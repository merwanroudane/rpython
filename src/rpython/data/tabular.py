"""Tabular data (sections 8-9): pandas, Polars, PyArrow, dataframe-interchange
objects, Arrow datasets  <->  data.frame / tibble / data.table / arrow Table.

Envelope ``kind: "table"``::

    {"kind": "table", "nrow": n,
     "columns": [{"name": .., "type": <rtype>, "values": [...] | null,
                  "semantic": {...}}, ...],
     "arrow": <ipc path> | null,          # columnar payload when Arrow is used
     "index": {"columns": [...], "names": [...], "row_names": bool} | null,
     "attrs": {...},                       # user attrs (pandas df.attrs)
     "semantics": {...},                   # timeseries / panel / spatial / labels ...
     "meta": {"source_class": .., "class_hint": "data.frame"|"tibble"|"data.table"}}

Column ``semantic`` sidecars carry what Arrow / JSON alone cannot:
``categorical`` (levels + ordered), ``datetime`` (tz or "naive"),
``labels`` (variable/value labels), ``nullable`` (pandas extension dtype),
``list``/``struct`` element types, ``decimal`` precision/scale.

Per column the wire type is one of the atomic ``rtype`` names plus
``factor``, ``list``, ``struct``, ``geometry`` (spatial module).
"""
from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd

from .context import Context
from .primitives import (classify_scalar, encode_values, decode_values, promote,
                         encode_scalar_value, decode_scalar_value, encode_datetime)
from .registry import Adapter, REGISTRY
from .semantic import Confidence, ConversionPath, Detection, Fidelity


# --------------------------------------------------------------------------
# Column encoding (JSON path)
# --------------------------------------------------------------------------

def _dtype_semantic(s: pd.Series, ctx: Context | None) -> tuple[str, dict[str, Any]]:
    """Return (rtype, semantic sidecar) for a pandas Series."""
    dt = s.dtype
    sem: dict[str, Any] = {}
    if isinstance(dt, pd.CategoricalDtype):
        cats = dt.categories
        sem["categorical"] = {"levels": [str(c) for c in cats], "ordered": bool(dt.ordered),
                              "level_type": classify_scalar(cats[0]) if len(cats) else "character"}
        return "factor", sem
    if isinstance(dt, pd.DatetimeTZDtype):
        sem["datetime"] = {"tz": str(dt.tz), "unit": getattr(dt, "unit", "ns")}
        return "datetime", sem
    if dt.kind == "M":
        sem["datetime"] = {"tz": "naive", "unit": np.datetime_data(dt)[0]}
        return "datetime", sem
    if dt.kind == "m":
        sem["timedelta"] = {"units": "secs"}
        return "timedelta", sem
    if isinstance(dt, pd.PeriodDtype):
        sem["period"] = {"freq": dt.freq.freqstr, "dtype": str(dt)}
        return "period", sem
    if isinstance(dt, pd.IntervalDtype):
        sem["interval"] = {"closed": dt.closed}
        return "interval", sem
    if isinstance(dt, pd.SparseDtype):
        sem["sparse"] = {"fill_value": None if pd.isna(dt.fill_value) else dt.fill_value}
        dt = dt.subtype
    name = str(dt)
    if name in ("Int8", "Int16", "Int32", "UInt8", "UInt16"):
        sem["nullable"] = name
        return "integer", sem
    if name in ("Int64", "UInt32", "UInt64"):
        sem["nullable"] = name
        vals = s.dropna()
        if len(vals) and (vals.min() < -2**31 + 1 or vals.max() > 2**31 - 1):
            return "int64", sem
        return "integer", sem
    if name in ("Float32", "Float64"):
        sem["nullable"] = name
        return "double", sem
    if name == "boolean":
        sem["nullable"] = name
        return "logical", sem
    if name in ("string", "string[python]", "string[pyarrow]", "str") or str(dt).startswith("str"):
        sem["nullable"] = name   # exact dtype ("str" vs "string") restored on round trip
        return "character", sem
    if dt.kind == "b":
        return "logical", sem
    if dt.kind in "iu":
        if dt.itemsize > 4 or dt == np.uint32:
            vals = s.to_numpy()
            if vals.size and (vals.min() < -2**31 + 1 or vals.max() > 2**31 - 1):
                if ctx is not None:
                    ctx.plan.risk(f"column {s.name!r}: {dt} beyond 32-bit range -> int64 (bit64 in R)")
                return "int64", sem
        sem["np_dtype"] = str(dt)
        return "integer", sem
    if dt.kind == "f":
        if dt == np.float32:
            sem["np_dtype"] = "float32"
        return "double", sem
    if dt.kind == "c":
        return "complex", sem
    if dt.kind in "US":
        return "character", sem
    if dt.kind == "O":
        types = {classify_scalar(v) for v in s if v is not None and not _isna_scalar(v)}
        if not types:
            sem["all_missing"] = True      # object column of None/NA only: comes back as object, not bool
            return "character", sem
        if types <= {"list", "unknown"} or all(isinstance(v, (list, tuple, np.ndarray)) for v in s.dropna()):
            return "list", sem
        if all(isinstance(v, dict) for v in s.dropna()):
            return "struct", sem
        if len(types) == 1:
            t = types.pop()
            if t in ("date", "datetime", "raw", "decimal", "uuid", "fraction", "character", "int64",
                     "integer", "double", "logical", "complex", "timedelta"):
                if t == "datetime":
                    tzs = {getattr(v, "tzinfo", None) for v in s.dropna()}
                    sem["datetime"] = {"tz": "naive" if tzs == {None} else str(next(iter(tzs)))}
                return t, sem
        pt = promote(list(types))
        if pt:
            return pt, sem
        # heterogeneous object column: keep as list column (R list column)
        sem["heterogeneous"] = True
        return "list", sem
    raise TypeError(f"unsupported column dtype {dt}")


def _isna_scalar(v: Any) -> bool:
    try:
        r = pd.isna(v)
        return bool(r) if np.isscalar(r) or isinstance(r, (bool, np.bool_)) else False
    except Exception:
        return False


def encode_column(name: str, s: pd.Series, ctx: Context, inline: bool = True) -> dict[str, Any]:
    rtype, sem = _dtype_semantic(s, ctx)
    col: dict[str, Any] = {"name": str(name), "type": rtype, "semantic": sem, "values": None}
    if not inline:
        return col
    if rtype == "factor":
        codes = s.cat.codes.to_numpy()
        levels = sem["categorical"]["levels"]
        col["values"] = [None if c < 0 else levels[c] for c in codes]
    elif rtype == "datetime":
        col["values"] = [None if pd.isna(v) else pd.Timestamp(v).isoformat() for v in s]
    elif rtype == "timedelta":
        col["values"] = [None if pd.isna(v) else pd.Timedelta(v).total_seconds() for v in s]
    elif rtype == "period":
        col["values"] = [None if pd.isna(v) else str(v) for v in s]
    elif rtype == "interval":
        col["values"] = [None if pd.isna(v) else [_json_scalar(v.left), _json_scalar(v.right)] for v in s]
    elif rtype == "list":
        from .convert import to_envelope
        col["values"] = [None if _isna_scalar(v) else to_envelope(list(v) if isinstance(v, (tuple, np.ndarray)) else v, ctx) for v in s]
    elif rtype == "struct":
        from .convert import to_envelope
        col["values"] = [None if _isna_scalar(v) else to_envelope(v, ctx) for v in s]
    elif "nullable" in sem or s.dtype.kind == "O":
        col["values"] = [encode_scalar_value(v, rtype, ctx) for v in s.tolist()]
    else:
        col["values"] = encode_values(s.to_numpy(), rtype, ctx)
        if rtype == "double" and s.dtype.kind == "f" and ctx.config.missing == "preserve":
            # pandas semantics: NaN in a float64 column *is* the missing marker -> R NA
            col["values"] = ["NA" if v == "NaN" else v for v in col["values"]]
            sem["nan_is_missing"] = True
    return col


def _json_scalar(v: Any) -> Any:
    t = classify_scalar(v)
    return encode_scalar_value(v, t if t != "unknown" else "character")


def decode_column(col: dict[str, Any], ctx: Context, values: Any = None) -> pd.Series:
    """Decode one column (from JSON values or an already-loaded Arrow column)."""
    rtype = col["type"]
    sem = col.get("semantic") or {}
    name = col.get("name")
    if values is None:
        values = col.get("values") or []
        if rtype == "factor":
            cat = sem.get("categorical", {})
            levels = cat.get("levels", [])
            s = pd.Series(pd.Categorical(values, categories=levels, ordered=cat.get("ordered", False)), name=name)
            return s
        if rtype == "datetime":
            tz = sem.get("datetime", {}).get("tz", "naive")
            if tz and tz != "naive":
                s = pd.Series(pd.to_datetime(values, utc=True), name=name).dt.tz_convert(tz)
            else:
                stamps = [None if v is None else pd.Timestamp(v).tz_localize(None) if pd.Timestamp(v).tzinfo is not None else pd.Timestamp(v) for v in values]
                s = pd.Series(pd.to_datetime(stamps), name=name)
            return s
        if rtype == "timedelta":
            return pd.Series(pd.to_timedelta([None if v is None else float(v) for v in values], unit="s"), name=name)
        if rtype == "period":
            pinfo = sem.get("period", {})
            if pinfo.get("dtype"):
                return pd.Series(pd.PeriodIndex([None if v is None else v for v in values], dtype=pinfo["dtype"]), name=name)
            return pd.Series(pd.PeriodIndex([None if v is None else v for v in values], freq=pinfo.get("freq")), name=name)
        if rtype == "interval":
            closed = sem.get("interval", {}).get("closed", "right")
            ivs = [None if v is None else pd.Interval(v[0], v[1], closed=closed) for v in values]
            return pd.Series(ivs, name=name)
        if rtype in ("list", "struct"):
            from .convert import from_envelope
            return pd.Series([None if v is None else from_envelope(v, ctx) for v in values], name=name, dtype=object)
        if rtype == "date":
            return pd.Series([None if v is None else decode_scalar_value(v, "date") for v in values], name=name, dtype=object)
        if rtype in ("raw", "decimal", "uuid", "fraction"):
            return pd.Series([decode_scalar_value(v, rtype) for v in values], name=name, dtype=object)
        if rtype == "double" and not sem.get("nullable"):
            has_na = any(v == "NA" or v is None for v in values)
            has_nan = any(v == "NaN" for v in values)
            if has_na and not has_nan:
                s = pd.Series(np.asarray([np.nan if (v == "NA" or v is None) else decode_scalar_value(v, "double") for v in values], dtype=float), name=name)
                return _restore_dtype(s, rtype, sem)
            if has_na and has_nan and ctx is not None:
                ctx.plan.note(f"column {name!r}: R NA and NaN both present -> pandas Float64 keeps them distinct")
        arr = decode_values(values, rtype, ctx=ctx)
        s = pd.Series(arr, name=name)
    else:
        s = pd.Series(values, name=name) if not isinstance(values, pd.Series) else values.rename(name)
        s = _apply_semantic_from_arrow(s, rtype, sem)
    return _restore_dtype(s, rtype, sem)


def _apply_semantic_from_arrow(s: pd.Series, rtype: str, sem: dict[str, Any]) -> pd.Series:
    if rtype == "factor":
        cat = sem.get("categorical", {})
        levels = cat.get("levels")
        if levels is not None:
            vals = s.astype(object).where(s.notna(), None)
            if isinstance(s.dtype, pd.CategoricalDtype):
                vals = s.astype(str).where(s.notna(), None)
            s = pd.Series(pd.Categorical(vals, categories=levels, ordered=cat.get("ordered", False)), name=s.name)
    elif rtype == "datetime":
        tz = sem.get("datetime", {}).get("tz", "naive")
        if s.dtype.kind == "M" or isinstance(s.dtype, pd.DatetimeTZDtype):
            if tz == "naive":
                if getattr(s.dt, "tz", None) is not None:
                    s = s.dt.tz_convert("UTC").dt.tz_localize(None)
            else:
                s = s.dt.tz_localize("UTC").dt.tz_convert(tz) if s.dt.tz is None else s.dt.tz_convert(tz)
        else:
            s = pd.to_datetime(s, utc=(tz != "naive"))
            if tz != "naive":
                s = s.dt.tz_convert(tz)
    elif rtype == "date":
        if s.dtype.kind == "M":
            s = pd.Series(s.dt.date.where(s.notna(), None), name=s.name, dtype=object)
    elif rtype == "timedelta" and s.dtype.kind != "m":
        s = pd.to_timedelta(s.astype(float), unit="s")
    elif rtype == "list":
        s = s.apply(lambda v: v.tolist() if isinstance(v, np.ndarray) else v)
    return s


def _restore_dtype(s: pd.Series, rtype: str, sem: dict[str, Any]) -> pd.Series:
    nullable = sem.get("nullable")
    try:
        if sem.get("all_missing"):
            return pd.Series([None] * len(s), index=s.index, name=s.name, dtype=object)
        if nullable:
            return s.astype(nullable)
        np_dtype = sem.get("np_dtype")
        if np_dtype and not s.isna().any():
            return s.astype(np_dtype)
        if rtype == "integer" and s.dtype.kind == "f" and not s.isna().any():
            return s.astype("int64")
        if rtype == "integer" and s.dtype.kind == "f" and s.isna().any():
            return s.astype("Int64")
        if rtype == "integer" and s.dtype == np.int32 and not np_dtype:
            return s.astype("int64")
        if rtype == "logical" and s.dtype.kind == "O":
            return s.astype("boolean") if s.isna().any() else s.astype(bool)
        if rtype == "double" and isinstance(s.dtype, pd.api.extensions.ExtensionDtype) and not nullable:
            # R NA in a double column -> keep Float64 so NA != NaN
            return s
    except Exception:
        return s
    return s


# --------------------------------------------------------------------------
# Frame encoding
# --------------------------------------------------------------------------

def _index_to_columns(df: pd.DataFrame, ctx: Context) -> tuple[pd.DataFrame, dict[str, Any] | None]:
    idx = df.index
    if isinstance(idx, pd.RangeIndex) and idx.start == 0 and idx.step == 1 and idx.name is None:
        return df, None
    if isinstance(idx, pd.MultiIndex):
        names = [n if n is not None else f"level_{i}" for i, n in enumerate(idx.names)]
        out = df.reset_index(allow_duplicates=True)
        out.columns = [*names, *df.columns] if list(out.columns[:len(names)]) != names else out.columns
        return out, {"columns": names, "names": [n for n in idx.names], "kind": "multiindex", "row_names": False}
    name = idx.name if idx.name is not None else "index"
    if name in df.columns:
        name = f"__index_{name}"
    out = df.copy()
    out.insert(0, name, idx.to_numpy() if not isinstance(idx, pd.CategoricalIndex) else idx.to_series().to_numpy())
    row_names = bool(idx.is_unique and idx.dtype.kind in "OU" and not isinstance(idx, pd.DatetimeIndex))
    kind = "datetime" if isinstance(idx, pd.DatetimeIndex) else "period" if isinstance(idx, pd.PeriodIndex) else "index"
    return out, {"columns": [name], "names": [idx.name], "kind": kind, "row_names": row_names}


def _columns_unique(df: pd.DataFrame, ctx: Context) -> tuple[pd.DataFrame, dict[str, Any]]:
    cols = [str(c) for c in df.columns]
    mapping: dict[str, Any] = {"original": [c if isinstance(c, str) else repr(c) for c in df.columns],
                               "non_string": [i for i, c in enumerate(df.columns) if not isinstance(c, str)]}
    if len(set(cols)) != len(cols):
        seen: dict[str, int] = {}
        new = []
        for c in cols:
            if c in seen:
                seen[c] += 1
                new.append(f"{c}__dup{seen[c]}")
            else:
                seen[c] = 0
                new.append(c)
        ctx.plan.note("duplicate column names made unique with reversible __dupN suffix")
        mapping["renamed"] = dict(zip(new, cols))
        cols = new
    if any(c != str(o) for c, o in zip(cols, df.columns)) or mapping["non_string"] or "renamed" in mapping:
        df = df.copy()
        df.columns = cols
    return df, mapping


def encode_frame(df: pd.DataFrame, ctx: Context, semantics: dict[str, Any] | None = None,
                 class_hint: str = "data.frame", extra_meta: dict[str, Any] | None = None) -> dict[str, Any]:
    hint = (getattr(df, "attrs", {}) or {}).get("rpython", {})
    if class_hint == "data.frame" and isinstance(hint, dict) and hint.get("class_hint"):
        class_hint = hint["class_hint"]          # tibble / data.table identity survives the round trip
    df2, index_info = _index_to_columns(df, ctx)
    df2, name_map = _columns_unique(df2, ctx)
    nrow = len(df2)
    use_arrow = ctx.use_arrow(nrow) and _arrow_encodable(df2)
    columns = [encode_column(c, df2[c], ctx, inline=not use_arrow) for c in df2.columns]
    meta: dict[str, Any] = {"source_class": f"{type(df).__module__}.{type(df).__qualname__}",
                            "class_hint": class_hint, "names": name_map, **(extra_meta or {})}
    attrs = {k: v for k, v in (getattr(df, "attrs", {}) or {}).items() if _jsonable(v)}
    env: dict[str, Any] = {"rpx": 1, "kind": "table", "nrow": nrow, "columns": columns,
                           "arrow": None, "index": index_info, "attrs": attrs,
                           "semantics": semantics or {}, "meta": meta}
    if use_arrow:
        from .arrow_io import write_table_arrow
        import pyarrow as pa
        tbl = pa.Table.from_pandas(df2, preserve_index=False)
        env["arrow"] = write_table_arrow(tbl, ctx, {"columns": [c["name"] for c in columns]})
        ctx.record("table", ConversionPath.STANDARD, "arrow-ipc",
                   f"{nrow:,} x {len(columns)} via Feather + semantic sidecar")
        ctx.plan.estimated_bytes = max(ctx.plan.estimated_bytes, int(tbl.nbytes))
        ctx.plan.copies = 1
    else:
        ctx.record("table", ConversionPath.NATIVE, "json", f"{nrow:,} x {len(columns)} inline columns")
        ctx.plan.estimated_bytes = max(ctx.plan.estimated_bytes, int(df2.memory_usage(deep=True).sum()))
    ctx.plan.shape = (nrow, len(df.columns))
    ctx.plan.fidelity.set("values", Fidelity.LOSSLESS)
    ctx.plan.fidelity.set("names", Fidelity.LOSSLESS)
    ctx.plan.fidelity.set("types", Fidelity.LOSSLESS, "dtypes + nullability in sidecar")
    ctx.plan.fidelity.set("index", Fidelity.LOSSLESS if index_info or True else Fidelity.NA,
                          "index carried as leading column(s)" if index_info else "default RangeIndex")
    ctx.plan.fidelity.set("metadata", Fidelity.LOSSLESS if attrs or not getattr(df, "attrs", None) else Fidelity.LOSSY,
                          "" if attrs or not getattr(df, "attrs", None) else "non-JSON attrs dropped")
    return env


def _arrow_encodable(df: pd.DataFrame) -> bool:
    try:
        import pyarrow  # noqa: F401
    except Exception:
        return False
    for c in df.columns:
        s = df[c]
        if s.dtype.kind == "O":
            try:
                t, _ = _dtype_semantic(s, None)
            except TypeError:
                return False
            if t in ("struct", "decimal", "fraction", "uuid", "complex"):
                return False
        if s.dtype.kind == "c" or isinstance(s.dtype, (pd.IntervalDtype, pd.SparseDtype)):
            return False
    return True


def _jsonable(v: Any) -> bool:
    try:
        json.dumps(v)
        return True
    except Exception:
        return False


def decode_frame(env: dict[str, Any], ctx: Context) -> pd.DataFrame:
    cols = env.get("columns") or []
    if env.get("arrow"):
        from .arrow_io import read_table_arrow
        tbl = read_table_arrow(env["arrow"])
        pdf = tbl.to_pandas(types_mapper=_types_mapper)
        series = {}
        for c in cols:
            name = c["name"]
            if name in pdf.columns:
                series[name] = decode_column(c, ctx, values=pdf[name])
            else:
                series[name] = decode_column(c, ctx)
        ctx.record("table", ConversionPath.STANDARD, "arrow-ipc", f"{env.get('nrow', 0):,} rows via Feather")
    else:
        series = {c["name"]: decode_column(c, ctx) for c in cols}
        ctx.record("table", ConversionPath.NATIVE, "json", f"{env.get('nrow', 0):,} rows inline")
    if series:
        df = pd.DataFrame(series)
    else:
        df = pd.DataFrame(index=range(env.get("nrow", 0)))
    # restore names
    meta = env.get("meta") or {}
    names = meta.get("names") or {}
    if names.get("renamed"):
        df.columns = [names["renamed"].get(c, c) for c in df.columns]
    # restore index
    idx = env.get("index")
    if idx and idx.get("columns") and all(c in df.columns for c in idx["columns"]):
        icols = idx["columns"]
        if idx.get("kind") == "multiindex":
            df = df.set_index(icols)
            df.index.names = [n for n in idx.get("names", icols)]
        else:
            df = df.set_index(icols[0])
            df.index.name = (idx.get("names") or [None])[0]
            if idx.get("kind") == "period" and not isinstance(df.index, pd.PeriodIndex):
                try:
                    df.index = pd.PeriodIndex(df.index)
                except Exception:
                    pass
    elif env.get("row_names"):
        rn = env["row_names"]
        if not _is_default_rownames(rn):
            df.index = pd.Index(rn)
    attrs = env.get("attrs") or {}
    if attrs:
        df.attrs.update(attrs)
    if meta.get("class_hint") and meta["class_hint"] != "data.frame":
        df.attrs.setdefault("rpython", {})["class_hint"] = meta["class_hint"]
    ctx.plan.shape = df.shape
    ctx.plan.fidelity.set("values", Fidelity.LOSSLESS)
    ctx.plan.fidelity.set("names", Fidelity.LOSSLESS)
    ctx.plan.fidelity.set("types", Fidelity.LOSSLESS)
    return df


def _is_default_rownames(rn: list[Any]) -> bool:
    return all(isinstance(v, int) for v in rn) and rn == list(range(1, len(rn) + 1))


def _types_mapper(t: Any) -> Any:
    """Keep Arrow nulls distinguishable from NaN by using pandas nullable dtypes
    only for columns that actually contain nulls -- handled later by sidecar."""
    return None


# --------------------------------------------------------------------------
# Adapter: pandas / polars / pyarrow / interchange / datasets
# --------------------------------------------------------------------------

def _is_polars_df(obj: Any) -> bool:
    return type(obj).__module__.startswith("polars") and type(obj).__name__ == "DataFrame"


def _is_polars_lazy(obj: Any) -> bool:
    return type(obj).__module__.startswith("polars") and type(obj).__name__ == "LazyFrame"


def _is_polars_series(obj: Any) -> bool:
    return type(obj).__module__.startswith("polars") and type(obj).__name__ == "Series"


def _is_pyarrow_table(obj: Any) -> bool:
    return type(obj).__module__.startswith("pyarrow") and type(obj).__name__ in ("Table", "RecordBatch")


def _is_pyarrow_dataset(obj: Any) -> bool:
    return type(obj).__module__.startswith("pyarrow.dataset") or type(obj).__name__.endswith("Dataset") and type(obj).__module__.startswith("pyarrow")


def _is_dask_df(obj: Any) -> bool:
    return type(obj).__module__.startswith("dask") and type(obj).__name__ in ("DataFrame", "Series")


def _has_interchange(obj: Any) -> bool:
    return hasattr(obj, "__dataframe__") and not isinstance(obj, pd.DataFrame)


class TableAdapter(Adapter):
    family = "table"
    kinds = ("table", "column", "dataset")
    tier = ConversionPath.STANDARD
    priority = 30

    def detect(self, obj: Any) -> Detection | None:
        if isinstance(obj, pd.DataFrame):
            return Detection("table", Confidence.CONFIRMED, f"pandas.DataFrame {obj.shape}")
        if isinstance(obj, pd.Series):
            return Detection("column", Confidence.CONFIRMED, f"pandas.Series {obj.dtype}")
        if isinstance(obj, (pd.Index,)):
            return Detection("column", Confidence.CONFIRMED, f"pandas.Index {obj.dtype}")
        if isinstance(obj, np.ndarray) and obj.dtype.names:
            return Detection("table", Confidence.CONFIRMED, "numpy structured array")
        if _is_polars_df(obj) or _is_polars_lazy(obj) or _is_polars_series(obj):
            return Detection("table", Confidence.CONFIRMED, type(obj).__name__ + " (polars)")
        if _is_pyarrow_table(obj):
            return Detection("table", Confidence.CONFIRMED, "pyarrow." + type(obj).__name__)
        if _is_pyarrow_dataset(obj):
            return Detection("dataset", Confidence.CONFIRMED, "pyarrow.dataset (lazy, shared source)")
        if _is_dask_df(obj):
            return Detection("table", Confidence.CONFIRMED, "dask DataFrame (lazy)")
        if _has_interchange(obj) or hasattr(obj, "__arrow_c_stream__"):
            return Detection("table", Confidence.CONFIRMED, "dataframe interchange protocol")
        return None

    # ------------------------------------------------------------------ encode
    def encode(self, obj: Any, ctx: Context) -> dict[str, Any]:
        if isinstance(obj, pd.DataFrame):
            return encode_frame(obj, ctx)
        if isinstance(obj, pd.Series):
            return self._encode_series(obj, ctx)
        if isinstance(obj, pd.Index):
            return self._encode_series(obj.to_series(index=None).reset_index(drop=True), ctx, index_kind="pandas.Index")
        if isinstance(obj, np.ndarray) and obj.dtype.names:
            return encode_frame(pd.DataFrame(obj), ctx, extra_meta={"structured_array": True})
        if _is_polars_series(obj):
            return self._encode_series(obj.to_pandas(), ctx, index_kind="polars.Series")
        if _is_polars_lazy(obj):
            import polars as pl
            nrows = int(obj.select(pl.len()).collect().item())
            ncols = len(obj.collect_schema())
            ctx.memory_guard(f"polars LazyFrame ({nrows:,} rows)", nrows * ncols * 8,
                             "collect a filtered subset, or rp.lazy(lf) to keep it lazy")
            ctx.plan.note("polars LazyFrame materialised (below memory threshold)")
            ctx.plan.fidelity.set("laziness", Fidelity.CHANGED, "query plan executed before transfer")
            obj = obj.collect()
        if _is_polars_df(obj):
            tbl = obj.to_arrow()
            return self._encode_arrow_table(tbl, ctx, class_hint="tibble", source="polars.DataFrame")
        if _is_pyarrow_table(obj):
            import pyarrow as pa
            tbl = obj if isinstance(obj, pa.Table) else pa.Table.from_batches([obj])
            return self._encode_arrow_table(tbl, ctx, class_hint="tibble", source=f"pyarrow.{type(obj).__name__}")
        if _is_pyarrow_dataset(obj):
            return self._encode_dataset(obj, ctx)
        if _is_dask_df(obj):
            est = int(obj.partitions[0].compute().memory_usage(deep=True).sum()) * obj.npartitions
            ctx.memory_guard(f"dask DataFrame ({obj.npartitions} partitions)", est,
                             "persist to Parquet and share the dataset instead")
            ctx.plan.fidelity.set("laziness", Fidelity.CHANGED, "dask graph computed before transfer")
            return encode_frame(obj.compute(), ctx, extra_meta={"dask_partitions": obj.npartitions})
        if hasattr(obj, "__arrow_c_stream__"):
            import pyarrow as pa
            return self._encode_arrow_table(pa.table(obj), ctx, source=type(obj).__name__)
        if _has_interchange(obj):
            from pyarrow.interchange import from_dataframe
            return self._encode_arrow_table(from_dataframe(obj), ctx, source=type(obj).__name__)
        raise TypeError(type(obj))

    def _encode_series(self, s: pd.Series, ctx: Context, index_kind: str = "pandas.Series") -> dict[str, Any]:
        col = encode_column(s.name if s.name is not None else "", s, ctx, inline=True)
        idx = s.index
        default_index = isinstance(idx, pd.RangeIndex) and idx.start == 0 and idx.step == 1
        names = None if default_index else [str(i) for i in idx]
        env = {"rpx": 1, "kind": "column", "column": col, "names": names, "nrow": len(s),
               "meta": {"source_class": index_kind, "series_name": s.name,
                        "index_dtype": None if default_index else str(idx.dtype)}}
        ctx.record("column", ConversionPath.NATIVE, "json", f"{index_kind} -> R vector ({col['type']})")
        ctx.plan.fidelity.set("values", Fidelity.LOSSLESS)
        ctx.plan.fidelity.set("types", Fidelity.LOSSLESS)
        ctx.plan.fidelity.set("index", Fidelity.LOSSLESS if names is None else Fidelity.CHANGED,
                              "" if names is None else "index stored as R names (character)")
        return env

    def _encode_arrow_table(self, tbl: Any, ctx: Context, class_hint: str = "tibble", source: str = "") -> dict[str, Any]:
        import pyarrow as pa
        pdf = tbl.to_pandas()
        env = encode_frame(pdf, ctx, class_hint=class_hint, extra_meta={"arrow_schema": str(tbl.schema)})
        env["meta"]["source_class"] = source or env["meta"]["source_class"]
        if tbl.schema.metadata:
            env["meta"]["schema_metadata"] = {k.decode(): v.decode(errors="replace") for k, v in tbl.schema.metadata.items()
                                              if k != b"pandas"}
        return env

    def _encode_dataset(self, ds: Any, ctx: Context) -> dict[str, Any]:
        files = list(getattr(ds, "files", []) or [])
        fmt = getattr(getattr(ds, "format", None), "default_extname", "parquet")
        env = {"rpx": 1, "kind": "dataset", "format": fmt, "files": files,
               "schema": str(ds.schema), "meta": {"source_class": "pyarrow.dataset.Dataset"}}
        ctx.record("dataset", ConversionPath.LAZY, "shared-files",
                   f"{len(files)} {fmt} file(s) opened lazily in R with arrow::open_dataset (no copy)")
        ctx.plan.fidelity.set("laziness", Fidelity.LOSSLESS, "shared source, nothing materialised")
        ctx.plan.fidelity.set("values", Fidelity.LOSSLESS)
        ctx.plan.copies = 0
        return env

    # ------------------------------------------------------------------ decode
    def decode(self, env: dict[str, Any], ctx: Context) -> Any:
        kind = env["kind"]
        if kind == "column":
            s = decode_column(env["column"], ctx)
            names = env.get("names")
            if names:
                s.index = pd.Index(names)
            meta = env.get("meta") or {}
            if meta.get("series_name") is not None:
                s.name = meta["series_name"]
            src = meta.get("source_class", "")
            if src == "polars.Series":
                try:
                    import polars as pl
                    return pl.from_pandas(s)
                except Exception:
                    pass
            if src == "pandas.Index":
                return pd.Index(s)
            return s
        if kind == "dataset":
            import pyarrow.dataset as pads
            ctx.record("dataset", ConversionPath.LAZY, "shared-files", "R arrow Dataset re-opened lazily")
            return pads.dataset(env["files"], format=env.get("format", "parquet"))
        df = decode_frame(env, ctx)
        src = (env.get("meta") or {}).get("source_class", "")
        if src.startswith("polars"):
            try:
                import polars as pl
                return pl.from_pandas(df.reset_index() if not isinstance(df.index, pd.RangeIndex) else df)
            except Exception:
                pass
        if src.startswith("pyarrow"):
            try:
                import pyarrow as pa
                return pa.Table.from_pandas(df, preserve_index=not isinstance(df.index, pd.RangeIndex))
            except Exception:
                pass
        if (env.get("meta") or {}).get("structured_array"):
            return df.to_records(index=False)
        return df


REGISTRY.register(TableAdapter(), tested=True,
                  limitations=("Interval / complex / Decimal columns use the JSON path (no Arrow)",
                               "pandas attrs must be JSON-serialisable to survive the trip"))
