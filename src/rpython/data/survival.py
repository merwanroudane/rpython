"""Event-history / survival data (section 16).

Envelope ``kind: "survival"``::

    {"kind": "survival", "type": "right"|"left"|"interval"|"counting"|"mstate",
     "time": [...], "time2": [...] | null, "event": [...],
     "event_levels": [...] | null,          # competing risks / multi-state
     "id": [...] | null, "strata": [...] | null, "start": ... ,
     "covariates": <table envelope> | null, "meta": {...}}

Maps onto ``survival::Surv`` in R (``Surv(time, event)``,
``Surv(time, time2, event, type="counting")``, ``type="interval2"``, or
``type="mstate"`` for competing risks) and onto :class:`SurvivalData`
(a thin pandas-backed structure usable with *lifelines* /
*scikit-survival*) in Python.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .context import Context
from .primitives import encode_values, decode_values
from .registry import Adapter, REGISTRY
from .semantic import Confidence, ConversionPath, Detection, Fidelity, SemanticRole


@dataclass
class SurvivalData:
    """``rp.survival(df, time="t", event="d")`` -- explicit event-history declaration."""

    data: pd.DataFrame
    time: str
    event: str
    time2: str | None = None           # stop time (counting process) or upper bound (interval)
    type: str = "right"                # right | left | interval | counting | mstate
    id: str | None = None
    strata: str | None = None
    event_levels: list[str] | None = None   # competing risks (mstate); first level = censored
    covariates: list[str] | None = None

    def describe_structure(self) -> str:
        n_events = int(pd.Series(self.data[self.event]).astype(float).fillna(0).ne(0).sum()) if self.type != "mstate" \
            else int((self.data[self.event].astype(str) != str((self.event_levels or ["censored"])[0])).sum())
        lines = ["Type: Survival / Event-History Data",
                 f"Censoring: {self.type}",
                 f"Time: {self.time}" + (f" → {self.time2}" if self.time2 else ""),
                 f"Event: {self.event}",
                 f"Observations: {len(self.data)}",
                 f"Events: {n_events}"]
        if self.id:
            lines.append(f"Subject: {self.id} ({self.data[self.id].nunique()} subjects, recurrent events: "
                         f"{'yes' if self.data[self.id].duplicated().any() else 'no'})")
        if self.strata:
            lines.append(f"Strata: {self.strata}")
        if self.event_levels:
            lines.append(f"Event types: {', '.join(self.event_levels)}")
        return "\n".join(lines)

    def to_lifelines(self) -> tuple[pd.Series, pd.Series]:
        return self.data[self.time], self.data[self.event]

    def to_sksurv(self) -> np.ndarray:
        return np.array(list(zip(self.data[self.event].astype(bool), self.data[self.time].astype(float))),
                        dtype=[("event", bool), ("time", float)])


def survival(data: pd.DataFrame, time: str, event: str, **kw: Any) -> SurvivalData:
    return SurvivalData(data, time, event, **kw)


class SurvivalAdapter(Adapter):
    family = "survival"
    kinds = ("survival",)
    tier = ConversionPath.ADAPTER
    priority = 8
    r_requires = ("survival",)

    def detect(self, obj: Any) -> Detection | None:
        if isinstance(obj, SurvivalData):
            return Detection("survival data", Confidence.CONFIRMED, "explicit declaration")
        return None

    def encode(self, obj: SurvivalData, ctx: Context) -> dict[str, Any]:
        from .tabular import encode_frame
        df = obj.data
        cov_cols = obj.covariates if obj.covariates is not None else [c for c in df.columns
                                                                      if c not in {obj.time, obj.time2, obj.event, obj.id, obj.strata}]
        time = encode_values(df[obj.time].to_numpy(dtype=float), "double", ctx)
        time2 = encode_values(df[obj.time2].to_numpy(dtype=float), "double", ctx) if obj.time2 else None
        if obj.type == "mstate":
            ev = df[obj.event].astype(str).tolist()
            levels = obj.event_levels or sorted(set(ev))
            event = ev
        else:
            levels = None
            event = encode_values(df[obj.event].to_numpy(dtype=float), "double", ctx)
        env: dict[str, Any] = {
            "rpx": 1, "kind": "survival", "type": obj.type, "time": time, "time2": time2, "event": event,
            "event_levels": levels,
            "id": None if not obj.id else df[obj.id].astype(str).tolist(),
            "strata": None if not obj.strata else df[obj.strata].astype(str).tolist(),
            "columns": {"time": obj.time, "time2": obj.time2, "event": obj.event, "id": obj.id, "strata": obj.strata},
            "covariates": encode_frame(df[cov_cols], ctx) if cov_cols else None,
            "meta": {"source_class": "rpython.SurvivalData", "n": int(len(df))},
        }
        roles = {obj.time: SemanticRole.DURATION.value, obj.event: SemanticRole.EVENT.value}
        if obj.id:
            roles[obj.id] = SemanticRole.ID.value
        env["roles"] = roles
        ctx.record("survival", ConversionPath.ADAPTER, "json",
                   f"{obj.type}-censored, n={len(df)} -> survival::Surv" + (" + covariate data.frame" if cov_cols else ""))
        ctx.plan.fidelity.set("values", Fidelity.LOSSLESS)
        ctx.plan.fidelity.set("semantics", Fidelity.LOSSLESS, "censoring type, subject, strata preserved")
        return env

    def decode(self, env: dict[str, Any], ctx: Context) -> SurvivalData:
        from .tabular import decode_frame
        cols = env.get("columns") or {}
        tname, ename = cols.get("time") or "time", cols.get("event") or "event"
        data: dict[str, Any] = {}
        if env.get("covariates"):
            cov = decode_frame(env["covariates"], ctx)
            data.update({c: cov[c].to_numpy() for c in cov.columns})
        data[tname] = _as_float(decode_values(env["time"], "double", ctx=ctx))
        if env.get("time2") is not None:
            data[cols.get("time2") or "time2"] = _as_float(decode_values(env["time2"], "double", ctx=ctx))
        if env.get("type") == "mstate":
            data[ename] = pd.Categorical(env["event"], categories=env.get("event_levels"))
        else:
            data[ename] = _as_float(decode_values(env["event"], "double", ctx=ctx))
        if env.get("id") is not None:
            data[cols.get("id") or "id"] = env["id"]
        if env.get("strata") is not None:
            data[cols.get("strata") or "strata"] = env["strata"]
        df = pd.DataFrame(data)
        ctx.record("survival", ConversionPath.ADAPTER, "json", "survival::Surv -> SurvivalData")
        ctx.plan.fidelity.set("semantics", Fidelity.LOSSLESS)
        return SurvivalData(df, tname, ename, time2=cols.get("time2") if env.get("time2") is not None else None,
                            type=env.get("type", "right"), id=cols.get("id") if env.get("id") is not None else None,
                            strata=cols.get("strata") if env.get("strata") is not None else None,
                            event_levels=env.get("event_levels"))


def _as_float(a: Any) -> np.ndarray:
    if isinstance(a, np.ndarray):
        return a.astype(float)
    return np.asarray(a.to_numpy(dtype=float, na_value=np.nan))


REGISTRY.register(SurvivalAdapter(), tested=True)
