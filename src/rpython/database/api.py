"""High-level database API.

    >>> db = rp.connect("duckdb:///research.duckdb")
    >>> rel = db.table("panel").filter("year >= ?", [2000])   # nothing fetched yet
    >>> rel.describe_structure()
    >>> r["panel"] = rel          # R opens the same file; the query is pushed down
    >>> df = rel.to_pandas()      # explicit materialisation (memory-guarded)
"""
from __future__ import annotations

from typing import Any

from .base import ConnectionRef, DatabaseAdapter, VAULT
from .relation import Relation
from . import registry


class Database:
    def __init__(self, ref: ConnectionRef, adapter: DatabaseAdapter, conn: Any):
        self.ref, self.adapter, self.conn = ref, adapter, conn

    def tables(self) -> list[str]:
        return self.adapter.tables(self.conn)

    def table(self, name: str) -> Relation:
        return Relation(self.ref, self.adapter, self.conn, table=name)

    def sql(self, query: str, params: Any = None) -> Relation:
        """A parametrised query as a lazy relation (``?`` or ``:name`` placeholders, values bound)."""
        return Relation(self.ref, self.adapter, self.conn, sql=query, params=params)

    def schema(self, table: str) -> list[dict[str, Any]]:
        return self.adapter.schema(self.conn, table)

    def write(self, table: str, df: Any, mode: str = "fail") -> Relation:
        self.adapter.write(self.conn, table, df, mode)
        return self.table(table)

    def execute(self, sql: str, params: Any = None) -> Any:
        return self.adapter.query_pandas(self.conn, sql, params)

    def read_spatial(self, table: str, **kw: Any) -> Any:
        if not hasattr(self.adapter, "read_spatial"):
            raise TypeError(f"backend {self.ref.backend} has no spatial support; use postgis / spatialite / duckdb-spatial")
        return self.adapter.read_spatial(self.conn, table, **kw)

    def close(self) -> None:
        self.adapter.close(self.conn)

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *a: Any) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"<Database {self.ref.redacted()} via {type(self.adapter).__name__}>"


def connect(target: str | ConnectionRef, **kw: Any) -> Database:
    """Open a database from a URL, a file path or a :class:`ConnectionRef`.

    Secrets in URLs are moved to the process-local vault immediately and
    never appear in any envelope, log, explain report or bundle.
    """
    ref = target if isinstance(target, ConnectionRef) else ConnectionRef.from_url(target, **kw)
    adapter = registry.get(ref.backend)
    conn = adapter.connect(ref)
    return Database(ref, adapter, conn)


def relation(target: str | ConnectionRef, table: str | None = None, sql: str | None = None, params: Any = None) -> Relation:
    db = connect(target)
    return db.sql(sql, params) if sql else db.table(table)  # type: ignore[arg-type]


def catalog() -> list[dict[str, Any]]:
    return registry.catalog()
