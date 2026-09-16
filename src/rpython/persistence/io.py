"""Family-aware persistence (design spec §31 / §66-67).

``rp.save(obj, path)`` picks the writer from the *object family* and the
file extension, and warns (or refuses, per policy) when the format
cannot hold the object's semantics.  ``rp.load(path)`` restores the
object, reading the semantic sidecar / bundle when present.

Formats: csv/tsv, xlsx, parquet, feather/arrow, json, npy/npz, pickle
(warned), rds/RData (through R), dta/sav/xpt (pyreadstat), nc (xarray),
gpkg/geojson/geoparquet (geopandas), tif (rasterio), graphml/gexf
(networkx), zarr, and the ``.rpx`` bundle for anything richer.

The bundle (section 67)::

    name.rpx/
      manifest.json           version, family, python/R versions, created
      semantic_metadata.json  SemanticObject description + fidelity
      portable/               envelope.json (+ Arrow IPC parts)
      native/                 object.rds | object.pickle when requested
"""
from __future__ import annotations

import json
import os
import pickle
import shutil
import warnings
from typing import Any

from ..data.context import Context, ConversionError
from ..data.convert import to_envelope, from_envelope, _json_default
from ..data.semantic import Runtime


_LOSSY_FORMATS = {".csv": "CSV keeps values only: dtypes, categories/order, timezone, index and any panel/time-series metadata are lost",
                  ".tsv": "TSV keeps values only (see CSV)",
                  ".xlsx": "Excel keeps values and basic types only; categories, timezones and semantic metadata are lost",
                  ".json": "JSON keeps values and names; dtypes and semantic metadata are lost unless a sidecar is written"}


def _family_of(obj: Any) -> str:
    from ..data.registry import REGISTRY
    from ..data.convert import ensure_adapters
    ensure_adapters()
    found = REGISTRY.detect(obj)
    return found[0].family if found else "unknown"


def save(obj: Any, path: str, *, sidecar: bool = True, session: Any = None, allow_lossy: bool | None = None, **kw: Any) -> str:
    """Save ``obj`` to ``path``; the format is chosen from the extension (``.rpx`` = universal bundle)."""
    import pandas as pd
    import numpy as np
    from ..config import get_config
    ext = os.path.splitext(path)[1].lower()
    family = _family_of(obj)
    lossy_note = _LOSSY_FORMATS.get(ext)
    rich = family not in ("table", "scalar", "collection", "array")
    policy = get_config().lossy if allow_lossy is None else ("allow" if allow_lossy else "error")

    if ext == ".rpx" or ext == "":
        return save_bundle(obj, path if ext else path + ".rpx", session=session)

    if lossy_note and (rich or ext in (".csv", ".tsv", ".xlsx")):
        msg = f"Saving a {family} object as {ext}: {lossy_note}."
        if rich and policy == "error":
            raise ConversionError(msg, cause="format cannot hold the object's semantics",
                                  fix=f"use rp.save(obj, '{os.path.splitext(path)[0]}.rpx') or a richer format")
        if policy != "allow":
            warnings.warn(msg + (" A .rpx.json sidecar with the semantic metadata is written next to it." if sidecar else ""), stacklevel=2)

    from ..proxy.r_object import RObjectProxy
    if isinstance(obj, RObjectProxy):
        if ext not in (".rds", ".rdata", ".rda"):
            raise ConversionError("R proxies can only be saved as .rds/.RData (or .rpx bundle)", fix="use obj.save('model.rds')")
        return obj.save(path)

    if ext in (".rds", ".rdata", ".rda"):
        s = session or _session()
        return s.save_rds(obj, path)

    frame = _as_frame(obj)
    if ext in (".csv", ".tsv"):
        frame.to_csv(path, sep="\t" if ext == ".tsv" else ",", index=not isinstance(frame.index, pd.RangeIndex), **kw)
    elif ext == ".xlsx":
        frame.to_excel(path, index=not isinstance(frame.index, pd.RangeIndex), **kw)
    elif ext in (".parquet", ".pq"):
        if _is_geo(obj):
            obj.to_parquet(path, **kw)   # GeoParquet keeps CRS + geometry
        else:
            frame.to_parquet(path, **kw)
    elif ext in (".feather", ".arrow", ".ipc"):
        frame.reset_index(drop=isinstance(frame.index, pd.RangeIndex)).to_feather(path, **kw)
    elif ext == ".json":
        if isinstance(obj, (pd.DataFrame, pd.Series)):
            frame.to_json(path, orient="table", **kw)
        else:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(to_envelope(obj, Context()), f, ensure_ascii=False, default=_json_default)
    elif ext == ".npy":
        np.save(path, np.asarray(obj))
    elif ext == ".npz":
        np.savez(path, **(obj if isinstance(obj, dict) else {"array": np.asarray(obj)}))
    elif ext in (".pkl", ".pickle"):
        warnings.warn("pickle files execute arbitrary code when loaded: only load pickles you trust", stacklevel=2)
        with open(path, "wb") as f:
            pickle.dump(obj, f)
    elif ext == ".dta":
        _write_stat(obj, path, "dta")
    elif ext == ".sav":
        _write_stat(obj, path, "sav")
    elif ext == ".xpt":
        _write_stat(obj, path, "xpt")
    elif ext in (".nc", ".netcdf"):
        obj.to_netcdf(path, **kw)
    elif ext == ".zarr":
        obj.to_zarr(path, **kw)
    elif ext in (".gpkg", ".geojson", ".shp", ".fgb"):
        if not _is_geo(obj):
            raise ConversionError(f"{ext} needs a GeoDataFrame", fix="rp.spatial(df, ...) with geopandas installed")
        obj.to_file(path, driver={".gpkg": "GPKG", ".geojson": "GeoJSON", ".shp": "ESRI Shapefile", ".fgb": "FlatGeobuf"}[ext], **kw)
        if ext == ".shp":
            warnings.warn("Shapefile truncates field names to 10 characters and has no null/date-time precision", stacklevel=2)
    elif ext in (".tif", ".tiff"):
        _write_raster(obj, path)
    elif ext in (".graphml", ".gexf"):
        import networkx as nx
        g = obj.to_networkx() if hasattr(obj, "to_networkx") else obj
        (nx.write_graphml if ext == ".graphml" else nx.write_gexf)(g, path)
    elif ext in (".png", ".svg", ".pdf", ".html") and hasattr(obj, "save"):
        obj.save(path, **kw)
    else:
        raise ConversionError(f"unsupported format {ext!r}", fix="use .rpx (universal bundle), .parquet, .feather, .rds, ...")

    if sidecar and (lossy_note or rich) and ext not in (".rds", ".rdata", ".rda"):
        _write_sidecar(obj, path)
    return path


def _as_frame(obj: Any) -> Any:
    import pandas as pd
    if isinstance(obj, pd.DataFrame):
        return obj
    if isinstance(obj, pd.Series):
        return obj.to_frame()
    for attr in ("data", "frame"):
        v = getattr(obj, attr, None)
        if callable(v):
            v = v()
        if isinstance(v, pd.DataFrame):
            return v
    if hasattr(obj, "to_pandas"):
        return obj.to_pandas()
    if hasattr(obj, "to_frame"):
        return obj.to_frame()
    return pd.DataFrame(obj)


def _is_geo(obj: Any) -> bool:
    return type(obj).__module__.startswith("geopandas")


def _write_stat(obj: Any, path: str, fmt: str) -> None:
    from ..data.survey import LabelledFrame
    try:
        import pyreadstat
    except ImportError as e:
        raise ConversionError(f"writing .{fmt} needs pyreadstat", fix="pip install pyreadstat") from e
    if isinstance(obj, LabelledFrame):
        kw = {"variable_value_labels": obj.value_labels, "column_labels": [obj.variable_labels.get(c, "") for c in obj.data.columns]}
        if fmt == "sav":
            kw["missing_ranges"] = {c: [{"lo": v, "hi": v} for v in vals] for c, vals in obj.missing_values.items()} or None
        df = obj.data
    else:
        kw, df = {}, _as_frame(obj)
    {"dta": pyreadstat.write_dta, "sav": pyreadstat.write_sav, "xpt": pyreadstat.write_xport}[fmt](df, path, **{k: v for k, v in kw.items() if v is not None})


def _write_raster(obj: Any, path: str) -> None:
    from ..data.raster import Raster, RasterRef
    if isinstance(obj, RasterRef):
        shutil.copyfile(obj.path, path)
        return
    try:
        import rasterio
        from rasterio.transform import Affine
    except ImportError as e:
        raise ConversionError("writing GeoTIFF needs rasterio", fix="pip install rasterio") from e
    r: Raster = obj
    arr = r.array if r.array.ndim == 3 else r.array[None, ...]
    t = r.transform
    with rasterio.open(path, "w", driver="GTiff", height=arr.shape[1], width=arr.shape[2], count=arr.shape[0], dtype=arr.dtype,
                       crs=r.crs, transform=Affine.from_gdal(*t), nodata=r.nodata) as dst:
        dst.write(arr)


def _write_sidecar(obj: Any, path: str) -> None:
    env = to_envelope(obj, Context())
    meta = {k: v for k, v in env.items() if k not in ("columns", "values", "items", "data", "arrow")}
    meta["columns_semantic"] = [{"name": c["name"], "type": c["type"], "semantic": c.get("semantic")} for c in env.get("columns", [])] if "columns" in env else None
    with open(path + ".rpx.json", "w", encoding="utf-8") as f:
        json.dump({"rpx_sidecar": 1, "for": os.path.basename(path), "meta": meta}, f, ensure_ascii=False, default=_json_default, indent=1)


# --------------------------------------------------------------------------- bundle

def save_bundle(obj: Any, path: str, session: Any = None, native: bool = True) -> str:
    import platform
    import datetime as dt
    from ..proxy.r_object import RObjectProxy
    from .. import __version__
    if os.path.exists(path):
        shutil.rmtree(path)
    os.makedirs(os.path.join(path, "portable"))
    os.makedirs(os.path.join(path, "native"))
    ctx = Context(direction="py->r", target_runtime=Runtime.PYTHON, workdir=os.path.join(path, "portable"))
    if isinstance(obj, RObjectProxy):
        obj.save(os.path.join(path, "native", "object.rds"))
        env = {"rpx": 1, "kind": "native_r", "path": "native/object.rds", "class": obj.rclass, "package": obj.package}
        family = "r-native"
    else:
        env = to_envelope(obj, ctx)
        family = ctx.plan.family
        # relocate arrow parts into the bundle
        env = _relocate_arrow(env, path)
        if native:
            try:
                with open(os.path.join(path, "native", "object.pickle"), "wb") as f:
                    pickle.dump(obj, f)
            except Exception:
                pass
    with open(os.path.join(path, "portable", "envelope.json"), "w", encoding="utf-8") as f:
        json.dump(env, f, ensure_ascii=False, default=_json_default)
    manifest = {"rpx_bundle": 1, "version": __version__, "family": family, "kind": env.get("kind"),
                "created": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                "python": platform.python_version(), "platform": platform.platform(),
                "source_class": (env.get("meta") or {}).get("source_class"), "has_native": os.listdir(os.path.join(path, "native")) != []}
    with open(os.path.join(path, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1)
    with open(os.path.join(path, "semantic_metadata.json"), "w", encoding="utf-8") as f:
        json.dump({"plan": ctx.plan.render(), "fidelity": ctx.plan.fidelity.to_dict(), "history": [h.to_dict() for h in ctx.plan.history]}, f, indent=1, default=str)
    return path


def _relocate_arrow(env: Any, bundle: str) -> Any:
    if isinstance(env, dict):
        if env.get("arrow") and os.path.isabs(env["arrow"]) and os.path.exists(env["arrow"]):
            dest = os.path.join(bundle, "portable", os.path.basename(env["arrow"]))
            if os.path.abspath(env["arrow"]) != os.path.abspath(dest):
                shutil.move(env["arrow"], dest)
            env["arrow"] = "portable/" + os.path.basename(dest)
        return {k: _relocate_arrow(v, bundle) for k, v in env.items()}
    if isinstance(env, list):
        return [_relocate_arrow(v, bundle) for v in env]
    return env


def _absolutize_arrow(env: Any, bundle: str) -> Any:
    if isinstance(env, dict):
        if env.get("arrow") and not os.path.isabs(env["arrow"]):
            env["arrow"] = os.path.join(bundle, env["arrow"])
        return {k: _absolutize_arrow(v, bundle) for k, v in env.items()}
    if isinstance(env, list):
        return [_absolutize_arrow(v, bundle) for v in env]
    return env


def load_bundle(path: str, session: Any = None, prefer_native: bool = False) -> Any:
    with open(os.path.join(path, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    with open(os.path.join(path, "portable", "envelope.json"), encoding="utf-8") as f:
        env = json.load(f)
    if env.get("kind") == "native_r":
        s = session or _session()
        return s.load_rds(os.path.join(path, env["path"]), convert=False)
    if prefer_native and os.path.exists(os.path.join(path, "native", "object.pickle")):
        warnings.warn("loading the native pickle from the bundle: only do this for bundles you trust", stacklevel=2)
        with open(os.path.join(path, "native", "object.pickle"), "rb") as f:
            return pickle.load(f)
    env = _absolutize_arrow(env, path)
    obj = from_envelope(env, Context(direction="r->py", target_runtime=Runtime.PYTHON))
    try:
        obj.attrs.setdefault("rpython", {})["bundle"] = manifest
    except Exception:
        pass
    return obj


def bundle_info(path: str) -> dict[str, Any]:
    with open(os.path.join(path, "manifest.json"), encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------------------------------- load

def load(path: str, *, session: Any = None, **kw: Any) -> Any:
    import pandas as pd
    ext = os.path.splitext(path)[1].lower()
    if os.path.isdir(path) and os.path.exists(os.path.join(path, "manifest.json")):
        return load_bundle(path, session=session, **kw)
    if ext in (".rds", ".rdata", ".rda"):
        s = session or _session()
        if ext == ".rds":
            return s.load_rds(path, **kw)
        p = os.path.abspath(path).replace("\\", "/")
        return s.run(f"local({{ e <- new.env(); load('{p}', envir = e); as.list(e) }})")
    if ext in (".csv", ".tsv"):
        df = pd.read_csv(path, sep="\t" if ext == ".tsv" else ",", **kw)
    elif ext == ".xlsx":
        df = pd.read_excel(path, **kw)
    elif ext in (".parquet", ".pq"):
        df = _read_parquet(path, **kw)
    elif ext in (".feather", ".arrow", ".ipc"):
        df = pd.read_feather(path, **kw)
    elif ext == ".json":
        with open(path, encoding="utf-8") as f:
            head = f.read(64)
        if '"rpx"' in head:
            with open(path, encoding="utf-8") as f:
                return from_envelope(json.load(f), Context())
        df = pd.read_json(path, orient="table", **kw)
    elif ext == ".npy":
        import numpy as np
        return np.load(path, allow_pickle=False)
    elif ext == ".npz":
        import numpy as np
        return dict(np.load(path, allow_pickle=False))
    elif ext in (".pkl", ".pickle"):
        warnings.warn("loading a pickle executes arbitrary code: only load pickles you trust", stacklevel=2)
        with open(path, "rb") as f:
            return pickle.load(f)
    elif ext in (".dta", ".sav", ".xpt", ".sas7bdat", ".por"):
        return _read_stat(path, ext, **kw)
    elif ext in (".nc", ".netcdf", ".zarr"):
        import xarray as xr
        return xr.open_dataset(path, **kw) if ext != ".zarr" else xr.open_zarr(path, **kw)
    elif ext in (".gpkg", ".geojson", ".shp", ".fgb"):
        import geopandas as gpd
        return gpd.read_file(path, **kw)
    elif ext in (".tif", ".tiff", ".img", ".vrt"):
        from ..data.raster import RasterRef
        return RasterRef(path)
    elif ext in (".graphml", ".gexf"):
        import networkx as nx
        return (nx.read_graphml if ext == ".graphml" else nx.read_gexf)(path)
    else:
        raise ConversionError(f"unsupported format {ext!r}", fix="rp.load supports .rpx bundles, parquet, feather, csv, xlsx, json, rds, dta/sav, nc, gpkg, graphml, ...")
    return _apply_sidecar(df, path)


def _read_parquet(path: str, **kw: Any) -> Any:
    import pyarrow.parquet as pq
    md = pq.read_schema(path).metadata or {}
    if b"geo" in md:
        try:
            import geopandas as gpd
            return gpd.read_parquet(path, **kw)
        except Exception:
            pass
    import pandas as pd
    return pd.read_parquet(path, **kw)


def _read_stat(path: str, ext: str, **kw: Any) -> Any:
    try:
        import pyreadstat
    except ImportError as e:
        raise ConversionError(f"reading {ext} needs pyreadstat", fix="pip install pyreadstat") from e
    reader = {".dta": pyreadstat.read_dta, ".sav": pyreadstat.read_sav, ".xpt": pyreadstat.read_xport,
              ".sas7bdat": pyreadstat.read_sas7bdat, ".por": pyreadstat.read_por}[ext]
    df, meta = reader(path, user_missing=True, **kw) if ext in (".dta", ".sav") else reader(path, **kw)
    from ..data.survey import LabelledFrame
    lf = LabelledFrame.from_pyreadstat(df, meta)
    lf.source_format = {".dta": "stata", ".sav": "spss", ".por": "spss", ".xpt": "sas", ".sas7bdat": "sas"}[ext]
    return lf


def _apply_sidecar(df: Any, path: str) -> Any:
    side = path + ".rpx.json"
    if not os.path.exists(side):
        return df
    try:
        with open(side, encoding="utf-8") as f:
            meta = json.load(f)["meta"]
        import pandas as pd
        from ..data.tabular import _restore_dtype, _apply_semantic_from_arrow
        for c in meta.get("columns_semantic") or []:
            if c["name"] in df.columns:
                s = _apply_semantic_from_arrow(df[c["name"]], c["type"], c.get("semantic") or {})
                df[c["name"]] = _restore_dtype(s, c["type"], c.get("semantic") or {})
        idx = meta.get("index")
        if idx and idx.get("columns") and all(c in df.columns for c in idx["columns"]):
            df = df.set_index(idx["columns"] if len(idx["columns"]) > 1 else idx["columns"][0])
            if not idx.get("names") or idx["names"] == [None]:
                df.index.name = None
        sem = meta.get("semantics") or {}
        if sem:
            df.attrs.setdefault("rpython", {}).update(sem)
        if meta.get("attrs"):
            df.attrs.update(meta["attrs"])
        return df
    except Exception as e:
        warnings.warn(f"could not apply sidecar {side}: {e}", stacklevel=2)
        return df


def _session() -> Any:
    from ..runtime.r_session import default_session
    return default_session()
