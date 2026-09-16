"""Spatiotemporal data (sections 19-20): spatial panels, trajectories,
moving objects, point events over time, spatial time series, raster
time stacks.

Envelope: ``table`` + **both** ``semantics.spatial`` and
``semantics.timeseries``/``semantics.panel`` blocks (``kind:
"spatiotemporal"``).  A raster time stack is a ``raster_ref`` whose
header carries the ``time`` coordinate.  No conversion may keep one of
the two semantics while silently dropping the other.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from .context import Context
from .registry import Adapter, REGISTRY
from .semantic import Confidence, ConversionPath, Detection, Fidelity, SemanticRole
from .spatial import SpatialAdapter, crs_block, _is_geodataframe, _is_geometry, _geom_to_wkb64, _wkb64_to_geom
from .tabular import encode_frame, decode_frame
from .panel import Panel, panel_semantics
from .temporal import TimeSeries, timeseries_semantics


@dataclass
class SpatioTemporal:
    """``rp.spatiotemporal(gdf, time="date", id="station", kind="trajectory")``.

    ``kind``: ``"spatial_panel"`` (fixed geometries observed over time),
    ``"trajectory"`` (moving objects: id + ordered timestamps + points),
    ``"events"`` (point events over time), ``"spatial_timeseries"``.
    """

    data: pd.DataFrame
    time: str
    id: str | None = None
    geometry: str = "geometry"
    crs: Any = None
    kind: str = "spatial_panel"
    freq: str | None = None
    segment: str | None = None   # trajectory segment / trip id

    def describe_structure(self) -> str:
        sem = spatiotemporal_semantics(self)
        sp, tp = sem["spatial"], sem["temporal"]
        lines = [f"Type: Spatiotemporal ({self.kind.replace('_', ' ')})",
                 f"Geometry: {'/'.join(sp['geometry_types']) or 'none'} in {self.geometry!r}",
                 f"CRS: {(sp['crs'] or {}).get('input') or 'undefined'}",
                 f"Time: {self.time} ({tp.get('frequency') or 'irregular'})"]
        if self.id:
            lines.append(f"Objects: {self.id} ({self.data[self.id].nunique()})")
        if self.segment:
            lines.append(f"Segments: {self.segment}")
        lines.append(f"Observations: {len(self.data)}")
        return "\n".join(lines)


def spatiotemporal(data: pd.DataFrame, time: str, id: str | None = None, geometry: str = "geometry",
                   crs: Any = None, kind: str = "spatial_panel", **kw: Any) -> SpatioTemporal:
    if crs is None and _is_geodataframe(data):
        crs = data.crs
    elif crs is None and isinstance(getattr(data, "attrs", {}).get("rpython"), dict):
        from .spatial import crs_from_block
        crs = crs_from_block((data.attrs["rpython"].get("spatial") or {}).get("crs"))
    return SpatioTemporal(data, time, id=id, geometry=geometry, crs=crs, kind=kind, **kw)


def spatiotemporal_semantics(st: SpatioTemporal) -> dict[str, Any]:
    from .spatial import _geometry_stats
    df = pd.DataFrame(st.data)
    stats = _geometry_stats([g if _is_geometry(g) else None for g in df[st.geometry]])
    spatial = {"geometry_column": st.geometry, "geometry_columns": [st.geometry], "crs": crs_block(st.crs),
               "encoding": "wkb-base64", **stats}
    if st.id:
        temporal = panel_semantics(Panel(df.drop(columns=[st.geometry]), st.id, st.time, freq=st.freq))
        temporal["kind"] = "panel"
    else:
        temporal = timeseries_semantics(TimeSeries(df.drop(columns=[st.geometry]), time=st.time, freq=st.freq))
        temporal["kind"] = "timeseries"
    return {"kind": st.kind, "spatial": spatial, "temporal": temporal, "id": st.id, "time": st.time,
            "segment": st.segment, "ordered_by_time": bool(df.sort_values([c for c in (st.id, st.time) if c]).index.equals(df.index)) if len(df) else True}


class SpatioTemporalAdapter(Adapter):
    family = "spatiotemporal"
    kinds = ("spatiotemporal",)
    tier = ConversionPath.ADAPTER
    priority = 9
    requires = ("shapely",)
    r_requires = ("sf",)

    def detect(self, obj: Any) -> Detection | None:
        if isinstance(obj, SpatioTemporal):
            return Detection("spatiotemporal", Confidence.CONFIRMED, obj.kind)
        if _is_geodataframe(obj):
            tcols = [c for c in obj.columns if obj[c].dtype.kind == "M"]
            if len(tcols) == 1:
                return Detection("spatiotemporal", Confidence.AMBIGUOUS,
                                 f"GeoDataFrame with datetime column {tcols[0]!r}; declare with rp.spatiotemporal(gdf, time={tcols[0]!r})")
        return None

    def encode(self, obj: SpatioTemporal, ctx: Context) -> dict[str, Any]:
        sem = spatiotemporal_semantics(obj)
        df = pd.DataFrame(obj.data).copy()
        df[obj.geometry] = [_geom_to_wkb64(g) if _is_geometry(g) else None for g in df[obj.geometry]]
        roles = {obj.geometry: SemanticRole.GEOMETRY.value, obj.time: SemanticRole.TIME.value}
        if obj.id:
            roles[obj.id] = SemanticRole.ENTITY.value
        env = encode_frame(df, ctx, semantics={"spatiotemporal": sem, "spatial": sem["spatial"],
                                                sem["temporal"]["kind"]: sem["temporal"], "roles": roles}, class_hint="sf")
        for col in env["columns"]:
            if col["name"] == obj.geometry:
                col["type"] = "geometry"
                col["semantic"]["geometry"] = {"encoding": "wkb-base64", "crs": sem["spatial"]["crs"]}
        env["kind"] = "spatiotemporal"
        ctx.record("spatiotemporal", ConversionPath.ADAPTER, ctx.plan.backend + "+wkb",
                   f"{obj.kind}: {len(df):,} obs, CRS {(sem['spatial']['crs'] or {}).get('input') or 'undefined'}, "
                   f"time {obj.time} -> sf + {sem['temporal']['kind']} attributes")
        ctx.plan.fidelity.set("crs", Fidelity.LOSSLESS if sem["spatial"]["crs"] else Fidelity.NA)
        ctx.plan.fidelity.set("temporal", Fidelity.LOSSLESS)
        ctx.plan.fidelity.set("topology", Fidelity.LOSSLESS, "WKB")
        return env

    def decode(self, env: dict[str, Any], ctx: Context) -> SpatioTemporal:
        sem = (env.get("semantics") or {}).get("spatiotemporal") or {}
        df = decode_frame(env, ctx)
        gcol = (sem.get("spatial") or {}).get("geometry_column", "geometry")
        if gcol in df.columns:
            df[gcol] = [_wkb64_to_geom(v) if isinstance(v, str) else None for v in df[gcol]]
        from .spatial import crs_from_block
        crs = crs_from_block((sem.get("spatial") or {}).get("crs"))
        try:
            import geopandas as gpd
            df = gpd.GeoDataFrame(df, geometry=gcol, crs=crs)
        except Exception:
            pass
        ctx.record("spatiotemporal", ConversionPath.ADAPTER, ctx.plan.backend + "+wkb", "sf + time -> SpatioTemporal")
        return SpatioTemporal(df, sem.get("time") or "time", id=sem.get("id"), geometry=gcol, crs=crs,
                              kind=sem.get("kind", "spatial_panel"), segment=sem.get("segment"))


REGISTRY.register(SpatioTemporalAdapter(), tested=True)
