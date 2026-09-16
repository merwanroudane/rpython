"""Custom classes, safe introspection and the universal proxy fallback
(sections 55-57).

The :class:`ProxyAdapter` is registered at the PROXY tier and matches
*every* object, so conversion never jumps from "no adapter" straight to
failure.  The object stays alive in the Python object store; R receives
an ``rpx_pyproxy`` handle and can call methods on it through the
callback channel of the worker protocol.
"""
from __future__ import annotations

import inspect
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

from .context import Context
from .registry import Adapter, REGISTRY
from .semantic import Confidence, ConversionPath, Detection, Fidelity


# --------------------------------------------------------------------------
# Object store (Python-side handles for proxies exposed to R)
# --------------------------------------------------------------------------

class ObjectStore:
    def __init__(self) -> None:
        self._objects: dict[str, Any] = {}
        self._lock = threading.Lock()

    def put(self, obj: Any) -> str:
        handle = f"py_{uuid.uuid4().hex[:12]}"
        with self._lock:
            self._objects[handle] = obj
        return handle

    def get(self, handle: str) -> Any:
        with self._lock:
            if handle not in self._objects:
                raise KeyError(f"unknown Python proxy handle {handle!r} (object released?)")
            return self._objects[handle]

    def release(self, handle: str) -> None:
        with self._lock:
            self._objects.pop(handle, None)

    def __len__(self) -> int:
        return len(self._objects)

    def clear(self) -> None:
        with self._lock:
            self._objects.clear()


OBJECT_STORE = ObjectStore()


# --------------------------------------------------------------------------
# Safe introspection (section 56)
# --------------------------------------------------------------------------

@dataclass
class Introspection:
    type_name: str
    module: str
    mro: list[str] = field(default_factory=list)
    protocols: list[str] = field(default_factory=list)
    fields: list[str] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)
    attributes: list[str] = field(default_factory=list)
    properties: list[str] = field(default_factory=list)   # NOT evaluated
    doc: str = ""

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


_PROTOCOLS = {
    "__dataframe__": "dataframe-interchange",
    "__array__": "numpy-array",
    "__array_interface__": "numpy-array-interface",
    "__arrow_c_array__": "arrow-c-data",
    "__arrow_c_stream__": "arrow-c-stream",
    "__dlpack__": "dlpack",
    "__geo_interface__": "geo-interface",
    "__iter__": "iterable",
    "__len__": "sized",
    "__getitem__": "indexable",
    "__call__": "callable",
}


def introspect(obj: Any) -> Introspection:
    """Inspect an object *without* triggering properties or side effects."""
    t = type(obj)
    info = Introspection(type_name=t.__qualname__, module=t.__module__,
                         mro=[f"{c.__module__}.{c.__qualname__}" for c in t.__mro__[:-1]],
                         doc=(inspect.getdoc(t) or "").splitlines()[0] if inspect.getdoc(t) else "")
    for dunder, name in _PROTOCOLS.items():
        if hasattr(t, dunder):
            info.protocols.append(name)
    try:
        import dataclasses
        if dataclasses.is_dataclass(obj):
            info.fields = [f.name for f in dataclasses.fields(obj)]
    except Exception:  # pragma: no cover
        pass
    for name in dir(t):
        if name.startswith("_"):
            continue
        try:
            attr = inspect.getattr_static(t, name)
        except Exception:
            continue
        if isinstance(attr, property):
            info.properties.append(name)
        elif callable(attr) or isinstance(attr, (staticmethod, classmethod)):
            info.methods.append(name)
        else:
            info.attributes.append(name)
    inst = getattr(obj, "__dict__", None)
    if isinstance(inst, dict):
        info.attributes.extend(k for k in inst if not k.startswith("_") and k not in info.attributes)
    return info


# --------------------------------------------------------------------------
# Proxy envelope
# --------------------------------------------------------------------------

def proxy_encode(obj: Any, ctx: Context) -> dict[str, Any]:
    handle = OBJECT_STORE.put(obj)
    info = introspect(obj)
    try:
        text = repr(obj)
        if len(text) > 500:
            text = text[:500] + "..."
    except Exception:
        text = f"<{info.type_name}>"
    ctx.record("proxy", ConversionPath.PROXY, "object-store",
               f"{info.module}.{info.type_name} kept alive in Python; R receives a handle")
    ctx.plan.fidelity.set("values", Fidelity.PROXY, "object stays in Python")
    ctx.plan.fidelity.set("semantics", Fidelity.PROXY)
    ctx.plan.note(f"No native or standard R representation for {info.module}.{info.type_name}; "
                  "a native-object proxy preserves it. Methods run in Python.")
    return {
        "rpx": 1, "kind": "proxy", "runtime": "python", "handle": handle, "callable": callable(obj),
        "class": [info.type_name], "module": info.module, "mro": info.mro,
        "protocols": info.protocols, "methods": info.methods,
        "attributes": info.attributes, "properties": info.properties,
        "repr": text, "meta": {"source_class": f"{info.module}.{info.type_name}"},
    }


class ProxyAdapter(Adapter):
    """Last-resort adapter: matches everything."""

    family = "proxy"
    kinds = ("proxy",)
    tier = ConversionPath.PROXY
    priority = 10_000

    def detect(self, obj: Any) -> Detection | None:
        return Detection("native object (proxy)", Confidence.CONFIRMED,
                         f"{type(obj).__module__}.{type(obj).__qualname__}")

    def encode(self, obj: Any, ctx: Context) -> dict[str, Any]:
        return proxy_encode(obj, ctx)

    def decode(self, env: dict[str, Any], ctx: Context) -> Any:
        if env.get("runtime") == "python":
            # Round trip of a Python proxy: return the original object.
            return OBJECT_STORE.get(env["handle"])
        from ..proxy.r_object import RObjectProxy
        ctx.record("proxy", ConversionPath.PROXY, "r-session",
                   f"R object of class {env.get('class')} kept alive in R")
        ctx.plan.fidelity.set("values", Fidelity.PROXY, "object stays in R")
        return RObjectProxy(env, session=ctx.session)


REGISTRY.register(ProxyAdapter(), tested=True)
