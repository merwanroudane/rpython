"""Conversion dispatcher: Python object <-> portable envelope.

Priority hierarchy (section 57)::

    1. exact optimized adapter          (registry, tier A)
    2. standard language-neutral path   (tier B, e.g. Arrow / WKB / DLPack)
    3. generic semantic adapter         (tier C)
    4. safe recursive conversion        (collections)
    5. native proxy                     (custom.ProxyAdapter, always last)
    6. explicit error with solution     (only when even a proxy is impossible)
"""
from __future__ import annotations

from typing import Any

from .context import Context, ConversionError
from .registry import REGISTRY
from .semantic import ConversionPath, Fidelity, Runtime

# Ensure built-in adapters are registered (import order == registration).
from . import primitives, collections as _collections  # noqa: F401,E402


def _load_builtin_adapters() -> None:
    # Lazy: heavy optional families register on first use.
    import importlib
    for mod in ("arrays", "sparse", "tabular", "temporal", "panel", "survey", "survival",
                "spatial", "raster", "spatiotemporal", "network", "text", "media",
                "scientific", "economics", "custom"):
        importlib.import_module(f"rpython.data.{mod}")


_LOADED = False


def ensure_adapters() -> None:
    global _LOADED
    if not _LOADED:
        _LOADED = True
        _load_builtin_adapters()


def to_envelope(obj: Any, ctx: Context | None = None) -> dict[str, Any]:
    """Encode any Python object into a portable envelope."""
    ensure_adapters()
    ctx = ctx or Context()
    top = not ctx.plan.source
    if top:
        ctx.plan.source = f"{type(obj).__module__}.{type(obj).__qualname__}".replace("builtins.", "")
        ctx.plan.target = "R" if ctx.target_runtime is Runtime.R else "Python"
    found = REGISTRY.detect(obj)
    if found is None:
        # Should not happen: ProxyAdapter detects everything. Defensive error.
        raise ConversionError(f"No adapter for {type(obj).__name__}", cause="registry empty",
                              fix="rp.register_converter(...) or report a bug")
    adapter, det = found
    if top:
        ctx.plan.family = adapter.family
        ctx.plan.detection = det.describe()
        for s in REGISTRY.suggestions(obj):
            ctx.plan.note(s.describe())
    env = adapter.encode(obj, ctx)
    env.setdefault("rpx", 1)
    if "meta" in env and isinstance(env["meta"], dict):
        env["meta"].setdefault("source_class", f"{type(obj).__module__}.{type(obj).__qualname__}".replace("builtins.", ""))
    return env


def from_envelope(env: Any, ctx: Context | None = None) -> Any:
    """Decode a portable envelope into the most natural Python object."""
    ensure_adapters()
    ctx = ctx or Context(direction="r->py", target_runtime=Runtime.PYTHON)
    if not isinstance(env, dict) or "kind" not in env:
        # tolerate raw JSON values produced by simple R paths
        return env
    kind = env["kind"]
    adapter = REGISTRY.decoder_for(kind)
    if adapter is None:
        missing = REGISTRY.missing_dependency_for(kind)
        if missing:
            raise ConversionError(
                f"Cannot decode R object family {kind!r}: optional dependency missing",
                cause=f"requires Python package(s): {missing}",
                fix=f"pip install {missing}   (or pip install 'rpython[all]')",
            )
        # Unknown kind: keep the raw envelope so nothing is destroyed.
        ctx.warn(f"unknown envelope kind {kind!r}; returned as RawEnvelope")
        return RawEnvelope(env)
    if not ctx.plan.source:
        ctx.plan.family = adapter.family
        ctx.plan.source = f"R {env.get('meta', {}).get('source_class', kind)}" if isinstance(env.get("meta"), dict) else f"R {kind}"
        ctx.plan.target = "Python"
    ctx.depth += 1
    try:
        return adapter.decode(env, ctx)
    finally:
        ctx.depth -= 1


class RawEnvelope(dict):
    """An envelope RPython could not decode; nothing was lost, nothing was guessed."""

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<RawEnvelope kind={self.get('kind')!r}>"


def roundtrip(obj: Any, ctx: Context | None = None) -> tuple[Any, Context]:
    """Python -> envelope -> Python (used by the fidelity engine and tests)."""
    import json
    ctx = ctx or Context(direction="py->py", target_runtime=Runtime.PYTHON)
    env = to_envelope(obj, ctx)
    # force JSON serialisability exactly as the wire would
    env2 = json.loads(json.dumps(env, ensure_ascii=False, default=_json_default))
    back = from_envelope(env2, ctx)
    return back, ctx


def _json_default(o: Any) -> Any:
    import numpy as np
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, bytes):
        import base64
        return base64.b64encode(o).decode("ascii")
    raise TypeError(f"not JSON serialisable: {type(o).__name__}")


def envelope_size(env: dict[str, Any]) -> int:
    import json
    try:
        return len(json.dumps(env, default=_json_default))
    except Exception:
        return 0
