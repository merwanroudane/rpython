"""Spatial / geospatial vector data (section 17).

Geometry travels as **WKB** (base64 in JSON, binary in Arrow); the CRS
travels as WKT2 + EPSG code + the user's original input string.

Envelope: ``table`` + ``semantics.spatial``::

    {"geometry_column": "geometry", "geometry_columns": ["geometry", "centroid"],
     "crs": {"wkt": "...", "epsg": 4326, "input": "EPSG:4326"} | null,
     "geometry_types": ["Polygon", "MultiPolygon"], "dimension": "XY",
     "n_empty": 0, "n_missing": 2, "bbox": [xmin, ymin, xmax, ymax], "axis_order": "authority"}

A single geometry uses ``kind: "geometry"`` with ``wkb`` + ``crs``.

Rules enforced here: the CRS is never assumed (no silent EPSG:4326),
coordinates are never transformed, the active geometry column and every
other geometry column keep their identity, empty and missing geometries
are preserved distinctly.
"""
from __future__ import annotations

import base64
from typing import Any

import pandas as pd

from .context import Context
from .registry import Adapter, REGISTRY
from .semantic import Confidence, ConversionPath, Detection, Fidelity, SemanticRole
from .tabular import encode_frame, decode_frame


def _shapely():
    try:
        import shapely
        return shapely
    except Exception:
        return None


def _is_geometry(obj: Any) -> bool:
    sh = _shapely()
    return sh is not None and isinstance(obj, sh.geometry.base.BaseGeometry)


def _is_geodataframe(obj: Any) -> bool:
    return type(obj).__module__.startswith("geopandas") and type(obj).__name__ == "GeoDataFrame"


def _is_geoseries(obj: Any) -> bool:
    return type(obj).__module__.startswith("geopandas") and type(obj).__name__ == "GeoSeries"


def crs_block(crs: Any) -> dict[str, Any] | None:
    """Describe a CRS as WKT + EPSG + original input without assuming anything."""
    if crs is None:
        return None
    try:
        import pyproj
        c = crs if isinstance(crs, pyproj.CRS) else pyproj.CRS.from_user_input(crs)
        epsg = c.to_epsg()
        return {"wkt": c.to_wkt(), "epsg": epsg, "input": str(crs) if not isinstance(crs, pyproj.CRS) else c.srs,
                "name": c.name, "is_geographic": bool(c.is_geographic),
                "axis_order": "authority"}
    except Exception:
        s = str(crs)
        epsg = None
        if s.upper().startswith("EPSG:"):
            try:
                epsg = int(s.split(":")[1])
            except Exception:
                pass
        return {"wkt": s if s.strip().upper().startswith(("GEOGCS", "PROJCS", "GEOGCRS", "PROJCRS", "BOUNDCRS")) else None,
                "epsg": epsg, "input": s, "name": None, "is_geographic": None, "axis_order": "authority"}


def crs_from_block(block: dict[str, Any] | None) -> Any:
    if not block:
        return None
    try:
        import pyproj
        if block.get("wkt"):
            return pyproj.CRS.from_wkt(block["wkt"])
        if block.get("epsg"):
            return pyproj.CRS.from_epsg(block["epsg"])
        return pyproj.CRS.from_user_input(block["input"])
    except Exception:
        return block.get("input") or (f"EPSG:{block['epsg']}" if block.get("epsg") else block.get("wkt"))


def _geom_to_wkb64(g: Any) -> str | None:
    if g is None:
        return None
    try:
        if pd.isna(g):
            return None
    except Exception:
        pass
    return base64.b64encode(g.wkb).decode("ascii")


def _wkb64_to_geom(s: str | None) -> Any:
    if s is None:
        return None
    from shapely import wkb
    return wkb.loads(base64.b64decode(s))


def _geometry_stats(geoms: list[Any]) -> dict[str, Any]:
    sh = _shapely()
    types: set[str] = set()
    n_empty = n_missing = 0
    has_z = has_m = False
    xs: list[float] = []
    for g in geoms:
        if g is None:
            n_missing += 1
            continue
        if g.is_empty:
            n_empty += 1
        types.add(g.geom_type)
        has_z = has_z or bool(getattr(g, "has_z", False))
        has_m = has_m or bool(getattr(g, "has_m", False))
    valid = [g for g in geoms if g is not None and not g.is_empty]
    bbox = None
    if valid and sh is not None:
        b = sh.total_bounds(sh.from_wkb([g.wkb for g in valid])) if hasattr(sh, "total_bounds") else None
        if b is not None:
            bbox = [float(v) for v in b]
    return {"geometry_types": sorted(types), "dimension": "XY" + ("Z" if has_z else "") + ("M" if has_m else ""),
            "n_empty": n_empty, "n_missing": n_missing, "bbox": bbox}


class SpatialAdapter(Adapter):
    family = "spatial"
    kinds = ("spatial", "geometry")
    tier = ConversionPath.STANDARD
    priority = 10
    requires = ("shapely",)
    r_requires = ("sf",)

    def detect(self, obj: Any) -> Detection | None:
        if _is_geodataframe(obj):
            crs = getattr(obj, "crs", None)
            return Detection("spatial vector (GeoDataFrame)", Confidence.CONFIRMED,
                             f"CRS {crs.to_string() if crs is not None else 'undefined'}")
        if _is_geoseries(obj):
            return Detection("spatial vector (GeoSeries)", Confidence.CONFIRMED, "geopandas")
        if _is_geometry(obj):
            return Detection("geometry", Confidence.CONFIRMED, obj.geom_type)
        if isinstance(obj, pd.DataFrame):
            block = (obj.attrs or {}).get("rpython", {}).get("spatial") if isinstance(obj.attrs.get("rpython"), dict) else None
            if block:
                return Detection("spatial vector", Confidence.CONFIRMED, "spatial metadata in df.attrs")
            geom_cols = [c for c in obj.columns if len(obj) and all(_is_geometry(v) or v is None for v in obj[c].head(20))
                         and any(_is_geometry(v) for v in obj[c].head(20))]
            if geom_cols:
                return Detection("spatial vector", Confidence.INFERRED,
                                 f"shapely geometries in column(s) {geom_cols}; CRS unknown (not assumed)")
            if {"lat", "lon"} <= {str(c).lower() for c in obj.columns} or {"latitude", "longitude"} <= {str(c).lower() for c in obj.columns}:
                return Detection("spatial points", Confidence.AMBIGUOUS,
                                 "lat/lon-like columns; declare with rp.spatial(df, lon=..., lat=..., crs=...)")
        return None

    # ------------------------------------------------------------------ encode
    def encode(self, obj: Any, ctx: Context) -> dict[str, Any]:
        if _is_geometry(obj):
            env = {"rpx": 1, "kind": "geometry", "wkb": _geom_to_wkb64(obj), "crs": None,
                   "geometry_type": obj.geom_type, "meta": {"source_class": "shapely"}}
            ctx.record("geometry", ConversionPath.STANDARD, "wkb", f"{obj.geom_type} -> sf::st_as_sfc(WKB)")
            ctx.plan.fidelity.set("values", Fidelity.LOSSLESS)
            ctx.plan.fidelity.set("crs", Fidelity.NA, "single geometry carries no CRS")
            return env
        if _is_geoseries(obj):
            gdf = obj.to_frame(name=obj.name or "geometry")
            gdf = type(obj).__module__ and __import__("geopandas").GeoDataFrame(gdf, geometry=obj.name or "geometry", crs=obj.crs)
            obj = gdf
        if _is_geodataframe(obj):
            active = obj.geometry.name
            geom_cols = [c for c in obj.columns if str(obj[c].dtype) == "geometry"]
            crs_by_col = {c: crs_block(obj[c].crs) for c in geom_cols}
            df = pd.DataFrame(obj)
        else:
            block = (obj.attrs.get("rpython") or {}).get("spatial") or {}
            geom_cols = block.get("geometry_columns") or [c for c in obj.columns if any(_is_geometry(v) for v in obj[c].head(20))]
            active = block.get("geometry_column") or geom_cols[0]
            crs_by_col = {c: block.get("crs") if c == active else block.get("crs_by_column", {}).get(c) for c in geom_cols}
            if crs_by_col.get(active) is None:
                ctx.warn(f"geometry column {active!r} has no CRS: sf will receive NA_crs_ (EPSG:4326 is never assumed)")
            df = obj
        # geometry -> WKB columns
        plain = df.copy()
        for c in geom_cols:
            plain[c] = [ _geom_to_wkb64(g) for g in df[c] ]
        stats = _geometry_stats([g if _is_geometry(g) else None for g in df[active]])
        block = {"geometry_column": active, "geometry_columns": geom_cols, "crs": crs_by_col.get(active),
                 "crs_by_column": crs_by_col, "encoding": "wkb-base64", **stats}
        env = encode_frame(plain, ctx, semantics={"spatial": block, "roles": {active: SemanticRole.GEOMETRY.value}}, class_hint="sf")
        for col in env["columns"]:
            if col["name"] in geom_cols:
                col["type"] = "geometry"
                col["semantic"]["geometry"] = {"encoding": "wkb-base64", "crs": crs_by_col.get(col["name"])}
        env["kind"] = "spatial"
        crs_txt = (block["crs"] or {}).get("input") or (f"EPSG:{block['crs']['epsg']}" if block["crs"] and block["crs"].get("epsg") else "undefined")
        ctx.record("spatial", ConversionPath.STANDARD, ctx.plan.backend + "+wkb",
                   f"{len(df):,} features, {'/'.join(stats['geometry_types']) or 'empty'}, CRS {crs_txt} -> sf")
        ctx.plan.extra["Geometry"] = "/".join(stats["geometry_types"]) or "none"
        ctx.plan.extra["CRS"] = crs_txt
        ctx.plan.extra["CRS preserved"] = "yes" if block["crs"] else "no CRS on source (kept undefined)"
        ctx.plan.extra["Geometry preserved"] = "yes (WKB)"
        ctx.plan.extra["Spatial index"] = "rebuilt on target"
        ctx.plan.fidelity.set("crs", Fidelity.LOSSLESS if block["crs"] else Fidelity.NA)
        ctx.plan.fidelity.set("topology", Fidelity.LOSSLESS, "WKB")
        ctx.plan.fidelity.set("index", Fidelity.REBUILT, "spatial index rebuilt, not transferred")
        return env

    # ------------------------------------------------------------------ decode
    def decode(self, env: dict[str, Any], ctx: Context) -> Any:
        if env.get("kind") == "geometry":
            g = _wkb64_to_geom(env.get("wkb"))
            ctx.record("geometry", ConversionPath.STANDARD, "wkb", "sfg -> shapely")
            return g
        block = (env.get("semantics") or {}).get("spatial") or {}
        df = decode_frame(env, ctx)
        geom_cols = block.get("geometry_columns") or [block.get("geometry_column", "geometry")]
        for c in geom_cols:
            if c in df.columns:
                df[c] = [ _wkb64_to_geom(v) if isinstance(v, str) else (_wkb_bytes(v) if isinstance(v, (bytes, bytearray)) else None) for v in df[c] ]
        active = block.get("geometry_column") or geom_cols[0]
        crs = crs_from_block(block.get("crs"))
        try:
            import geopandas as gpd
            gdf = gpd.GeoDataFrame(df, geometry=active, crs=crs)
            for c in geom_cols:
                if c != active:
                    gdf[c] = gpd.GeoSeries(gdf[c], crs=crs_from_block((block.get("crs_by_column") or {}).get(c)))
            out: Any = gdf
            ctx.record("spatial", ConversionPath.STANDARD, ctx.plan.backend + "+wkb", "sf -> geopandas.GeoDataFrame")
        except Exception:
            df.attrs["rpython"] = {**df.attrs.get("rpython", {}), "spatial": block}
            out = df
            ctx.record("spatial", ConversionPath.STANDARD, ctx.plan.backend + "+wkb",
                       "sf -> pandas + shapely (geopandas not installed; CRS kept in df.attrs)")
            ctx.plan.note("install geopandas for a GeoDataFrame: pip install 'rpython[spatial]'")
        ctx.plan.fidelity.set("crs", Fidelity.LOSSLESS if block.get("crs") else Fidelity.NA)
        ctx.plan.fidelity.set("topology", Fidelity.LOSSLESS)
        return out


def _wkb_bytes(b: bytes) -> Any:
    from shapely import wkb
    return wkb.loads(bytes(b))


def spatial(df: pd.DataFrame, geometry: str | None = None, crs: Any = None, lon: str | None = None,
            lat: str | None = None) -> Any:
    """Declare spatial structure: ``rp.spatial(df, geometry="geom", crs="EPSG:3035")`` or
    ``rp.spatial(df, lon="x", lat="y", crs="EPSG:4326")``.  ``crs`` is *required* to be
    stated by the user when unknown from the object -- it is never assumed."""
    sh = _shapely()
    if sh is None:
        raise ImportError("rp.spatial needs shapely: pip install 'rpython[spatial]'")
    out = df.copy()
    if lon is not None and lat is not None:
        out["geometry"] = [sh.Point(x, y) if pd.notna(x) and pd.notna(y) else None for x, y in zip(df[lon], df[lat])]
        geometry = "geometry"
    geometry = geometry or "geometry"
    try:
        import geopandas as gpd
        return gpd.GeoDataFrame(out, geometry=geometry, crs=crs)
    except Exception:
        out.attrs["rpython"] = {**out.attrs.get("rpython", {}),
                                "spatial": {"geometry_column": geometry, "geometry_columns": [geometry], "crs": crs_block(crs)}}
        return out


REGISTRY.register(SpatialAdapter(), tested=True,
                  limitations=("Spatial indexes are rebuilt on the target, never transferred",
                               "Without geopandas the Python side returns pandas + shapely with CRS in df.attrs"))
