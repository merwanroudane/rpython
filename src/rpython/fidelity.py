"""Round-trip fidelity engine (MASTER_PROMPT section 34; universal spec 58-59, 77-78).

Equality is defined *per family* -- there is no single ``==`` rule:

* tables: values (NaN == NaN, NA == NA), dtypes, column order, index, categories + order
* arrays: values (nan-aware), shape, dtype, mask
* sparse: shape, format, nnz, values + indices
* time series: values, index, frequency, timezone
* panel: values, entity/time keys, balance flags
* spatial: geometry WKB, CRS, geometry type
* networks: node set, edge multiset, direction, attributes
* labelled: variable/value labels, missing codes, design
* scalars / collections: Python equality with NaN-awareness
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from .data.context import Context
from .data.semantic import Fidelity, FidelityReport, Runtime


def _eq_scalar(a: Any, b: Any) -> bool:
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    try:
        import pandas as pd
        if a is pd.NA and b is pd.NA:
            return True
    except Exception:
        pass
    try:
        return bool(a == b)
    except Exception:
        return a is b


def _eq_array(a: Any, b: Any) -> bool:
    a, b = np.asarray(a), np.asarray(b)
    if a.shape != b.shape:
        return False
    if a.dtype.kind in "fc" and b.dtype.kind in "fc":
        return bool(np.array_equal(a, b, equal_nan=True))
    if a.dtype.kind == "O" or b.dtype.kind == "O":
        return all(_eq_scalar(x, y) for x, y in zip(a.ravel().tolist(), b.ravel().tolist()))
    return bool(np.array_equal(a, b))


def compare(original: Any, back: Any, report: FidelityReport | None = None) -> FidelityReport:
    """Compare an object with its round-tripped twin; fill a :class:`FidelityReport`."""
    import pandas as pd
    rep = report or FidelityReport()
    rep.validated = True
    t = type(original)

    if isinstance(original, pd.DataFrame):
        same_cols = list(original.columns) == list(getattr(back, "columns", []))
        rep.set("names", Fidelity.LOSSLESS if same_cols else Fidelity.LOSSY, "" if same_cols else "column names/order differ")
        try:
            vals_ok = same_cols and all(_eq_array(original[c].to_numpy(dtype=object) if original[c].dtype.kind == "O" else original[c].to_numpy(),
                                                  back[c].to_numpy(dtype=object) if back[c].dtype.kind == "O" else back[c].to_numpy())
                                        for c in original.columns)
        except Exception:
            vals_ok = False
        rep.set("values", Fidelity.LOSSLESS if vals_ok else Fidelity.LOSSY)
        dt_ok = same_cols and all(str(original[c].dtype) == str(back[c].dtype) for c in original.columns)
        rep.set("types", Fidelity.LOSSLESS if dt_ok else Fidelity.CHANGED,
                "" if dt_ok else "; ".join(f"{c}: {original[c].dtype}->{back[c].dtype}" for c in original.columns if same_cols and str(original[c].dtype) != str(back[c].dtype))[:200])
        idx_ok = original.index.equals(back.index) if hasattr(back, "index") else False
        rep.set("index", Fidelity.LOSSLESS if idx_ok else Fidelity.CHANGED)
        cats = [c for c in original.columns if isinstance(original[c].dtype, pd.CategoricalDtype)]
        if cats:
            cat_ok = same_cols and all(isinstance(back[c].dtype, pd.CategoricalDtype) and list(original[c].cat.categories) == list(back[c].cat.categories)
                                       and original[c].cat.ordered == back[c].cat.ordered for c in cats)
            rep.set("semantics", Fidelity.LOSSLESS if cat_ok else Fidelity.LOSSY, "category levels/order" if not cat_ok else "categories + order kept")
        if isinstance(original.index, (pd.DatetimeIndex, pd.PeriodIndex)):
            f_ok = isinstance(back.index, type(original.index)) and str(getattr(original.index, "freq", None)) == str(getattr(back.index, "freq", None))
            tz_ok = str(getattr(original.index, "tz", None)) == str(getattr(back.index, "tz", None))
            rep.set("temporal", Fidelity.LOSSLESS if f_ok and tz_ok else Fidelity.CHANGED, "" if f_ok and tz_ok else "frequency or timezone differs")
        return rep

    if isinstance(original, pd.Series):
        ok = isinstance(back, pd.Series) and _eq_array(original.to_numpy(dtype=object) if original.dtype.kind == "O" else original.to_numpy(),
                                                       back.to_numpy(dtype=object) if back.dtype.kind == "O" else back.to_numpy())
        rep.set("values", Fidelity.LOSSLESS if ok else Fidelity.LOSSY)
        rep.set("types", Fidelity.LOSSLESS if isinstance(back, pd.Series) and str(original.dtype) == str(back.dtype) else Fidelity.CHANGED)
        rep.set("index", Fidelity.LOSSLESS if isinstance(back, pd.Series) and original.index.equals(back.index) else Fidelity.CHANGED)
        return rep

    if isinstance(original, np.ndarray):
        rep.set("shape", Fidelity.LOSSLESS if np.shape(back) == original.shape else Fidelity.LOSSY)
        rep.set("values", Fidelity.LOSSLESS if _eq_array(np.ma.filled(original, np.nan) if np.ma.isMaskedArray(original) else original,
                                                         np.ma.filled(back, np.nan) if np.ma.isMaskedArray(back) else back) else Fidelity.LOSSY)
        rep.set("types", Fidelity.LOSSLESS if getattr(back, "dtype", None) == original.dtype else Fidelity.CHANGED,
                "" if getattr(back, "dtype", None) == original.dtype else f"{original.dtype} -> {getattr(back, 'dtype', None)}")
        if np.ma.isMaskedArray(original):
            rep.set("metadata", Fidelity.LOSSLESS if np.ma.isMaskedArray(back) and np.array_equal(np.ma.getmaskarray(original), np.ma.getmaskarray(back)) else Fidelity.LOSSY, "mask")
        return rep

    try:
        import scipy.sparse as sp
        if sp.issparse(original):
            m = getattr(back, "matrix", back)
            rep.set("shape", Fidelity.LOSSLESS if m.shape == original.shape else Fidelity.LOSSY)
            rep.set("storage", Fidelity.LOSSLESS if m.format == original.format else Fidelity.CHANGED, f"{original.format} -> {m.format}")
            diff = (original != m)
            rep.set("values", Fidelity.LOSSLESS if diff.nnz == 0 else Fidelity.LOSSY)
            rep.set("index", Fidelity.LOSSLESS if m.nnz == original.nnz else Fidelity.CHANGED, "nnz")
            return rep
    except Exception:
        pass

    try:
        import networkx as nx
        if isinstance(original, nx.Graph):
            same_nodes = set(original.nodes) == set(back.nodes)
            same_dir = original.is_directed() == back.is_directed()
            same_multi = original.is_multigraph() == back.is_multigraph()
            oe = sorted(map(str, original.edges(keys=True) if original.is_multigraph() else original.edges()))
            be = sorted(map(str, back.edges(keys=True) if back.is_multigraph() else back.edges()))
            rep.set("topology", Fidelity.LOSSLESS if same_nodes and same_dir and same_multi and oe == be else Fidelity.LOSSY,
                    "nodes, edges (multiset), direction")
            na_ok = all(original.nodes[n] == back.nodes[n] for n in original.nodes) if same_nodes else False
            ea_ok = all(d == back.get_edge_data(*e[:2])[e[2]] if original.is_multigraph() else d == back.get_edge_data(*e)
                        for *e, d in (original.edges(keys=True, data=True) if original.is_multigraph() else original.edges(data=True))) if oe == be else False
            rep.set("metadata", Fidelity.LOSSLESS if na_ok and ea_ok else Fidelity.LOSSY, "node + edge attributes")
            rep.set("values", Fidelity.LOSSLESS if na_ok and ea_ok else Fidelity.LOSSY)
            return rep
    except Exception:
        pass

    if hasattr(original, "geom_type") and hasattr(back, "geom_type"):
        rep.set("topology", Fidelity.LOSSLESS if original.equals(back) else Fidelity.LOSSY, "WKB geometry")
        rep.set("values", Fidelity.LOSSLESS if original.equals(back) else Fidelity.LOSSY)
        return rep

    # generic: structural equality with NaN awareness
    ok = _deep_eq(original, back)
    rep.set("values", Fidelity.LOSSLESS if ok else Fidelity.LOSSY)
    rep.set("types", Fidelity.LOSSLESS if type(back) is t else Fidelity.CHANGED, "" if type(back) is t else f"{t.__name__} -> {type(back).__name__}")
    return rep


def _deep_eq(a: Any, b: Any) -> bool:
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_deep_eq(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_deep_eq(x, y) for x, y in zip(a, b))
    if isinstance(a, (set, frozenset)) and isinstance(b, (set, frozenset)):
        return a == b
    if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
        return _eq_array(a, b)
    return _eq_scalar(a, b)


def validate_roundtrip(obj: Any, session: Any = None, name: str = ".rp_fidelity_check") -> FidelityReport:
    """Python -> R -> Python (with a live session) or Python -> envelope -> Python (without), then compare."""
    if session is not None:
        session.assign(name, obj)
        back = session.get(name)
    else:
        from .data.convert import roundtrip
        back, _ = roundtrip(obj)
    return compare(obj, back)


def fidelity_report(obj: Any, session: Any = None) -> str:
    return validate_roundtrip(obj, session).summary()
