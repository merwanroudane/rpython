"""Lazy / distributed / streaming objects (sections 44-45).

``rp.lazy(obj)`` wraps a polars ``LazyFrame``, a Dask collection, an
Arrow dataset/scanner, a DuckDB relation or any iterator/generator so
that it is **never materialised** for transfer.  What crosses the
boundary is a description (query plan / SQL / file list / schema) plus a
proxy handle; the other runtime can pull record batches on demand.

Streaming: ``rp.stream(iterable, batch_size=...)`` exposes an iterator of
Arrow record batches / DataFrames that R can consume chunk by chunk via
``py$next_batch()``.
"""
from __future__ import annotations

from typing import Any, Iterable, Iterator

from .context import Context
from .registry import Adapter, REGISTRY
from .semantic import Confidence, ConversionPath, Detection, Fidelity


class Lazy:
    def __init__(self, obj: Any):
        self.obj = obj

    def describe(self) -> dict[str, Any]:
        o = self.obj
        mod = type(o).__module__
        d: dict[str, Any] = {"class": f"{mod}.{type(o).__name__}"}
        try:
            if mod.startswith("polars"):
                d["plan"] = o.explain() if hasattr(o, "explain") else None
                d["columns"] = list(o.collect_schema().names()) if hasattr(o, "collect_schema") else None
            elif mod.startswith("dask"):
                d["npartitions"] = getattr(o, "npartitions", None)
                d["columns"] = list(getattr(o, "columns", []))
            elif mod.startswith("pyarrow"):
                d["schema"] = str(getattr(o, "schema", ""))
                d["files"] = list(getattr(o, "files", []) or [])
            elif mod.startswith("duckdb"):
                d["sql"] = getattr(o, "sql_query", lambda: None)()
                d["columns"] = list(getattr(o, "columns", []))
        except Exception as e:  # description must never fail
            d["error"] = str(e)
        return d

    def __repr__(self) -> str:
        return f"<Lazy {self.describe().get('class')}>"


class Stream:
    """Chunked iterable of tables; consumed batch by batch (never all at once)."""

    def __init__(self, source: Iterable[Any], batch_size: int = 10_000):
        self.source, self.batch_size = source, batch_size
        self._it: Iterator[Any] | None = None

    def __iter__(self) -> Iterator[Any]:
        import pandas as pd
        buf: list[Any] = []
        for rec in self.source:
            if isinstance(rec, pd.DataFrame):
                yield rec
                continue
            buf.append(rec)
            if len(buf) >= self.batch_size:
                yield pd.DataFrame(buf)
                buf = []
        if buf:
            yield pd.DataFrame(buf)

    def next_batch(self) -> Any:
        if self._it is None:
            self._it = iter(self)
        try:
            return next(self._it)
        except StopIteration:
            return None

    def __repr__(self) -> str:
        return f"<Stream batch_size={self.batch_size}>"


def stream(source: Iterable[Any], batch_size: int = 10_000) -> Stream:
    return Stream(source, batch_size)


class LazyAdapter(Adapter):
    family = "lazy"
    kinds = ("lazy",)
    tier = ConversionPath.LAZY
    priority = 4

    def detect(self, obj: Any) -> Detection | None:
        if isinstance(obj, (Lazy, Stream)):
            return Detection("lazy / streaming object", Confidence.CONFIRMED, type(obj).__name__)
        import types
        if isinstance(obj, (types.GeneratorType, Iterator)) and not isinstance(obj, (list, tuple, dict, str, bytes)):
            return Detection("iterator / generator", Confidence.CONFIRMED, "kept lazy behind a proxy (never materialised)")
        return None

    def encode(self, obj: Any, ctx: Context) -> dict[str, Any]:
        from .custom import proxy_encode
        env = proxy_encode(obj.obj if isinstance(obj, Lazy) else obj, ctx)
        env["kind"] = "proxy"
        env["lazy"] = True
        env["description"] = obj.describe() if isinstance(obj, Lazy) else {"class": type(obj).__name__, "streaming": True}
        ctx.record("lazy", ConversionPath.LAZY, "proxy", "lazy object kept in Python; R pulls batches on demand")
        ctx.plan.fidelity.set("laziness", Fidelity.LOSSLESS, "not materialised")
        ctx.plan.copies = 0
        return env

    def decode(self, env: dict[str, Any], ctx: Context) -> Any:  # pragma: no cover - proxies decode via ProxyAdapter
        from .custom import ProxyAdapter
        return ProxyAdapter().decode(env, ctx)


REGISTRY.register(LazyAdapter(), tested=True)
