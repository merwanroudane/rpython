"""Time series -- all major forms (sections 10, 12 of MASTER_PROMPT, 10 of the
universal spec).

A time series crosses the boundary as a ``table`` envelope whose
``semantics.timeseries`` block carries what a bare table cannot::

    {"time": "<column>", "value_columns": [...], "ids": [...],
     "frequency": "M", "r_frequency": 12, "regular": true, "tz": "UTC"|"naive",
     "start": "2020-01", "end": "2024-12", "n_periods": 60, "missing_periods": 2,
     "duplicate_timestamps": 0, "seasonal_period": 12, "r_class": "ts"|"xts"|"zoo"|"tsibble",
     "declared": true}

R side: ``ts``/``mts`` when regular with a classic frequency (1, 4, 12, 52,
7, 24 ...), ``xts`` (or ``zoo``) for timestamped / irregular series,
``tsibble`` for keyed series when installed; otherwise a data.frame with a
``rpython.timeseries`` attribute.  Nothing is dropped silently: frequency,
timezone, gaps and duplicates are always reported in Explain Mode.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .context import Context
from .registry import Adapter, REGISTRY
from .semantic import Confidence, ConversionPath, Detection, Fidelity
from .tabular import encode_frame, decode_frame

# pandas offset alias  ->  R ts frequency
_FREQ_TO_R: dict[str, int] = {
    "Y": 1, "A": 1, "YE": 1, "YS": 1, "AS": 1, "YE-DEC": 1, "A-DEC": 1, "YS-JAN": 1,
    "Q": 4, "QE": 4, "QS": 4, "QE-DEC": 4, "Q-DEC": 4, "QS-JAN": 4, "QS-OCT": 4,
    "M": 12, "ME": 12, "MS": 12,
    "W": 52, "W-SUN": 52, "W-MON": 52,
    "D": 365, "B": 260, "h": 24, "H": 24,
}
_R_TO_PERIOD: dict[int, str] = {1: "Y", 4: "Q", 12: "M"}
_SEASONAL: dict[int, int] = {12: 12, 4: 4, 52: 52, 7: 7, 24: 24, 365: 365}


def _canonical_freq(freq: Any) -> str | None:
    if freq is None:
        return None
    s = freq if isinstance(freq, str) else getattr(freq, "freqstr", str(freq))
    return s


def r_frequency(freq: str | None) -> int | None:
    if freq is None:
        return None
    base = freq.lstrip("0123456789")
    if base != freq:
        return None  # multiples like "2M": not a classic ts frequency
    return _FREQ_TO_R.get(base) or _FREQ_TO_R.get(base.split("-")[0])


@dataclass
class TimeSeries:
    """Explicit time-series declaration: ``rp.timeseries(df, time="date", freq="M")``."""

    data: pd.DataFrame | pd.Series
    time: str | None = None            # column name; None = index
    freq: str | None = None            # pandas offset alias, e.g. "M", "Q", "D", "h"
    ids: list[str] = field(default_factory=list)   # grouped / hierarchical keys
    seasonal_period: int | None = None
    tz: str | None = None
    duplicates: str = "keep"           # keep | error

    def frame(self) -> pd.DataFrame:
        d = self.data.to_frame() if isinstance(self.data, pd.Series) else self.data
        return d

    def describe_structure(self) -> str:
        sem = timeseries_semantics(self)
        lines = ["Type: Time Series",
                 f"Time: {sem['time']}",
                 f"Frequency: {sem['frequency'] or 'irregular'}",
                 f"Regular: {'Yes' if sem['regular'] else 'No'}",
                 f"Timezone: {sem['tz']}",
                 f"Periods: {sem['start']} – {sem['end']} ({sem['n_periods']})",
                 f"Missing periods: {sem['missing_periods']}",
                 f"Duplicate timestamps: {sem['duplicate_timestamps']}",
                 f"Series: {', '.join(sem['value_columns'])}"]
        if sem["ids"]:
            lines.append(f"Keys: {', '.join(sem['ids'])}")
        if sem["seasonal_period"]:
            lines.append(f"Seasonal period: {sem['seasonal_period']}")
        lines.append(f"R representation: {sem['r_class']}")
        return "\n".join(lines)


def timeseries(data: Any, time: str | None = None, freq: str | None = None, ids: list[str] | str | None = None,
               seasonal_period: int | None = None, tz: str | None = None) -> TimeSeries:
    """Declare a time series explicitly (public API ``rp.timeseries``)."""
    if isinstance(ids, str):
        ids = [ids]
    return TimeSeries(data, time=time, freq=freq, ids=list(ids or []), seasonal_period=seasonal_period, tz=tz)


def _time_index(ts: TimeSeries) -> pd.Index:
    df = ts.frame()
    if ts.time is not None:
        idx = pd.Index(df[ts.time])
    else:
        idx = df.index
    if isinstance(idx, pd.PeriodIndex):
        return idx
    if not isinstance(idx, pd.DatetimeIndex):
        try:
            idx = pd.DatetimeIndex(pd.to_datetime(idx))
        except Exception:
            return idx
    return idx


def timeseries_semantics(ts: TimeSeries, ctx: Context | None = None) -> dict[str, Any]:
    df = ts.frame()
    idx = _time_index(ts)
    key_frame = df if not ts.ids else df.drop(columns=ts.ids, errors="ignore")
    value_columns = [c for c in key_frame.columns if c != ts.time]
    if ts.ids:
        # per-key time index for gap detection; use the first key's series as representative
        first_key = df.groupby(ts.ids, sort=False).head(0) if False else None
    tidx = idx
    freq = ts.freq
    if freq is None:
        if isinstance(tidx, pd.PeriodIndex):
            freq = tidx.freqstr
        elif isinstance(tidx, pd.DatetimeIndex):
            freq = _canonical_freq(tidx.freq) or (pd.infer_freq(tidx.unique().sort_values()) if len(tidx.unique()) >= 3 and not ts.ids else None)
            if freq is None and ts.ids:
                sub = tidx[df[ts.ids].apply(tuple, axis=1) == df[ts.ids].apply(tuple, axis=1).iloc[0]] if len(df) else tidx
                freq = pd.infer_freq(sub) if len(sub) >= 3 else None
    dupes = int(pd.Index(list(zip(*[df[c] for c in ts.ids], tidx))).duplicated().sum()) if ts.ids else int(tidx.duplicated().sum())
    missing = 0
    regular = freq is not None
    if freq is not None and isinstance(tidx, (pd.DatetimeIndex, pd.PeriodIndex)) and len(tidx) > 1 and not ts.ids:
        u = tidx.unique().sort_values()
        try:
            full = pd.period_range(u[0], u[-1], freq=freq) if isinstance(u, pd.PeriodIndex) else pd.date_range(u[0], u[-1], freq=freq, tz=getattr(u, "tz", None))
            missing = int(len(full) - len(u))
            if missing < 0:
                missing, regular = 0, False
        except Exception:
            pass
    tz = ts.tz or ("naive" if getattr(tidx, "tz", None) is None else str(tidx.tz))
    rfreq = r_frequency(freq)
    if rfreq is not None and regular and missing == 0 and dupes == 0 and tz == "naive" and not ts.ids:
        r_class = "ts"
    elif ts.ids:
        r_class = "tsibble"
    elif isinstance(tidx, (pd.DatetimeIndex, pd.PeriodIndex)):
        r_class = "xts"
    else:
        r_class = "data.frame"
    start = str(tidx.min()) if len(tidx) else None
    end = str(tidx.max()) if len(tidx) else None
    r_start = None
    if rfreq in (1, 4, 12) and len(tidx):
        p = pd.Period(tidx.min(), freq=_R_TO_PERIOD[rfreq])
        r_start = [int(p.year), int(getattr(p, {"Y": "year", "Q": "quarter", "M": "month"}[_R_TO_PERIOD[rfreq]]))] if rfreq != 1 else [int(p.year), 1]
    elif rfreq is not None and len(tidx) and isinstance(tidx, pd.DatetimeIndex):
        t0 = tidx.min()
        r_start = [int(t0.year), int(t0.dayofyear if rfreq == 365 else t0.isocalendar().week if rfreq == 52 else 1)]
    sem = {"time": ts.time or (tidx.name or "index"), "value_columns": [str(c) for c in value_columns],
           "ids": list(ts.ids), "frequency": freq, "r_frequency": rfreq, "regular": bool(regular),
           "tz": tz, "start": start, "end": end, "r_start": r_start, "n_periods": int(len(tidx.unique())),
           "missing_periods": missing, "duplicate_timestamps": dupes,
           "seasonal_period": ts.seasonal_period or (_SEASONAL.get(rfreq) if rfreq else None),
           "r_class": r_class, "declared": ts.freq is not None or ts.time is not None,
           "index_kind": "period" if isinstance(tidx, pd.PeriodIndex) else "datetime" if isinstance(tidx, pd.DatetimeIndex) else "other"}
    return sem


class TimeSeriesAdapter(Adapter):
    family = "timeseries"
    kinds = ("timeseries",)
    tier = ConversionPath.ADAPTER
    priority = 6   # before TableAdapter (40)

    def detect(self, obj: Any) -> Detection | None:
        if isinstance(obj, TimeSeries):
            return Detection("time series", Confidence.CONFIRMED, "explicit rp.timeseries() declaration")
        if isinstance(obj, (pd.DataFrame, pd.Series)):
            if isinstance(obj.index, (pd.DatetimeIndex, pd.PeriodIndex)):
                if isinstance(obj, pd.DataFrame) and _has_geometry(obj):
                    return None
                return Detection("time series", Confidence.CONFIRMED,
                                 f"{type(obj.index).__name__} freq={_canonical_freq(obj.index.freq) or 'irregular'}")
            if isinstance(obj, pd.DataFrame):
                dcols = [c for c in obj.columns if obj[c].dtype.kind == "M"]
                if len(dcols) == 1 and len(obj) > 2:
                    return Detection("time series", Confidence.AMBIGUOUS,
                                     f"single datetime column {dcols[0]!r}; declare with rp.timeseries(df, time={dcols[0]!r})")
        return None

    def encode(self, obj: Any, ctx: Context) -> dict[str, Any]:
        ts = obj if isinstance(obj, TimeSeries) else TimeSeries(obj)
        sem = timeseries_semantics(ts, ctx)
        df = ts.frame()
        if ts.time is None:
            # index -> column so the table path carries it; remember the name
            name = df.index.name or "time"
            df = df.reset_index(names=name) if name not in df.columns else df.reset_index()
            sem["time"] = name
            sem["from_index"] = True
        if isinstance(ts.data, pd.Series):
            sem["series_name"] = ts.data.name
            sem["from_series"] = True
        env = encode_frame(df, ctx, semantics={"timeseries": sem})
        env["kind"] = "timeseries"
        if sem["duplicate_timestamps"] and ts.duplicates == "error":
            ctx.lossy("time series", f"{sem['duplicate_timestamps']} duplicate timestamps")
        if sem["r_class"] == "ts":
            ctx.record("timeseries", ConversionPath.ADAPTER, ctx.plan.backend,
                       f"regular {sem['frequency']} series -> R ts(frequency={sem['r_frequency']}, start={sem['r_start']})")
        elif sem["r_class"] == "xts":
            ctx.record("timeseries", ConversionPath.ADAPTER, ctx.plan.backend,
                       f"{'regular' if sem['regular'] else 'irregular'} timestamped series -> R xts (tz={sem['tz']})")
        else:
            ctx.record("timeseries", ConversionPath.ADAPTER, ctx.plan.backend, f"-> R {sem['r_class']}")
        ctx.plan.extra["Time index"] = f"{sem['time']} ({sem['index_kind']})"
        ctx.plan.extra["Frequency"] = sem["frequency"] or "irregular"
        ctx.plan.extra["Timezone"] = sem["tz"]
        if sem["missing_periods"]:
            ctx.plan.note(f"{sem['missing_periods']} missing period(s) preserved as gaps")
        if sem["duplicate_timestamps"]:
            ctx.plan.note(f"{sem['duplicate_timestamps']} duplicate timestamp(s) kept")
        ctx.plan.fidelity.set("temporal", Fidelity.LOSSLESS, "frequency, tz, gaps, duplicates in sidecar")
        ctx.plan.fidelity.set("index", Fidelity.LOSSLESS)
        return env

    def decode(self, env: dict[str, Any], ctx: Context) -> Any:
        sem = (env.get("semantics") or {}).get("timeseries") or {}
        df = decode_frame(env, ctx)
        time_col = sem.get("time")
        if sem.get("r_ts"):
            # came from an R ts/mts object: build PeriodIndex or numeric time index
            df = _index_from_r_ts(df, sem)
        elif time_col and time_col in df.columns and (sem.get("from_index") or sem.get("r_class") in ("xts", "zoo")):
            df = df.set_index(time_col)
            if sem.get("index_kind") == "period" and not isinstance(df.index, pd.PeriodIndex):
                try:
                    df.index = pd.PeriodIndex(df.index, freq=sem.get("frequency"))
                except Exception:
                    pass
            if sem.get("frequency") and isinstance(df.index, pd.DatetimeIndex) and not sem.get("missing_periods") and not sem.get("duplicate_timestamps"):
                try:
                    df.index.freq = sem["frequency"]
                except Exception:
                    pass
            if sem.get("from_index") and (env.get("index") or {}).get("names"):
                df.index.name = (env["index"]["names"] or [None])[0]
            elif time_col in ("index", "time") and sem.get("from_index"):
                df.index.name = None
        df.attrs["rpython"] = {**df.attrs.get("rpython", {}), "timeseries": {k: v for k, v in sem.items() if k not in ("from_index", "from_series")}}
        ctx.record("timeseries", ConversionPath.ADAPTER, ctx.plan.backend,
                   f"R {sem.get('r_class', 'time series')} -> pandas ({type(df.index).__name__})")
        ctx.plan.fidelity.set("temporal", Fidelity.LOSSLESS)
        if sem.get("from_series") and df.shape[1] == 1:
            s = df.iloc[:, 0]
            s.name = sem.get("series_name")
            s.attrs.update(df.attrs)
            if sem.get("from_index"):
                s.index.name = None if sem.get("time") in ("index", "time") else sem.get("time")
            return s
        if sem.get("r_ts") and df.shape[1] == 1 and not sem.get("mts"):
            s = df.iloc[:, 0]
            s.attrs.update(df.attrs)
            return s
        return df


def _has_geometry(df: pd.DataFrame) -> bool:
    return any(getattr(df[c].dtype, "name", "") == "geometry" for c in df.columns)


def _index_from_r_ts(df: pd.DataFrame, sem: dict[str, Any]) -> pd.DataFrame:
    freq = sem.get("r_frequency")
    start = sem.get("r_start") or [1, 1]
    n = len(df)
    if freq in _R_TO_PERIOD:
        pfreq = _R_TO_PERIOD[freq]
        if pfreq == "Y":
            p0 = pd.Period(year=int(start[0]), freq="Y")
        elif pfreq == "Q":
            p0 = pd.Period(year=int(start[0]), quarter=int(start[1]), freq="Q")
        else:
            p0 = pd.Period(year=int(start[0]), month=int(start[1]), freq="M")
        if sem.get("index_kind") == "datetime" and sem.get("frequency"):
            # came from a pandas DatetimeIndex: rebuild it with the original offset alias
            try:
                df.index = pd.date_range(p0.to_timestamp(how="start"), periods=n, freq=sem["frequency"])
            except Exception:
                df.index = pd.period_range(p0, periods=n, freq=pfreq)
        else:
            df.index = pd.period_range(p0, periods=n, freq=pfreq)
    else:
        t0 = float(start[0]) + (float(start[1]) - 1) / float(freq or 1)
        df.index = pd.Index(t0 + np.arange(n) / float(freq or 1), name="time")
    if "time" in df.columns and sem.get("time") == "time" and sem.get("time_from_r"):
        df = df.drop(columns=["time"])
    return df


REGISTRY.register(TimeSeriesAdapter(), tested=True,
                  limitations=("R ts frequencies other than 1/4/12 decode to a numeric time index (no calendar anchor)",
                               "ts cannot hold duplicate timestamps or timezones: such series go to xts instead"))
