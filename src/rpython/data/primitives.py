"""Scalars and atomic vectors (section 4).

Portable encoding (``kind == "vector"``)::

    {"rpx": 1, "kind": "vector", "type": <rtype>, "values": [...],
     "names": [...] | null, "scalar": bool, "meta": {...}}

``rtype`` is one of ``null, logical, integer, int64, double, complex,
character, raw, decimal, fraction, date, datetime, timedelta, uuid``.

Special values are encoded explicitly so that R ``NA`` / ``NaN`` /
``Inf`` / ``-Inf`` and Python ``None`` / ``nan`` / ``inf`` never collapse
silently:

* double: numbers; ``"NA"``, ``"NaN"``, ``"Inf"``, ``"-Inf"`` as strings
* integer / logical / character / date / datetime: ``null`` == ``NA``
* int64: decimal strings (never rounded through float64)
* complex: ``[re, im]`` pairs or ``null``
* raw: base64 string
"""
from __future__ import annotations

import base64
import datetime as _dt
import decimal
import enum
import fractions
import math
import uuid
from typing import Any

import numpy as np

from .context import Context
from .registry import Adapter, REGISTRY
from .semantic import Confidence, ConversionPath, Detection, Fidelity

INT32_MIN, INT32_MAX = -2**31 + 1, 2**31 - 1      # R integer NA is -2^31
FLOAT_EXACT_INT = 2**53

# --------------------------------------------------------------------------
# Scalar encoding helpers
# --------------------------------------------------------------------------


def _encode_double(x: Any) -> Any:
    if x is None:
        return "NA"
    try:
        import pandas as pd
        if x is pd.NA:
            return "NA"
    except Exception:  # pragma: no cover
        pass
    f = float(x)
    if math.isnan(f):
        return "NaN"
    if math.isinf(f):
        return "Inf" if f > 0 else "-Inf"
    return f


def _decode_double(v: Any) -> float | None:
    if v is None or v == "NA":
        return None
    if v == "NaN":
        return math.nan
    if v == "Inf":
        return math.inf
    if v == "-Inf":
        return -math.inf
    return float(v)


def _is_missing(x: Any) -> bool:
    if x is None:
        return True
    try:
        import pandas as pd
        if x is pd.NA or x is pd.NaT:
            return True
    except Exception:  # pragma: no cover
        pass
    if isinstance(x, np.datetime64) and np.isnat(x):
        return True
    return False


def _is_nan(x: Any) -> bool:
    return (isinstance(x, (float, np.floating)) and math.isnan(x))


def classify_scalar(x: Any) -> str:
    """Return the R type name for a single Python value."""
    if x is None:
        return "null"
    try:
        import pandas as pd
        if x is pd.NA:
            return "null"
        if x is pd.NaT:
            return "datetime"
        if isinstance(x, pd.Timestamp):
            return "datetime"
        if isinstance(x, pd.Timedelta):
            return "timedelta"
        if isinstance(x, pd.Period):
            return "period"
    except Exception:  # pragma: no cover
        pass
    if isinstance(x, (bool, np.bool_)):
        return "logical"
    if isinstance(x, enum.Enum):
        return classify_scalar(x.value)
    if isinstance(x, (int, np.integer)):
        v = int(x)
        if INT32_MIN <= v <= INT32_MAX:
            return "integer"
        return "int64"
    if isinstance(x, (float, np.floating)):
        return "double"
    if isinstance(x, (complex, np.complexfloating)):
        return "complex"
    if isinstance(x, decimal.Decimal):
        return "decimal"
    if isinstance(x, fractions.Fraction):
        return "fraction"
    if isinstance(x, uuid.UUID):
        return "uuid"
    if isinstance(x, (str, np.str_)):
        return "character"
    if isinstance(x, (bytes, bytearray, memoryview, np.bytes_)):
        return "raw"
    if isinstance(x, _dt.datetime):
        return "datetime"
    if isinstance(x, _dt.date):
        return "date"
    if isinstance(x, _dt.timedelta):
        return "timedelta"
    if isinstance(x, np.datetime64):
        return "datetime"
    if isinstance(x, np.timedelta64):
        return "timedelta"
    return "unknown"


# type promotion lattice for mixed lists -> atomic vector
_PROMOTION = ["null", "logical", "integer", "int64", "double", "complex", "character"]


def promote(types: list[str]) -> str | None:
    """Return a common atomic type for the given scalar types, or None."""
    ts = {t for t in types if t != "null"}
    if not ts:
        return "null"
    if len(ts) == 1:
        return ts.pop()
    if ts <= {"logical", "integer", "int64", "double", "complex"}:
        return max(ts, key=_PROMOTION.index)
    if ts <= {"integer", "double", "int64"}:
        return "double" if "double" in ts else "int64"
    return None  # heterogeneous -> list


def encode_scalar_value(x: Any, rtype: str, ctx: Context | None = None) -> Any:
    """Encode one Python value as the JSON payload element for ``rtype``."""
    if _is_missing(x):
        return "NA" if rtype == "double" else None
    if _is_nan(x):
        if rtype == "double":
            return "NaN"
        if rtype == "complex":
            return ["NaN", "NaN"]
        return None
    if isinstance(x, enum.Enum):
        x = x.value
    if rtype == "logical":
        return bool(x)
    if rtype == "integer":
        return int(x)
    if rtype == "int64":
        v = int(x)
        if ctx is not None and abs(v) >= FLOAT_EXACT_INT:
            ctx.plan.risk(f"integer {v} exceeds 2^53: transported as int64 string, needs bit64 in R")
        return str(v)
    if rtype == "double":
        return _encode_double(x)
    if rtype == "complex":
        c = complex(x)
        return [_encode_double(c.real), _encode_double(c.imag)]
    if rtype == "character":
        return str(x)
    if rtype == "raw":
        return base64.b64encode(bytes(x)).decode("ascii")
    if rtype == "decimal":
        return str(x)
    if rtype == "fraction":
        return f"{x.numerator}/{x.denominator}"
    if rtype == "uuid":
        return str(x)
    if rtype == "date":
        if isinstance(x, _dt.datetime):
            x = x.date()
        return x.isoformat()
    if rtype == "datetime":
        return encode_datetime(x)
    if rtype == "timedelta":
        return encode_timedelta(x)
    if rtype == "period":
        return str(x)
    raise TypeError(f"cannot encode {type(x).__name__} as {rtype}")


def encode_datetime(x: Any) -> str | None:
    """ISO-8601 with nanosecond precision when needed; offset kept if aware."""
    if _is_missing(x):
        return None
    if isinstance(x, np.datetime64):
        import pandas as pd
        x = pd.Timestamp(x)
    try:
        import pandas as pd
        if isinstance(x, pd.Timestamp):
            s = x.isoformat()
            return s
    except Exception:  # pragma: no cover
        pass
    if isinstance(x, _dt.datetime):
        return x.isoformat()
    if isinstance(x, _dt.date):
        return _dt.datetime(x.year, x.month, x.day).isoformat()
    raise TypeError(f"not a datetime: {x!r}")


def encode_timedelta(x: Any) -> float | None:
    if _is_missing(x):
        return None
    if isinstance(x, np.timedelta64):
        return float(x / np.timedelta64(1, "s"))
    try:
        import pandas as pd
        if isinstance(x, pd.Timedelta):
            return x.total_seconds()
    except Exception:  # pragma: no cover
        pass
    return x.total_seconds()


def decode_scalar_value(v: Any, rtype: str, tz: str | None = None) -> Any:
    if rtype == "double":
        return _decode_double(v)
    if v is None:
        return None
    if rtype == "logical":
        return bool(v)
    if rtype == "integer":
        return int(v)
    if rtype == "int64":
        return int(v)
    if rtype == "complex":
        re, im = _decode_double(v[0]), _decode_double(v[1])
        if re is None or im is None:
            return None
        return complex(re, im)
    if rtype == "character":
        return str(v)
    if rtype == "raw":
        return base64.b64decode(v)
    if rtype == "decimal":
        return decimal.Decimal(v)
    if rtype == "fraction":
        return fractions.Fraction(v)
    if rtype == "uuid":
        return uuid.UUID(v)
    if rtype == "date":
        return _dt.date.fromisoformat(v)
    if rtype == "datetime":
        return decode_datetime(v, tz)
    if rtype == "timedelta":
        return _dt.timedelta(seconds=float(v))
    if rtype == "period":
        import pandas as pd
        return pd.Period(v)
    return v


def decode_datetime(v: str | None, tz: str | None = None) -> Any:
    if v is None:
        return None
    import pandas as pd
    ts = pd.Timestamp(v)
    if tz and ts.tzinfo is None:
        ts = ts.tz_localize("UTC").tz_convert(tz) if tz != "naive" else ts
    elif tz and tz != "naive" and str(ts.tzinfo) != tz:
        try:
            ts = ts.tz_convert(tz)
        except Exception:  # pragma: no cover
            pass
    return ts


# --------------------------------------------------------------------------
# Vector-level helpers used by collections / tabular fallbacks
# --------------------------------------------------------------------------

_NP_KIND_TO_RTYPE = {"b": "logical", "i": "integer", "u": "integer", "f": "double",
                     "c": "complex", "U": "character", "S": "raw", "O": None,
                     "M": "datetime", "m": "timedelta"}


def numpy_rtype(arr: np.ndarray, ctx: Context | None = None) -> str:
    k = arr.dtype.kind
    if k in ("i", "u"):
        if arr.dtype.itemsize > 4 and arr.size and (arr.min() < INT32_MIN or arr.max() > INT32_MAX):
            if ctx is not None:
                ctx.plan.risk(f"{arr.dtype} values exceed R's 32-bit integer range; transported as int64")
            return "int64"
        if arr.dtype == np.uint32 and arr.size and arr.max() > INT32_MAX:
            return "int64"
        return "integer"
    if k == "O":
        types = [classify_scalar(v) for v in arr.ravel()]
        t = promote(types)
        return t or "character"
    r = _NP_KIND_TO_RTYPE.get(k)
    if r is None:
        raise TypeError(f"unsupported numpy dtype {arr.dtype}")
    return r


def encode_values(values: Any, rtype: str, ctx: Context | None = None) -> list[Any]:
    arr = np.asarray(values) if not isinstance(values, np.ndarray) else values
    flat = arr.ravel(order="K") if arr.ndim else arr.reshape(-1)
    if rtype == "double" and arr.dtype.kind == "f":
        out: list[Any] = flat.tolist()
        nan_mask = np.isnan(flat)
        if nan_mask.any() or np.isinf(flat).any():
            out = [_encode_double(v) for v in flat.tolist()]
        return out
    if rtype == "integer" and arr.dtype.kind in "iu":
        return flat.tolist()
    if rtype == "logical" and arr.dtype.kind == "b":
        return flat.tolist()
    if rtype == "datetime" and arr.dtype.kind == "M":
        import pandas as pd
        return [None if pd.isna(t) else pd.Timestamp(t).isoformat() for t in flat]
    if rtype == "timedelta" and arr.dtype.kind == "m":
        return [None if np.isnat(t) else float(t / np.timedelta64(1, "s")) for t in flat]
    return [encode_scalar_value(v, rtype, ctx) for v in flat.tolist()]


def decode_values(values: list[Any], rtype: str, tz: str | None = None,
                  ctx: Context | None = None) -> Any:
    """Decode a JSON list into the most natural Python container.

    Returns a numpy array, a pandas extension array (when R ``NA`` must be
    preserved distinctly from ``NaN``), or a list for object types.
    """
    import pandas as pd
    if rtype == "double":
        has_na = any(v == "NA" or v is None for v in values)
        has_nan = any(v == "NaN" for v in values)
        floats = [math.nan if (v == "NA" or v is None) else _decode_double(v) for v in values]
        if has_na and has_nan and (ctx is None or ctx.config.missing == "preserve"):
            # both R NA and NaN present: FloatingArray keeps them distinct (pd.array() would not)
            mask = np.array([v == "NA" or v is None for v in values], dtype=bool)
            if ctx is not None:
                ctx.plan.note("R NA and NaN both present -> pandas Float64 array keeps them distinct")
            return pd.arrays.FloatingArray(np.asarray(floats, dtype=float), mask)
        return np.asarray(floats, dtype=float)   # NA-only -> NaN (numpy-native), documented policy
    if rtype == "integer":
        # R integer is 32-bit; pandas/numpy default is int64 -> use the native default
        if any(v is None for v in values):
            return pd.array(values, dtype="Int64")
        return np.asarray(values, dtype=np.int64)
    if rtype == "int64":
        ints = [None if v is None else int(v) for v in values]
        if any(v is None for v in ints):
            return pd.array(ints, dtype="Int64")
        return np.asarray(ints, dtype=np.int64)
    if rtype == "logical":
        if any(v is None for v in values):
            return pd.array(values, dtype="boolean")
        return np.asarray(values, dtype=bool)
    if rtype == "character":
        return np.asarray(values, dtype=object)
    if rtype == "datetime":
        stamps = [decode_datetime(v, tz) for v in values]
        return pd.DatetimeIndex(stamps).to_numpy() if tz in (None, "naive") else pd.DatetimeIndex(stamps)
    if rtype == "date":
        return np.asarray([None if v is None else _dt.date.fromisoformat(v) for v in values], dtype=object)
    if rtype == "timedelta":
        return pd.to_timedelta([None if v is None else float(v) for v in values], unit="s").to_numpy()
    if rtype == "complex":
        out = [decode_scalar_value(v, "complex") for v in values]
        if any(v is None for v in out):
            return np.asarray([complex(math.nan, math.nan) if v is None else v for v in out])
        return np.asarray(out, dtype=complex)
    return [decode_scalar_value(v, rtype, tz) for v in values]


# --------------------------------------------------------------------------
# Adapter
# --------------------------------------------------------------------------

_SCALAR_TYPES = (type(None), bool, int, float, complex, str, bytes, bytearray, memoryview,
                 decimal.Decimal, fractions.Fraction, uuid.UUID, _dt.date, _dt.datetime,
                 _dt.timedelta, enum.Enum, np.generic)


class ScalarAdapter(Adapter):
    family = "scalar"
    kinds = ("vector", "null")
    tier = ConversionPath.NATIVE
    priority = 50

    def detect(self, obj: Any) -> Detection | None:
        try:
            import pandas as pd
            if obj is pd.NA or obj is pd.NaT or isinstance(obj, (pd.Timestamp, pd.Timedelta, pd.Period)):
                return Detection("scalar", Confidence.CONFIRMED, type(obj).__name__)
        except Exception:  # pragma: no cover
            pass
        if isinstance(obj, np.ndarray):
            return None
        if isinstance(obj, _SCALAR_TYPES):
            return Detection("scalar", Confidence.CONFIRMED, type(obj).__name__)
        return None

    def encode(self, obj: Any, ctx: Context) -> dict[str, Any]:
        rtype = classify_scalar(obj)
        if rtype == "null":
            ctx.record("scalar", ConversionPath.NATIVE, "json", "NULL")
            return {"rpx": 1, "kind": "null"}
        meta: dict[str, Any] = {}
        if isinstance(obj, enum.Enum):
            meta["enum"] = f"{type(obj).__module__}.{type(obj).__qualname__}"
            meta["enum_name"] = obj.name
        if rtype == "datetime":
            meta["tz"] = _tz_of(obj)
        if rtype == "decimal":
            meta["precision_note"] = "exact decimal string; R keeps class 'rpx_decimal'"
        val = encode_scalar_value(obj, rtype, ctx)
        ctx.record("scalar", ConversionPath.NATIVE, "json", rtype)
        ctx.plan.fidelity.set("values", Fidelity.LOSSLESS)
        ctx.plan.fidelity.set("types", Fidelity.LOSSLESS if rtype not in ("int64", "decimal", "fraction", "uuid")
                              else Fidelity.CHANGED, "" if rtype not in ("int64", "decimal", "fraction", "uuid")
                              else f"R has no native {rtype}; encoded representation with class marker")
        return {"rpx": 1, "kind": "vector", "type": rtype, "values": [val], "names": None,
                "scalar": True, "meta": meta}

    def decode(self, env: dict[str, Any], ctx: Context) -> Any:
        if env.get("kind") == "null":
            return None
        rtype = env["type"]
        values = env.get("values", [])
        names = env.get("names")
        meta = env.get("meta") or {}
        tz = meta.get("tz")
        if env.get("scalar") or (len(values) == 1 and not names and env.get("scalar", None) is not False):
            v = decode_scalar_value(values[0], rtype, tz)
            if meta.get("enum"):
                v = _restore_enum(meta["enum"], meta.get("enum_name"), v)
            src = meta.get("source_class", "")
            if rtype == "datetime" and v is not None and not src.endswith("Timestamp"):
                v = v.to_pydatetime() if hasattr(v, "to_pydatetime") else v
            if rtype == "timedelta" and src.endswith("Timedelta") and v is not None:
                import pandas as pd
                v = pd.Timedelta(v)
            return v
        arr = decode_values(values, rtype, tz, ctx)
        if meta.get("container") and meta["container"] not in ("dict", "OrderedDict", "defaultdict"):
            from .collections import restore_container
            return restore_container(arr, meta)
        if names:
            if meta.get("container") in ("dict", "OrderedDict", "defaultdict"):
                from .collections import restore_container
                return dict(zip(names, restore_container(arr, {"container": "list"})))
            import pandas as pd
            return pd.Series(arr, index=list(names))
        return arr


def _tz_of(x: Any) -> str | None:
    tzinfo = getattr(x, "tzinfo", None)
    if tzinfo is None:
        return "naive"
    try:
        import pandas as pd
        return str(pd.Timestamp(x).tz)
    except Exception:  # pragma: no cover
        return str(tzinfo)


def _restore_enum(path: str, name: str | None, value: Any) -> Any:
    import importlib
    try:
        mod, _, qual = path.rpartition(".")
        cls: Any = importlib.import_module(mod)
        for part in qual.split("."):
            cls = getattr(cls, part)
        return cls[name] if name else cls(value)
    except Exception:
        return value


REGISTRY.register(ScalarAdapter(), tested=True)
