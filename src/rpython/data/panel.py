"""Panel / longitudinal, cross-sectional, repeated cross-section and
hierarchical (multilevel) data (sections 11-14).

All four families travel as ``table`` envelopes with a
``semantics.panel`` block::

    {"kind": "panel"|"cross_section"|"repeated_cross_section"|"hierarchical",
     "id": "country", "time": "year", "balanced": false, "n_entities": 48,
     "n_periods": 26, "duplicates": 0, "gaps": 14, "frequency": "A",
     "sorted": true, "weight": "w", "cluster": "region", "strata": "s",
     "cohort": null, "wave": "survey_year", "levels": ["school", "class"],
     "r_class": "pdata.frame"|"data.frame"}

R side: ``plm::pdata.frame`` (when *plm* is installed) or a data.frame
carrying the same block as the ``rpython.panel`` attribute.  The Python
side returns a DataFrame indexed by ``(id, time)`` -- what
``linearmodels`` expects -- with the block in ``df.attrs["rpython"]``.

Auto-detection only ever produces *suggestions* (section 69).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from .context import Context
from .registry import Adapter, REGISTRY
from .semantic import Confidence, ConversionPath, Detection, Fidelity, SemanticRole
from .tabular import encode_frame, decode_frame
from .temporal import _canonical_freq


@dataclass
class Panel:
    """``rp.panel(df, id="country", time="year")``."""

    data: pd.DataFrame
    id: str | list[str]
    time: str
    weight: str | None = None
    cluster: str | None = None
    strata: str | None = None
    cohort: str | None = None
    freq: str | None = None
    kind: str = "panel"
    roles: dict[str, str] = field(default_factory=dict)

    @property
    def ids(self) -> list[str]:
        return [self.id] if isinstance(self.id, str) else list(self.id)

    def frame(self) -> pd.DataFrame:
        df = self.data
        if isinstance(df.index, pd.MultiIndex) and all(n in df.index.names for n in [*self.ids, self.time]):
            df = df.reset_index()
        return df

    def structure(self) -> dict[str, Any]:
        return panel_semantics(self)

    def describe_structure(self) -> str:
        s = self.structure()
        lines = ["Type: Panel Data" if self.kind == "panel" else f"Type: {self.kind.replace('_', ' ').title()}",
                 f"Entity: {', '.join(self.ids)}",
                 f"Time: {self.time}",
                 f"Frequency: {s['frequency'] or 'unknown'}",
                 f"Entities: {s['n_entities']}",
                 f"Periods: {s['first_period']}–{s['last_period']} ({s['n_periods']})",
                 f"Balanced: {'Yes' if s['balanced'] else 'No'}",
                 f"Duplicates: {s['duplicates']}",
                 f"Missing periods: {s['gaps']}",
                 f"Sorted: {'Yes' if s['sorted'] else 'No'}"]
        for k in ("weight", "cluster", "strata", "cohort"):
            if s.get(k):
                lines.append(f"{k.capitalize()}: {s[k]}")
        lines.append(f"R representation: {s['r_class']}")
        return "\n".join(lines)


def panel(data: pd.DataFrame, id: str | list[str] | None = None, time: str | None = None, **kw: Any) -> Panel:
    """Declare panel structure explicitly (public API ``rp.panel``)."""
    if id is None or time is None:
        if isinstance(data.index, pd.MultiIndex) and data.index.nlevels == 2:
            id = id or data.index.names[0]
            time = time or data.index.names[1]
        else:
            raise ValueError("rp.panel() needs id= and time= (auto-detection is suggestion-only, never silent)")
    return Panel(data, id, time, **kw)


def cross_section(data: pd.DataFrame, id: str | None = None, weight: str | None = None,
                  strata: str | None = None, cluster: str | None = None) -> Panel:
    return Panel(data, id or "", "", weight=weight, strata=strata, cluster=cluster, kind="cross_section")


def repeated_cross_section(data: pd.DataFrame, wave: str, id: str | None = None, weight: str | None = None,
                           strata: str | None = None, cluster: str | None = None) -> Panel:
    """Repeated cross-sections: independent samples per wave (never a panel)."""
    return Panel(data, id or "", wave, weight=weight, strata=strata, cluster=cluster, kind="repeated_cross_section")


def hierarchical(data: pd.DataFrame, levels: list[str], time: str | None = None, weight: str | None = None) -> Panel:
    """Nested / multilevel data: ``levels`` ordered from outermost to innermost."""
    p = Panel(data, list(levels), time or "", weight=weight, kind="hierarchical")
    return p


def panel_semantics(p: Panel, ctx: Context | None = None) -> dict[str, Any]:
    df = p.frame()
    ids, time = p.ids, p.time
    sem: dict[str, Any] = {"kind": p.kind, "id": p.id, "time": time or None, "weight": p.weight,
                           "cluster": p.cluster, "strata": p.strata, "cohort": p.cohort,
                           "levels": ids if p.kind == "hierarchical" else None, "roles": dict(p.roles)}
    have_ids = all(i in df.columns for i in ids if i)
    have_time = bool(time) and time in df.columns
    n_ent = int(df[ids].drop_duplicates().shape[0]) if have_ids and ids and ids[0] else int(len(df))
    if have_time:
        t = df[time]
        n_per = int(t.nunique(dropna=True))
        first, last = (str(t.min()), str(t.max())) if len(t) else (None, None)
        freq = p.freq
        if freq is None and t.dtype.kind == "M":
            u = pd.DatetimeIndex(t.dropna().unique()).sort_values()
            freq = pd.infer_freq(u) if len(u) >= 3 else None
        elif freq is None and pd.api.types.is_integer_dtype(t):
            u = sorted(t.dropna().unique())
            freq = "A" if len(u) >= 2 and all(b - a == 1 for a, b in zip(u, u[1:])) else None
        elif freq is None and isinstance(t.dtype, pd.PeriodDtype):
            freq = t.dt.freq.freqstr
    else:
        n_per, first, last, freq = 1, None, None, None
    if have_ids and have_time and ids[0]:
        keys = df[[*ids, time]]
        dups = int(keys.duplicated().sum())
        counts = df.groupby(ids, sort=False, dropna=False)[time].nunique()
        balanced = bool(counts.nunique() == 1 and counts.iloc[0] == n_per) if len(counts) else True
        gaps = int((n_per - counts).clip(lower=0).sum())
        sorted_ = bool(keys.equals(keys.sort_values([*ids, time]).reset_index(drop=True)))
    else:
        dups, balanced, gaps, sorted_ = 0, True, 0, True
    if p.kind == "repeated_cross_section":
        balanced = False
        gaps = 0
    sem.update({"n_entities": n_ent, "n_periods": n_per, "first_period": first, "last_period": last,
                "frequency": _canonical_freq(freq), "balanced": balanced, "duplicates": dups, "gaps": gaps,
                "sorted": sorted_, "n_obs": int(len(df)),
                "r_class": "pdata.frame" if p.kind == "panel" and dups == 0 else "data.frame"})
    return sem


class PanelAdapter(Adapter):
    family = "panel"
    kinds = ("panel",)
    tier = ConversionPath.ADAPTER
    priority = 5   # before timeseries (30) and table (40)

    def detect(self, obj: Any) -> Detection | None:
        if isinstance(obj, Panel):
            return Detection(obj.kind.replace("_", " "), Confidence.CONFIRMED, "explicit declaration")
        if isinstance(obj, pd.DataFrame):
            attrs = (obj.attrs or {}).get("rpython", {})
            if isinstance(attrs, dict) and attrs.get("panel"):
                return Detection("panel", Confidence.CONFIRMED, "panel metadata in df.attrs")
            if isinstance(obj.index, pd.MultiIndex) and obj.index.nlevels == 2 and all(obj.index.names):
                lvl1 = obj.index.get_level_values(1)
                if lvl1.dtype.kind in "Mi" or isinstance(lvl1, pd.PeriodIndex):
                    return Detection("panel", Confidence.AMBIGUOUS,
                                     f"{obj.index.names[0]} × {obj.index.names[1]} MultiIndex; declare with rp.panel(df)")
            sug = _suggest_panel_columns(obj)
            if sug:
                return Detection("panel", Confidence.AMBIGUOUS, f"{sug[0]} × {sug[1]}; declare with rp.panel(df, id={sug[0]!r}, time={sug[1]!r})")
        return None

    def encode(self, obj: Any, ctx: Context) -> dict[str, Any]:
        if isinstance(obj, pd.DataFrame):
            block = obj.attrs["rpython"]["panel"]
            obj = Panel(obj, block["id"], block["time"], weight=block.get("weight"), cluster=block.get("cluster"),
                        strata=block.get("strata"), cohort=block.get("cohort"), kind=block.get("kind", "panel"))
        p: Panel = obj
        sem = panel_semantics(p, ctx)
        roles = {**({i: SemanticRole.ENTITY.value for i in p.ids if i}),
                 **({p.time: SemanticRole.TIME.value} if p.time else {}),
                 **({p.weight: SemanticRole.WEIGHT.value} if p.weight else {}),
                 **({p.cluster: SemanticRole.CLUSTER.value} if p.cluster else {}),
                 **({p.strata: SemanticRole.STRATA.value} if p.strata else {}),
                 **p.roles}
        sem["roles"] = roles
        env = encode_frame(p.frame(), ctx, semantics={"panel": sem})
        env["kind"] = "panel"
        ctx.plan.roles = roles if hasattr(ctx.plan, "roles") else None
        ctx.record("panel", ConversionPath.ADAPTER, ctx.plan.backend,
                   f"{p.kind}: {sem['n_entities']} entities x {sem['n_periods']} periods -> R {sem['r_class']}")
        ctx.plan.extra["Entity key"] = ", ".join(p.ids) if p.ids and p.ids[0] else "-"
        ctx.plan.extra["Time key"] = p.time or "-"
        ctx.plan.extra["Balanced"] = "yes" if sem["balanced"] else "no"
        if sem["duplicates"]:
            ctx.plan.note(f"{sem['duplicates']} duplicate entity-time keys: plm::pdata.frame cannot index them, "
                          "data.frame with rpython.panel attribute used instead")
        if sem["gaps"]:
            ctx.plan.note(f"{sem['gaps']} missing entity-period cells (unbalanced)")
        ctx.plan.fidelity.set("semantics", Fidelity.LOSSLESS, "entity/time/balance/gaps/duplicates in sidecar")
        return env

    def decode(self, env: dict[str, Any], ctx: Context) -> Any:
        sem = (env.get("semantics") or {}).get("panel") or {}
        df = decode_frame(env, ctx)
        ids = sem.get("id")
        ids = [ids] if isinstance(ids, str) else list(ids or [])
        time = sem.get("time")
        if sem.get("kind", "panel") == "panel" and ids and time and all(c in df.columns for c in [*ids, time]):
            if not sem.get("duplicates"):
                df = df.set_index([*ids, time])
        df.attrs["rpython"] = {**df.attrs.get("rpython", {}), "panel": sem}
        ctx.record("panel", ConversionPath.ADAPTER, ctx.plan.backend,
                   f"R {sem.get('r_class', 'panel')} -> pandas MultiIndex({', '.join([*ids, time] if time else ids)})")
        ctx.plan.fidelity.set("semantics", Fidelity.LOSSLESS)
        return df


def _suggest_panel_columns(df: pd.DataFrame) -> tuple[str, str] | None:
    """Very conservative heuristic; result is only ever a suggestion."""
    if len(df) < 6 or df.shape[1] < 3:
        return None
    time_cands = [c for c in df.columns if df[c].dtype.kind == "M" or isinstance(df[c].dtype, pd.PeriodDtype)
                  or (pd.api.types.is_integer_dtype(df[c]) and df[c].between(1800, 2200).all() and 2 <= df[c].nunique() < len(df))]
    id_cands = [c for c in df.columns if c not in time_cands and (df[c].dtype.kind in "OU" or isinstance(df[c].dtype, pd.CategoricalDtype)
                or str(df[c].dtype) in ("str", "string")) and 1 < df[c].nunique() < len(df)]
    for t in time_cands:
        if df[t].nunique() >= len(df):      # time never repeats across rows: not a panel
            continue
        for i in id_cands:
            if not df[[i, t]].duplicated().any() and df.groupby(i, observed=True)[t].nunique().min() > 1:
                return i, t
    return None


REGISTRY.register(PanelAdapter(), tested=True,
                  limitations=("plm::pdata.frame requires unique (id, time) keys; duplicates fall back to data.frame + attribute",))
