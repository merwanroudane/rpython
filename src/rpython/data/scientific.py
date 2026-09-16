"""Scientific labelled multidimensional data (section 35): xarray
``DataArray`` / ``Dataset``, NetCDF/HDF-backed and Dask-chunked objects.

Envelopes::

    {"kind": "labeled_array", "name": ..., "dims": [...],
     "coords": {name: {"dims": [...], "values": <vector env>, "attrs": {...}}},
     "attrs": {...}, "data": <array env>, "encoding": {...}, "meta": {...}}

    {"kind": "labeled_dataset", "variables": {name: <labeled_array>},
     "coords": {...}, "attrs": {...}, "meta": {...}}

    {"kind": "netcdf_ref", "path": ..., "engine": ..., "variables": [...],
     "dims": {...}, "lazy": true}          # shared file, nothing loaded

R: an array with ``dimnames`` (1-D coordinates) plus ``rpython.coords`` /
``rpython.attrs`` attributes; ``stars`` objects when *stars* is installed;
``ncdf4``/``stars`` proxy for NetCDF references.  Units, calendar and
attributes are preserved verbatim.
"""
from __future__ import annotations

import os
from typing import Any

import numpy as np

from .context import Context
from .registry import Adapter, REGISTRY
from .semantic import Confidence, ConversionPath, Detection, Fidelity


def _xr():
    try:
        import xarray as xr
        return xr
    except Exception:
        return None


def _is_dataarray(obj: Any) -> bool:
    xr = _xr()
    return xr is not None and isinstance(obj, xr.DataArray)


def _is_dataset(obj: Any) -> bool:
    xr = _xr()
    return xr is not None and isinstance(obj, xr.Dataset)


def _jsonable(d: dict[str, Any]) -> dict[str, Any]:
    import json
    out: dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, np.generic):
            v = v.item()
        elif isinstance(v, np.ndarray):
            v = v.tolist()
        try:
            json.dumps(v)
            out[str(k)] = v
        except Exception:
            out[str(k)] = str(v)
    return out


class NetCDFRef:
    """Lazy reference to a NetCDF / HDF5 / Zarr store shared between runtimes."""

    def __init__(self, path: str, engine: str | None = None, metadata: dict[str, Any] | None = None):
        self.path, self.engine, self.metadata = path, engine, metadata or {}

    def open(self, **kw: Any) -> Any:
        xr = _xr()
        if xr is None:
            raise ImportError("xarray is required: pip install 'rpython[scientific]'")
        return xr.open_dataset(self.path, engine=self.engine, **kw)

    def describe_structure(self) -> str:
        lines = ["Type: NetCDF/HDF (lazy file reference)", f"Path: {self.path}", f"Engine: {self.engine or 'auto'}"]
        for k, v in self.metadata.items():
            lines.append(f"{k}: {v}")
        return "\n".join(lines)

    def __repr__(self) -> str:
        return f"<NetCDFRef {self.path}>"


class ScientificAdapter(Adapter):
    family = "scientific"
    kinds = ("labeled_array", "labeled_dataset", "netcdf_ref")
    tier = ConversionPath.ADAPTER
    priority = 15
    requires = ("xarray",)

    def detect(self, obj: Any) -> Detection | None:
        if _is_dataarray(obj):
            return Detection("labelled array (xarray.DataArray)", Confidence.CONFIRMED, f"dims={list(obj.dims)}")
        if _is_dataset(obj):
            return Detection("labelled dataset (xarray.Dataset)", Confidence.CONFIRMED, f"{len(obj.data_vars)} variables")
        if isinstance(obj, NetCDFRef):
            return Detection("NetCDF reference", Confidence.CONFIRMED, obj.path)
        return None

    # ------------------------------------------------------------------ encode
    def encode(self, obj: Any, ctx: Context) -> dict[str, Any]:
        if isinstance(obj, NetCDFRef):
            return self._encode_ref(obj, ctx)
        if _is_dataset(obj):
            src = obj.encoding.get("source")
            if src and _is_lazy(obj) and os.path.exists(str(src)):
                ctx.plan.note("dataset is file-backed and lazy: shared as a NetCDF reference instead of loading it")
                return self._encode_ref(NetCDFRef(str(src), obj.encoding.get("engine") or None,
                                                  {"variables": list(obj.data_vars), "dims": dict(obj.sizes)}), ctx)
            est = int(sum(v.nbytes for v in obj.data_vars.values()))
            ctx.memory_guard("xarray.Dataset", est, "share the NetCDF file (rp.netcdf(path)) or subset first")
            variables = {name: self._encode_array(da, ctx, nested=True) for name, da in obj.data_vars.items()}
            coords = {name: self._encode_coord(c, ctx) for name, c in obj.coords.items()}
            env = {"rpx": 1, "kind": "labeled_dataset", "variables": variables, "coords": coords,
                   "attrs": _jsonable(obj.attrs), "dims": {k: int(v) for k, v in obj.sizes.items()},
                   "meta": {"source_class": "xarray.Dataset"}}
            ctx.record("scientific", ConversionPath.ADAPTER, ctx.plan.backend,
                       f"Dataset with {len(variables)} variables, dims {dict(obj.sizes)} -> R list of labelled arrays / stars")
            ctx.plan.fidelity.set("values", Fidelity.LOSSLESS)
            ctx.plan.fidelity.set("metadata", Fidelity.LOSSLESS, "attrs, units, calendar kept verbatim")
            ctx.plan.fidelity.set("names", Fidelity.LOSSLESS, "dims + coords")
            return env
        return self._encode_array(obj, ctx)

    def _encode_ref(self, ref: NetCDFRef, ctx: Context) -> dict[str, Any]:
        env = {"rpx": 1, "kind": "netcdf_ref", "path": os.path.abspath(ref.path), "engine": ref.engine,
               "metadata": ref.metadata, "lazy": True, "meta": {"source_class": "rpython.NetCDFRef"}}
        ctx.record("scientific", ConversionPath.LAZY, "shared-file", f"{ref.path} opened lazily on target (stars/ncdf4)")
        ctx.plan.copies = 0
        ctx.plan.fidelity.set("laziness", Fidelity.LOSSLESS)
        return env

    def _encode_coord(self, c: Any, ctx: Context) -> dict[str, Any]:
        from .convert import to_envelope
        vals = c.values
        return {"dims": list(c.dims), "values": to_envelope(vals if vals.ndim > 1 else vals.tolist() if vals.dtype.kind in "OU" else vals, ctx),
                "attrs": _jsonable(c.attrs), "dtype": str(vals.dtype)}

    def _encode_array(self, da: Any, ctx: Context, nested: bool = False) -> dict[str, Any]:
        from .arrays import ArrayAdapter
        if _is_lazy(da):
            est = int(da.nbytes)
            ctx.memory_guard(f"lazy DataArray {da.name or ''}", est, "share the NetCDF file (rp.netcdf(path)) or subset first")
            ctx.plan.fidelity.set("laziness", Fidelity.CHANGED, "chunked data computed before transfer")
        data_env = ArrayAdapter().encode(np.asarray(da.values), ctx)
        dimnames: list[list[str] | None] = []
        for d in da.dims:
            if d in da.coords and da.coords[d].ndim == 1:
                dimnames.append([str(v) for v in da.coords[d].values])
            else:
                dimnames.append(None)
        data_env["dimnames"] = dimnames
        env = {"rpx": 1, "kind": "labeled_array", "name": da.name, "dims": list(da.dims),
               "coords": {name: self._encode_coord(c, ctx) for name, c in da.coords.items()},
               "attrs": _jsonable(da.attrs), "data": data_env, "encoding": _jsonable(getattr(da, "encoding", {}) or {}),
               "chunks": [list(c) for c in da.chunks] if getattr(da, "chunks", None) else None,
               "meta": {"source_class": "xarray.DataArray"}}
        if not nested:
            ctx.record("scientific", ConversionPath.ADAPTER, ctx.plan.backend,
                       f"DataArray {da.name or ''} dims={list(da.dims)} shape={tuple(da.shape)} -> R array with dimnames + coords")
            ctx.plan.fidelity.set("values", Fidelity.LOSSLESS)
            ctx.plan.fidelity.set("names", Fidelity.LOSSLESS, "dims + coordinates")
            ctx.plan.fidelity.set("metadata", Fidelity.LOSSLESS, "attrs / units / calendar verbatim")
        return env

    # ------------------------------------------------------------------ decode
    def decode(self, env: dict[str, Any], ctx: Context) -> Any:
        xr = _xr()
        k = env["kind"]
        if k == "netcdf_ref":
            ctx.record("scientific", ConversionPath.LAZY, "shared-file", "NetCDF reference (lazy)")
            return NetCDFRef(env["path"], env.get("engine"), env.get("metadata") or {})
        if k == "labeled_dataset":
            variables = {n: self._decode_array(v, ctx) for n, v in (env.get("variables") or {}).items()}
            coords = self._decode_coords(env.get("coords") or {}, ctx)
            ds = xr.Dataset(variables, coords=coords, attrs=env.get("attrs") or {})
            ctx.record("scientific", ConversionPath.ADAPTER, ctx.plan.backend, "R labelled arrays -> xarray.Dataset")
            return ds
        da = self._decode_array(env, ctx)
        ctx.record("scientific", ConversionPath.ADAPTER, ctx.plan.backend, "R array + dimnames -> xarray.DataArray")
        ctx.plan.fidelity.set("values", Fidelity.LOSSLESS)
        return da

    def _decode_coords(self, coords: dict[str, Any], ctx: Context) -> dict[str, Any]:
        from .convert import from_envelope
        out: dict[str, Any] = {}
        for name, c in coords.items():
            vals = from_envelope(c["values"], ctx)
            vals = np.asarray(vals.tolist() if hasattr(vals, "tolist") and not isinstance(vals, np.ndarray) else vals)
            dt = c.get("dtype", "")
            if dt.startswith("datetime64") and vals.dtype.kind != "M":
                import pandas as pd
                vals = pd.DatetimeIndex(vals).to_numpy()
            elif dt.startswith(("int", "uint")) and vals.dtype.kind == "f":
                vals = vals.astype(dt)
            out[name] = (c["dims"], vals, c.get("attrs") or {})
        return out

    def _decode_array(self, env: dict[str, Any], ctx: Context) -> Any:
        xr = _xr()
        from .arrays import ArrayAdapter
        data = np.asarray(ArrayAdapter().decode({**env["data"], "dimnames": None}, ctx))
        dims = env.get("dims") or [f"dim_{i}" for i in range(data.ndim)]
        coords = self._decode_coords(env.get("coords") or {}, ctx)
        if not coords:
            dimnames = env["data"].get("dimnames") or []
            for d, names in zip(dims, dimnames):
                if names:
                    coords[d] = (d, np.asarray(names))
        return xr.DataArray(data, dims=dims, coords=coords, name=env.get("name"), attrs=env.get("attrs") or {})


def _is_lazy(obj: Any) -> bool:
    try:
        if hasattr(obj, "chunks") and obj.chunks:
            return True
        if hasattr(obj, "data_vars"):
            return any(getattr(v, "chunks", None) for v in obj.data_vars.values())
    except Exception:
        pass
    return False


def netcdf(path: str, engine: str | None = None) -> NetCDFRef:
    return NetCDFRef(str(path), engine)


REGISTRY.register(ScientificAdapter(), tested=True,
                  limitations=("Multi-dimensional (non 1-D) coordinates are carried in rpython.coords, not as dimnames",))
