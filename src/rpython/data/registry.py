"""Universal semantic registry (sections 55, 57, 71).

Adapters are ordered by *tier* (the conversion priority hierarchy) and
then by priority.  The registry is an optimisation, **not a whitelist**:
when no adapter matches, the conversion layer falls back to safe
recursive conversion and finally to a native proxy.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from .semantic import ConversionPath, Detection, Confidence

TIER_ORDER: dict[ConversionPath, int] = {
    ConversionPath.NATIVE: 0,
    ConversionPath.STANDARD: 1,
    ConversionPath.ADAPTER: 2,
    ConversionPath.LAZY: 3,
    ConversionPath.PROXY: 4,
    ConversionPath.LOSSY: 5,
}


class Adapter:
    """Base class for all object-family adapters.

    Subclasses implement :meth:`detect`, :meth:`encode` and :meth:`decode`.
    ``kinds`` lists the envelope kinds the adapter can decode.
    """

    family: str = "unknown"
    kinds: tuple[str, ...] = ()
    tier: ConversionPath = ConversionPath.ADAPTER
    priority: int = 100
    #: optional Python packages required (used for install hints)
    requires: tuple[str, ...] = ()
    #: R packages required on the other side
    r_requires: tuple[str, ...] = ()

    def detect(self, obj: Any) -> Detection | None:  # pragma: no cover - abstract
        raise NotImplementedError

    def encode(self, obj: Any, ctx: "Context") -> dict[str, Any]:  # pragma: no cover
        raise NotImplementedError

    def decode(self, env: dict[str, Any], ctx: "Context") -> Any:  # pragma: no cover
        raise NotImplementedError

    def available(self) -> bool:
        import importlib.util
        return all(importlib.util.find_spec(p.split(".")[0]) is not None for p in self.requires)

    def __repr__(self) -> str:
        return f"<{type(self).__name__} family={self.family!r} tier={self.tier.name} priority={self.priority}>"


@dataclass
class RegistryEntry:
    adapter: Adapter
    #: known limitations, shown in explain mode / catalog
    limitations: tuple[str, ...] = ()
    #: whether round-trip fidelity tests exist for this entry
    tested: bool = False


@dataclass
class Registry:
    _entries: list[RegistryEntry] = field(default_factory=list)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def register(self, adapter: Adapter, *, limitations: Iterable[str] = (), tested: bool = False) -> Adapter:
        with self._lock:
            # replace an adapter of the same class if re-registered
            self._entries = [e for e in self._entries if type(e.adapter) is not type(adapter)]
            self._entries.append(RegistryEntry(adapter, tuple(limitations), tested))
            # detection order == specificity (priority); the tier is descriptive
            self._entries.sort(key=lambda e: (e.adapter.priority, TIER_ORDER[e.adapter.tier]))
        return adapter

    def unregister(self, adapter_type: type) -> None:
        with self._lock:
            self._entries = [e for e in self._entries if type(e.adapter) is not adapter_type]

    @property
    def adapters(self) -> list[Adapter]:
        return [e.adapter for e in self._entries]

    def entries(self) -> list[RegistryEntry]:
        return list(self._entries)

    def detect(self, obj: Any) -> tuple[Adapter, Detection] | None:
        """Return the first adapter whose detector recognises ``obj``."""
        for e in self._entries:
            ad = e.adapter
            if not ad.available():
                continue
            try:
                det = ad.detect(obj)
            except Exception:  # detection must never crash conversion
                det = None
            if det is not None and det.confidence in (Confidence.CONFIRMED, Confidence.INFERRED):
                return ad, det
        return None

    def suggestions(self, obj: Any) -> list[Detection]:
        """Ambiguous detections -- surfaced as suggestions only."""
        out = []
        for e in self._entries:
            if not e.adapter.available():
                continue
            try:
                det = e.adapter.detect(obj)
            except Exception:
                det = None
            if det is not None and det.confidence is Confidence.AMBIGUOUS:
                out.append(det)
        return out

    def decoder_for(self, kind: str) -> Adapter | None:
        for e in self._entries:
            if kind in e.adapter.kinds and e.adapter.available():
                return e.adapter
        return None

    def missing_dependency_for(self, kind: str) -> str | None:
        for e in self._entries:
            if kind in e.adapter.kinds and not e.adapter.available():
                return ", ".join(e.adapter.requires)
        return None


REGISTRY = Registry()


# --------------------------------------------------------------------------
# Public extension API (section 55)
# --------------------------------------------------------------------------

class _FunctionAdapter(Adapter):
    def __init__(self, family: str, kind: str, detector: Callable[[Any], bool],
                 encoder: Callable[[Any, "Context"], dict[str, Any]],
                 decoder: Callable[[dict[str, Any], "Context"], Any] | None,
                 tier: ConversionPath, priority: int, requires: tuple[str, ...]):
        self.family = family
        self.kinds = (kind,)
        self._detector = detector
        self._encoder = encoder
        self._decoder = decoder
        self.tier = tier
        self.priority = priority
        self.requires = requires

    def detect(self, obj: Any) -> Detection | None:
        if self._detector(obj):
            return Detection(self.family, Confidence.CONFIRMED, f"custom converter {self.kinds[0]}")
        return None

    def encode(self, obj: Any, ctx: "Context") -> dict[str, Any]:
        env = self._encoder(obj, ctx)
        env.setdefault("rpx", 1)
        env.setdefault("kind", self.kinds[0])
        return env

    def decode(self, env: dict[str, Any], ctx: "Context") -> Any:
        if self._decoder is None:
            raise NotImplementedError(f"no decoder registered for kind {self.kinds[0]!r}")
        return self._decoder(env, ctx)


def register_converter(*, family: str, kind: str, detect: Callable[[Any], bool],
                       encode: Callable[[Any, "Context"], dict[str, Any]],
                       decode: Callable[[dict[str, Any], "Context"], Any] | None = None,
                       priority: int = 50, requires: tuple[str, ...] = ()) -> Adapter:
    """Register an exact optimised converter for a custom class.

    ``kind`` must be unique; the R companion must know how to decode it
    (see ``rpython::rpx_register_decoder``) or it will land as a proxy.
    """
    ad = _FunctionAdapter(family, kind, detect, encode, decode, ConversionPath.NATIVE, priority, requires)
    return REGISTRY.register(ad)


def register_semantic_adapter(*, family: str, kind: str, detect: Callable[[Any], bool],
                              encode: Callable[[Any, "Context"], dict[str, Any]],
                              decode: Callable[[dict[str, Any], "Context"], Any] | None = None,
                              priority: int = 50, requires: tuple[str, ...] = ()) -> Adapter:
    """Register a metadata-preserving adapter (tier C)."""
    ad = _FunctionAdapter(family, kind, detect, encode, decode, ConversionPath.ADAPTER, priority, requires)
    return REGISTRY.register(ad)


def register_proxy_adapter(*, family: str, detect: Callable[[Any], bool], priority: int = 50) -> Adapter:
    """Force objects matching ``detect`` to always stay native behind a proxy."""
    from .custom import proxy_encode  # local import to avoid cycles
    ad = _FunctionAdapter(family, "proxy", detect, proxy_encode, None, ConversionPath.PROXY, priority, ())
    return REGISTRY.register(ad)


# late import for type checkers only
from .context import Context  # noqa: E402  (circular-safe: context has no registry import)
