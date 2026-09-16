"""Matrices, N-d arrays and tensors (section 6).

Envelope ``kind: "array"``::

    {"kind": "array", "dtype": <rtype>, "shape": [...], "order": "C"|"F",
     "values": [...flat in `order`...] | null, "arrow": <path> | null,
     "dimnames": [[...]|null, ...] | null, "mask": [...] | null, "meta": {...}}

Memory layout is transported explicitly: values are shipped in the
source array's own order and the receiver reshapes accordingly, so no
axis is ever silently transposed.  ``[i, j]`` in NumPy refers to the same
element as ``[i+1, j+1]`` in R.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from .context import Context
from .primitives import numpy_rtype, encode_values, decode_values
from .registry import Adapter, REGISTRY
from .semantic import Confidence, ConversionPath, Detection, Fidelity

ARROW_ARRAY_THRESHOLD = 50_000  # elements


def _is_torch(obj: Any) -> bool:
    return type(obj).__module__.startswith("torch") and hasattr(obj, "detach")


def _is_jax(obj: Any) -> bool:
    return type(obj).__module__.startswith("jax")


def _is_cupy(obj: Any) -> bool:
    return type(obj).__module__.startswith("cupy")


def _is_dask_array(obj: Any) -> bool:
    return type(obj).__module__.startswith("dask.array")


class ArrayAdapter(Adapter):
    family = "array"
    kinds = ("array",)
    tier = ConversionPath.STANDARD
    priority = 25

    def detect(self, obj: Any) -> Detection | None:
        if isinstance(obj, np.ma.MaskedArray):
            return Detection("array", Confidence.CONFIRMED, "numpy masked array")
        if isinstance(obj, np.ndarray):
            if obj.dtype.kind == "V" or obj.dtype.names:
                return None  # structured arrays are tables
            return Detection("array", Confidence.CONFIRMED, f"numpy ndarray {obj.dtype} {obj.shape}")
        if isinstance(obj, np.matrix):
            return Detection("array", Confidence.CONFIRMED, "numpy matrix (compat)")
        if _is_torch(obj):
            return Detection("array", Confidence.CONFIRMED, "torch.Tensor")
        if _is_jax(obj) or _is_cupy(obj) or _is_dask_array(obj):
            return Detection("array", Confidence.CONFIRMED, type(obj).__module__)
        return None

    # ------------------------------------------------------------------ encode
    def encode(self, obj: Any, ctx: Context) -> dict[str, Any]:
        meta: dict[str, Any] = {"source_class": f"{type(obj).__module__}.{type(obj).__qualname__}"}
        mask: list[bool] | None = None
        arr = obj
        if _is_torch(obj):
            meta["device"] = str(obj.device)
            meta["requires_grad"] = bool(obj.requires_grad)
            meta["torch_dtype"] = str(obj.dtype)
            if obj.is_sparse:
                from .sparse import SparseAdapter
                return SparseAdapter().encode(obj.to_sparse_coo().coalesce(), ctx)
            if obj.device.type != "cpu":
                ctx.warn(f"tensor moved from {obj.device} to CPU for transfer")
            arr = obj.detach().cpu().numpy()
        elif _is_jax(obj) or _is_cupy(obj):
            arr = np.asarray(obj.__array__() if hasattr(obj, "__array__") else obj.get())
            meta["device"] = getattr(getattr(obj, "device", None), "__str__", lambda: "unknown")()
        elif _is_dask_array(obj):
            est = int(np.prod(obj.shape)) * obj.dtype.itemsize
            ctx.memory_guard("dask array", est, "compute a slice, or keep the array lazy behind a proxy")
            ctx.record("array", ConversionPath.LAZY, "dask.compute", "lazy array materialised (explicit)")
            arr = np.asarray(obj.compute())
            meta["chunks"] = [list(c) for c in obj.chunks]
        masked_src = None
        if isinstance(arr, np.ma.MaskedArray):
            masked_src = arr
            fill = arr.filled(np.nan if arr.dtype.kind == "f" else 0)
            arr = np.asarray(fill)
            meta["masked"] = True
        if isinstance(arr, np.matrix):
            arr = np.asarray(arr)
        arr = np.asarray(arr)
        order = "F" if (arr.flags.f_contiguous and not arr.flags.c_contiguous) else "C"
        rtype = numpy_rtype(arr, ctx)
        meta["np_dtype"] = str(arr.dtype)
        if arr.dtype.kind in "iu" and arr.dtype.itemsize < 4:
            ctx.plan.note(f"{arr.dtype} widened to R integer (32-bit)")
        if arr.dtype == np.float32:
            ctx.plan.note("float32 stored as R double (float64); dtype restored on round trip")
        if arr.dtype.kind == "f" and arr.dtype.itemsize > 8:
            ctx.lossy("long double array", "R double is 64-bit")
        shape = list(arr.shape)
        flat = arr.ravel(order=order)
        if masked_src is not None:
            # masked -> NA in R (same memory order as the values)
            mask = np.ma.getmaskarray(masked_src).ravel(order=order).tolist()
        env: dict[str, Any] = {"rpx": 1, "kind": "array", "dtype": rtype, "shape": shape, "order": order,
                               "dimnames": None, "mask": mask, "meta": meta}
        if flat.size >= ARROW_ARRAY_THRESHOLD and ctx.use_arrow(flat.size) and rtype in ("double", "integer", "logical", "int64"):
            from .arrow_io import write_flat_arrow
            env["values"] = None
            env["arrow"] = write_flat_arrow(flat, ctx, mask=mask)
            ctx.record("array", ConversionPath.STANDARD, "arrow-ipc", f"{flat.size:,} elements via Feather")
        else:
            vals = encode_values(flat, rtype, ctx)
            if mask is not None:
                vals = ["NA" if rtype == "double" else None if m else v for v, m in zip(vals, mask)]
            env["values"] = vals
            ctx.record("array", ConversionPath.NATIVE, "json", f"{flat.size:,} elements inline")
        ctx.plan.shape = tuple(shape)
        ctx.plan.estimated_bytes = max(ctx.plan.estimated_bytes, int(arr.nbytes))
        ctx.plan.extra["Memory order"] = f"{order} order shipped; R reshapes explicitly (no silent transpose)"
        ctx.plan.fidelity.set("values", Fidelity.LOSSLESS)
        ctx.plan.fidelity.set("shape", Fidelity.LOSSLESS)
        ctx.plan.fidelity.set("types", Fidelity.LOSSLESS if arr.dtype.kind in "fbU" and arr.dtype != np.float32
                              else Fidelity.CHANGED, "" if arr.dtype.kind in "fbU" and arr.dtype != np.float32
                              else f"{arr.dtype} -> R {rtype}; original dtype kept in metadata")
        return env

    # ------------------------------------------------------------------ decode
    def decode(self, env: dict[str, Any], ctx: Context) -> Any:
        meta = env.get("meta") or {}
        shape = tuple(env.get("shape") or [])
        order = env.get("order", "F")
        rtype = env["dtype"]
        if env.get("arrow"):
            from .arrow_io import read_flat_arrow
            flat = read_flat_arrow(env["arrow"])
        else:
            flat = decode_values(env.get("values") or [], rtype, meta.get("tz"), ctx)
        mask = env.get("mask")
        # pandas extension arrays (NA present) -> numpy with nan / masked
        if not isinstance(flat, np.ndarray):
            try:
                import pandas as pd
                if isinstance(flat, pd.api.extensions.ExtensionArray):
                    na = np.asarray(flat.isna())
                    if mask is None and na.any():
                        mask = na.tolist()
                    flat = np.asarray(flat.to_numpy(dtype=float if rtype in ("double", "integer", "int64")
                                                    else object, na_value=np.nan if rtype in ("double", "integer", "int64") else None))
                else:
                    flat = np.asarray(flat)
            except Exception:
                flat = np.asarray(flat)
        arr = np.asarray(flat).reshape(shape, order=order) if shape else np.asarray(flat)
        np_dtype = meta.get("np_dtype")
        if np_dtype:
            try:
                target = np.dtype(np_dtype)
                if target.kind in "iub" and arr.dtype.kind == "f" and np.isnan(arr).any():
                    if mask is not None and any(mask):
                        arr = np.nan_to_num(arr).astype(target)   # values under the mask are irrelevant
                else:
                    arr = arr.astype(target, copy=False)
            except Exception:
                pass
        if mask is not None and any(mask):
            m = np.asarray(mask, dtype=bool).reshape(shape, order=order) if shape else np.asarray(mask, dtype=bool)
            arr = np.ma.MaskedArray(arr, mask=m)
        dimnames = env.get("dimnames")
        if dimnames and any(d for d in dimnames):
            ctx.plan.note("R dimnames preserved in result attribute `.rpython_dimnames` (xarray gives them axes)")
            arr = LabeledArray(arr, dimnames)
        src = meta.get("source_class", "")
        if src.startswith("torch"):
            try:
                import torch
                t = torch.from_numpy(np.ascontiguousarray(np.asarray(arr)))
                if meta.get("requires_grad"):
                    t.requires_grad_(True)
                return t
            except Exception:
                pass
        ctx.record("array", ConversionPath.NATIVE, "json" if not env.get("arrow") else "arrow-ipc",
                   f"R {rtype} array {shape} -> numpy {arr.dtype}")
        ctx.plan.shape = shape
        ctx.plan.fidelity.set("values", Fidelity.LOSSLESS)
        ctx.plan.fidelity.set("shape", Fidelity.LOSSLESS)
        return arr


class LabeledArray(np.ndarray):
    """ndarray subclass carrying R ``dimnames`` (per-axis labels)."""

    def __new__(cls, arr: np.ndarray, dimnames: list[list[str] | None]):
        obj = np.asarray(arr).view(cls)
        obj.dimnames = dimnames
        return obj

    def __array_finalize__(self, obj: Any) -> None:
        self.dimnames = getattr(obj, "dimnames", None)

    def to_xarray(self) -> Any:
        import xarray as xr
        coords = {f"dim_{i}": d for i, d in enumerate(self.dimnames or []) if d}
        dims = [f"dim_{i}" for i in range(self.ndim)]
        return xr.DataArray(np.asarray(self), dims=dims, coords=coords)


def encode_dimnames(names: Any, ndim: int) -> list[list[str] | None] | None:
    if names is None:
        return None
    out = []
    for i in range(ndim):
        d = names[i] if i < len(names) else None
        out.append(None if d is None else [str(x) for x in d])
    return out


REGISTRY.register(ArrayAdapter(), tested=True,
                  limitations=("float32 / int8 / int16 widen to R double / integer; dtype restored on round trip",
                               "GPU tensors are copied to CPU (reported, never silent)"))
