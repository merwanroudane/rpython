"""Sparse matrices (section 7): first-class, never densified by default.

Envelope ``kind: "sparse"``::

    {"kind": "sparse", "format": "csc"|"csr"|"coo", "shape": [m, n],
     "dtype": <rtype>, "indptr": [...], "indices": [...],     # csc / csr
     "row": [...], "col": [...],                              # coo
     "data": [...], "dimnames": [...]|null,
     "symmetric": bool, "triangular": null|"U"|"L", "meta": {...}}

Indices are **0-based** on the wire; the R companion maps them onto
``Matrix::dgCMatrix`` / ``dgRMatrix`` / ``dgTMatrix`` (and ``lgCMatrix``
for logical, ``dsCMatrix`` when symmetric) without changing format.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from .context import Context
from .primitives import encode_values, decode_values, numpy_rtype
from .registry import Adapter, REGISTRY
from .semantic import Confidence, ConversionPath, Detection, Fidelity


def _scipy():
    try:
        import scipy.sparse as sp
        return sp
    except Exception:
        return None


def _is_scipy_sparse(obj: Any) -> bool:
    sp = _scipy()
    return sp is not None and sp.issparse(obj)


def _is_torch_sparse(obj: Any) -> bool:
    return type(obj).__module__.startswith("torch") and getattr(obj, "is_sparse", False)


def _is_pandas_sparse(obj: Any) -> bool:
    try:
        import pandas as pd
        if isinstance(obj, pd.DataFrame):
            return any(isinstance(dt, pd.SparseDtype) for dt in obj.dtypes)
        return isinstance(getattr(obj, "dtype", None), pd.SparseDtype)
    except Exception:
        return False


def estimate_dense_bytes(shape: tuple[int, ...], itemsize: int = 8) -> int:
    return int(np.prod(shape)) * itemsize


class SparseAdapter(Adapter):
    family = "sparse"
    kinds = ("sparse",)
    tier = ConversionPath.STANDARD
    priority = 20
    requires = ("scipy",)
    r_requires = ("Matrix",)

    def detect(self, obj: Any) -> Detection | None:
        if _is_scipy_sparse(obj):
            return Detection("sparse matrix", Confidence.CONFIRMED, f"scipy.sparse {obj.format} {obj.shape}")
        if _is_torch_sparse(obj):
            return Detection("sparse matrix", Confidence.CONFIRMED, "torch sparse tensor")
        if _is_pandas_sparse(obj):
            return Detection("sparse matrix", Confidence.CONFIRMED, "pandas SparseDtype")
        return None

    def encode(self, obj: Any, ctx: Context) -> dict[str, Any]:
        sp = _scipy()
        meta: dict[str, Any] = {"source_class": f"{type(obj).__module__}.{type(obj).__qualname__}"}
        if _is_torch_sparse(obj):
            t = obj.coalesce()
            idx = t.indices().cpu().numpy()
            vals = t.values().cpu().numpy()
            obj = sp.coo_matrix((vals, (idx[0], idx[1])), shape=tuple(t.shape))
            meta["source_format"] = "torch-coo"
        elif _is_pandas_sparse(obj):
            import pandas as pd
            if isinstance(obj, pd.DataFrame):
                meta["columns"] = [str(c) for c in obj.columns]
                obj = obj.sparse.to_coo()
            else:
                obj = sp.coo_matrix(obj.sparse.to_coo()) if hasattr(obj.sparse, "to_coo") else sp.coo_matrix(obj.to_numpy())
            meta["source_format"] = "pandas-sparse"
        fmt = obj.format
        meta["source_format"] = meta.get("source_format", fmt)
        if fmt not in ("csc", "csr", "coo"):
            ctx.plan.note(f"sparse format {fmt} has no Matrix-package equivalent; transported as CSC")
            ctx.plan.fidelity.set("storage", Fidelity.CHANGED, f"{fmt} -> csc")
            obj = obj.tocsc()
            fmt = "csc"
        else:
            ctx.plan.fidelity.set("storage", Fidelity.LOSSLESS)
        if fmt in ("csc", "csr"):
            if not obj.has_sorted_indices:
                obj = obj.copy()
            obj.sort_indices()   # before encoding data: values and indices must align
        rtype = numpy_rtype(obj.data, ctx) if obj.data.size else "double"
        if rtype not in ("double", "integer", "logical", "int64", "complex"):
            raise TypeError(f"unsupported sparse dtype {obj.data.dtype}")
        env: dict[str, Any] = {"rpx": 1, "kind": "sparse", "format": fmt, "shape": list(obj.shape),
                               "dtype": rtype, "data": encode_values(obj.data, rtype, ctx),
                               "dimnames": None, "symmetric": False, "triangular": None, "meta": meta}
        if fmt in ("csc", "csr"):
            env["indptr"] = obj.indptr.astype(np.int64).tolist()
            env["indices"] = obj.indices.astype(np.int64).tolist()
        else:
            env["row"] = obj.row.astype(np.int64).tolist()
            env["col"] = obj.col.astype(np.int64).tolist()
        meta["nnz"] = int(obj.nnz)
        ctx.record("sparse", ConversionPath.STANDARD, "json",
                   f"{fmt} {obj.shape} nnz={obj.nnz:,} -> Matrix::{_r_class(fmt, rtype)}")
        ctx.plan.shape = tuple(obj.shape)
        ctx.plan.extra["Sparse"] = f"{fmt} kept sparse (dense would be {estimate_dense_bytes(obj.shape):,} bytes)"
        ctx.plan.fidelity.set("values", Fidelity.LOSSLESS)
        ctx.plan.fidelity.set("shape", Fidelity.LOSSLESS)
        ctx.plan.fidelity.set("index", Fidelity.LOSSLESS)
        return env

    def decode(self, env: dict[str, Any], ctx: Context) -> Any:
        sp = _scipy()
        fmt = env["format"]
        shape = tuple(env["shape"])
        rtype = env.get("dtype", "double")
        data = decode_values(env.get("data") or [], rtype, ctx=ctx)
        if not isinstance(data, np.ndarray):
            data = np.asarray(data.to_numpy(dtype=float, na_value=np.nan))
        if fmt == "csc":
            mat = sp.csc_matrix((data, np.asarray(env["indices"]), np.asarray(env["indptr"])), shape=shape)
        elif fmt == "csr":
            mat = sp.csr_matrix((data, np.asarray(env["indices"]), np.asarray(env["indptr"])), shape=shape)
        else:
            mat = sp.coo_matrix((data, (np.asarray(env["row"]), np.asarray(env["col"]))), shape=shape)
        meta = env.get("meta") or {}
        if env.get("symmetric"):
            # R stores only one triangle for dsCMatrix; rebuild the full matrix.
            upper = mat.tocsr()
            mat = (upper + upper.T - sp.diags(upper.diagonal())).asformat(fmt)
            ctx.plan.note("symmetric sparse matrix expanded from stored triangle (scipy has no symmetric flag)")
            ctx.plan.fidelity.set("storage", Fidelity.CHANGED, "symmetric storage expanded")
        if meta.get("source_format") == "torch-coo":
            try:
                import torch
                coo = mat.tocoo()
                idx = torch.tensor(np.vstack([coo.row, coo.col]), dtype=torch.int64)
                return torch.sparse_coo_tensor(idx, torch.tensor(coo.data), size=shape).coalesce()
            except Exception:
                pass
        if env.get("dimnames") and any(d for d in env["dimnames"]):
            mat = SparseWithNames(mat, env["dimnames"])
        ctx.record("sparse", ConversionPath.STANDARD, "json", f"Matrix {fmt} -> scipy {fmt}")
        ctx.plan.fidelity.set("values", Fidelity.LOSSLESS)
        ctx.plan.fidelity.set("shape", Fidelity.LOSSLESS)
        return mat


class SparseWithNames:
    """Thin wrapper keeping R dimnames next to a scipy matrix."""

    def __init__(self, matrix: Any, dimnames: list[list[str] | None]):
        self.matrix = matrix
        self.dimnames = dimnames

    def __getattr__(self, item: str) -> Any:
        return getattr(self.matrix, item)

    def __repr__(self) -> str:
        return f"<SparseWithNames {self.matrix!r} rows={len(self.dimnames[0] or [])} cols={len(self.dimnames[1] or [])}>"


def _r_class(fmt: str, rtype: str) -> str:
    prefix = {"double": "d", "integer": "d", "int64": "d", "logical": "l", "complex": "z"}[rtype]
    return prefix + {"csc": "gCMatrix", "csr": "gRMatrix", "coo": "gTMatrix"}[fmt]


def to_dense(mat: Any, ctx: Context | None = None, allow: bool = False) -> np.ndarray:
    """Explicit densification with a memory estimate and guard (section 7)."""
    ctx = ctx or Context()
    if allow:
        ctx.allow_materialize = True
    est = estimate_dense_bytes(mat.shape, getattr(mat, "dtype", np.dtype(float)).itemsize)
    ctx.memory_guard(f"sparse {mat.shape}", est, "keep the matrix sparse")
    return mat.toarray()


REGISTRY.register(SparseAdapter(), tested=True,
                  limitations=("DIA/BSR/LIL/DOK formats are transported as CSC (reported)",
                               "symmetric/triangular flags come from R only; scipy has no such flag"))
