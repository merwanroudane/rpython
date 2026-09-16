"""Basic containers (section 5): list, tuple, namedtuple, dict, OrderedDict,
defaultdict, set, frozenset, dataclass, attrs, pydantic.

Two envelope shapes are produced:

* homogeneous scalar sequences -> ``kind: "vector"`` (R atomic vector) with
  ``meta.container`` recording the original Python container so the round
  trip restores ``list`` / ``tuple`` / ``set``;
* everything else -> ``kind: "list"`` with recursively encoded ``items``
  and optional ``names``.

Cycles are detected and replaced by ``kind: "ref"`` markers.
"""
from __future__ import annotations

import collections
import dataclasses
import importlib
from typing import Any

from .context import Context
from .primitives import classify_scalar, encode_scalar_value, promote, decode_values, _tz_of
from .registry import Adapter, REGISTRY
from .semantic import Confidence, ConversionPath, Detection, Fidelity


def _is_namedtuple(obj: Any) -> bool:
    return isinstance(obj, tuple) and hasattr(obj, "_fields")


def _is_attrs(obj: Any) -> bool:
    return hasattr(type(obj), "__attrs_attrs__")


def _is_pydantic(obj: Any) -> bool:
    return hasattr(obj, "model_dump") and hasattr(type(obj), "model_fields")


def _qualname(obj: Any) -> str:
    t = type(obj)
    return f"{t.__module__}.{t.__qualname__}"


class CollectionAdapter(Adapter):
    family = "collection"
    kinds = ("list", "ref")
    tier = ConversionPath.NATIVE
    priority = 60

    def detect(self, obj: Any) -> Detection | None:
        if isinstance(obj, (list, tuple, set, frozenset, dict)):
            return Detection("collection", Confidence.CONFIRMED, type(obj).__name__)
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            return Detection("collection", Confidence.CONFIRMED, "dataclass")
        if _is_attrs(obj):
            return Detection("collection", Confidence.CONFIRMED, "attrs")
        if _is_pydantic(obj):
            return Detection("collection", Confidence.CONFIRMED, "pydantic")
        return None

    # ------------------------------------------------------------------ encode
    def encode(self, obj: Any, ctx: Context) -> dict[str, Any]:
        from .convert import to_envelope
        ref = ctx.enter(obj)
        if ref is not None:
            ctx.warn("self-referential structure: cycle replaced by reference marker")
            return {"rpx": 1, "kind": "ref", "ref": ref}
        try:
            return self._encode(obj, ctx, to_envelope)
        finally:
            ctx.leave(obj)

    def _encode(self, obj: Any, ctx: Context, to_envelope: Any) -> dict[str, Any]:
        container = type(obj).__name__
        meta: dict[str, Any] = {"container": container, "class": _qualname(obj)}
        names: list[str] | None = None
        keys_env: list[dict[str, Any]] | None = None

        if _is_namedtuple(obj):
            meta["container"] = "namedtuple"
            names = list(obj._fields)
            items = list(obj)
        elif dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            meta["container"] = "dataclass"
            names = [f.name for f in dataclasses.fields(obj)]
            items = [getattr(obj, n) for n in names]
        elif _is_attrs(obj):
            meta["container"] = "attrs"
            names = [a.name for a in type(obj).__attrs_attrs__]
            items = [getattr(obj, n) for n in names]
        elif _is_pydantic(obj):
            meta["container"] = "pydantic"
            names = list(type(obj).model_fields)
            items = [getattr(obj, n) for n in names]
        elif isinstance(obj, dict):
            meta["container"] = "dict" if not isinstance(obj, collections.OrderedDict) else "OrderedDict"
            if isinstance(obj, collections.defaultdict):
                meta["container"] = "defaultdict"
            keys = list(obj.keys())
            items = list(obj.values())
            if all(isinstance(k, str) for k in keys):
                names = keys
            else:
                names = [str(k) for k in keys]
                keys_env = [to_envelope(k, ctx) for k in keys]
                meta["key_types"] = "encoded"
        elif isinstance(obj, (set, frozenset)):
            items = sorted(obj, key=repr)
        else:
            items = list(obj)

        # homogeneous scalar sequence -> atomic vector
        if names is None or meta["container"] in ("namedtuple", "dict", "OrderedDict", "defaultdict"):
            types = [classify_scalar(v) for v in items]
            rtype = promote(types) if all(t != "unknown" for t in types) else None
            if rtype is not None and rtype != "null" and rtype not in ("period",) and (
                names is None or meta["container"] == "dict" and keys_env is None):
                vals = [encode_scalar_value(v, rtype, ctx) for v in items]
                if rtype == "datetime":
                    tzs = {_tz_of(v) for v in items if v is not None}
                    meta["tz"] = tzs.pop() if len(tzs) == 1 else "mixed"
                    if meta["tz"] == "mixed":
                        ctx.lossy("datetime list", "mixed timezones in one vector")
                ctx.record("collection", ConversionPath.NATIVE, "json", f"{container} -> atomic {rtype}")
                ctx.plan.fidelity.set("values", Fidelity.LOSSLESS)
                ctx.plan.fidelity.set("types", Fidelity.LOSSLESS, "container restored from metadata")
                return {"rpx": 1, "kind": "vector", "type": rtype, "values": vals,
                        "names": names, "scalar": False, "meta": meta}

        env_items = [to_envelope(v, ctx) for v in items]
        out: dict[str, Any] = {"rpx": 1, "kind": "list", "items": env_items, "names": names, "meta": meta}
        if keys_env is not None:
            out["keys"] = keys_env
        ctx.record("collection", ConversionPath.NATIVE, "json", f"{container} -> R list")
        ctx.plan.fidelity.set("values", Fidelity.LOSSLESS)
        ctx.plan.fidelity.set("names", Fidelity.LOSSLESS)
        return out

    # ------------------------------------------------------------------ decode
    def decode(self, env: dict[str, Any], ctx: Context) -> Any:
        from .convert import from_envelope
        if env.get("kind") == "ref":
            return CycleRef(env["ref"])
        items = [from_envelope(e, ctx) for e in env.get("items", [])]
        names = env.get("names")
        meta = env.get("meta") or {}
        container = meta.get("container")
        if env.get("keys"):
            keys = [from_envelope(k, ctx) for k in env["keys"]]
            return dict(zip(keys, items))
        if container == "namedtuple" and names:
            return _rebuild_namedtuple(meta.get("class"), names, items)
        if container in ("dataclass", "attrs", "pydantic") and names:
            return _rebuild_class(meta.get("class"), names, items)
        if container == "tuple":
            return tuple(items)
        if container in ("set", "frozenset"):
            try:
                return (frozenset if container == "frozenset" else set)(items)
            except TypeError:
                return items
        if container in ("dict", "OrderedDict", "defaultdict") and not items:
            return collections.OrderedDict() if container == "OrderedDict" else {}
        if names and all(names) and len(set(names)) == len(names):
            if container == "OrderedDict":
                return collections.OrderedDict(zip(names, items))
            if container == "defaultdict":
                d: Any = collections.defaultdict(None)
                d.update(zip(names, items))
                return d
            return dict(zip(names, items))
        if names and any(names):
            # duplicate / partial names: R semantics -> keep as list of pairs
            return [(n, v) for n, v in zip(names, items)]
        return items


class CycleRef:
    """Marker returned in place of a cyclic reference."""

    def __init__(self, ref: str):
        self.ref = ref

    def __repr__(self) -> str:
        return f"<CycleRef {self.ref}>"


def _load_class(path: str | None) -> type | None:
    if not path:
        return None
    try:
        mod, _, qual = path.rpartition(".")
        cls: Any = importlib.import_module(mod)
        for part in qual.split("."):
            cls = getattr(cls, part)
        return cls
    except Exception:
        return None


def _rebuild_namedtuple(path: str | None, names: list[str], items: list[Any]) -> Any:
    cls = _load_class(path)
    if cls is not None:
        try:
            return cls(*items)
        except Exception:
            pass
    return collections.namedtuple("RPythonTuple", names)(*items)


def _rebuild_class(path: str | None, names: list[str], items: list[Any]) -> Any:
    cls = _load_class(path)
    if cls is not None:
        try:
            return cls(**dict(zip(names, items)))
        except Exception:
            pass
    return dict(zip(names, items))


def restore_container(values: Any, meta: dict[str, Any]) -> Any:
    """Restore list/tuple/set from a decoded atomic vector using metadata."""
    container = meta.get("container")
    if container is None:
        return values
    seq = list(values.tolist() if hasattr(values, "tolist") else values)
    seq = [None if _isna(v) else v for v in seq]
    if container == "tuple":
        return tuple(seq)
    if container == "set":
        return set(seq)
    if container == "frozenset":
        return frozenset(seq)
    if container == "namedtuple":
        return seq
    return seq


def _isna(v: Any) -> bool:
    try:
        import pandas as pd
        return v is pd.NA
    except Exception:  # pragma: no cover
        return False


REGISTRY.register(CollectionAdapter(), tested=True)
