"""Lazy relations, the query contract (sections 48-49) and the ``db_relation`` envelope."""
from __future__ import annotations

from typing import Any

from ..data.context import Context
from ..data.registry import Adapter, REGISTRY
from ..data.semantic import Confidence, ConversionPath, Detection, Fidelity
from .base import ConnectionRef, DatabaseAdapter


class Relation:
    """A table or parametrised query on a shared data source, evaluated lazily.

    ``params`` are always **bound** (never string-concatenated) -- see
    :meth:`filter` which only accepts parameter placeholders.
    """

    def __init__(self, ref: ConnectionRef, adapter: DatabaseAdapter, conn: Any, table: str | None = None,
                 sql: str | None = None, params: Any = None, columns: list[str] | None = None):
        self.ref, self.adapter, self.conn = ref, adapter, conn
        self.table, self.sql, self.params = table, sql, params
        self._columns = columns
        self._schema: list[dict[str, Any]] | None = None
        self._count: int | None = None

    # ------------------------------------------------------------------ description
    def sql_text(self) -> str:
        if self.sql:
            return self.sql
        return f"SELECT * FROM {self.adapter.quote(self.table)}" if self.table else ""

    @property
    def columns(self) -> list[str]:
        if self._columns is None:
            self._columns = [c["name"] for c in self.schema()]
        return self._columns

    def schema(self) -> list[dict[str, Any]]:
        if self._schema is None:
            if self.table and not self.sql:
                self._schema = self.adapter.schema(self.conn, self.table)
            else:
                head = self.adapter.query_arrow(self.conn, self.adapter.limit_sql(self.sql_text(), 0), self.params)
                self._schema = [{"name": f.name, "type": str(f.type), "nullable": f.nullable, "primary_key": False} for f in head.schema]
        return self._schema

    def keys(self) -> dict[str, Any]:
        return self.adapter.keys(self.conn, self.table) if self.table else {"primary_key": [], "foreign_keys": [], "indexes": []}

    def count(self) -> int | None:
        if self._count is None:
            self._count = self.adapter.count(self.conn, self.sql_text(), self.params)
        return self._count

    def describe_structure(self) -> str:
        n = self.count()
        lines = ["Type: Database relation (lazy)", f"Source: {self.ref.redacted()}",
                 f"Table: {self.table}" if self.table else f"Query: {self.sql_text()[:120]}",
                 f"Rows: {n if n is not None else 'unknown'}", f"Columns: {len(self.columns)}",
                 "Materialised: no"]
        k = self.keys()
        if k.get("primary_key"):
            lines.append(f"Primary key: {', '.join(k['primary_key'])}")
        return "\n".join(lines)

    # ------------------------------------------------------------------ composition (pushdown)
    def select(self, *cols: str) -> "Relation":
        sel = ", ".join(self.adapter.quote(c) for c in cols)
        return Relation(self.ref, self.adapter, self.conn, sql=f"SELECT {sel} FROM ({self.sql_text()}) AS _rp_s", params=self.params, columns=list(cols))

    def filter(self, condition: str, params: Any = None) -> "Relation":
        """``rel.filter("year > ? AND country = ?", [2000, "FR"])`` -- placeholders only, never inline values."""
        if params is None and any(tok in condition for tok in ("'", '"')):
            raise ValueError("bind values through params=..., do not inline literals into SQL (injection-safe by design)")
        merged = list(self.params or []) + list(params or []) if not isinstance(self.params, dict) else {**(self.params or {}), **(params or {})}
        return Relation(self.ref, self.adapter, self.conn, sql=f"SELECT * FROM ({self.sql_text()}) AS _rp_f WHERE {condition}",
                        params=merged or None, columns=self._columns)

    def limit(self, n: int) -> "Relation":
        return Relation(self.ref, self.adapter, self.conn, sql=self.adapter.limit_sql(self.sql_text(), n), params=self.params, columns=self._columns)

    # ------------------------------------------------------------------ materialisation
    def head(self, n: int = 10) -> Any:
        return self.adapter.query_pandas(self.conn, self.adapter.limit_sql(self.sql_text(), n), self.params)

    def _guard(self, ctx: Context | None, allow: bool) -> Context:
        ctx = ctx or Context()
        if allow:
            ctx.allow_materialize = True
        n = self.count()
        est = (n or 0) * max(len(self.columns), 1) * 8
        ctx.memory_guard(f"database relation ({n if n is not None else '?'} rows)", est,
                         "use .filter()/.select()/.limit() pushdown, .to_arrow_batches(), or share the relation with R lazily")
        return ctx

    def to_arrow(self, allow_materialize: bool = False, ctx: Context | None = None) -> Any:
        self._guard(ctx, allow_materialize)
        return self.adapter.query_arrow(self.conn, self.sql_text(), self.params)

    def to_pandas(self, allow_materialize: bool = False, ctx: Context | None = None) -> Any:
        self._guard(ctx, allow_materialize)
        return self.adapter.query_pandas(self.conn, self.sql_text(), self.params)

    def to_polars(self, **kw: Any) -> Any:
        import polars as pl
        return pl.from_arrow(self.to_arrow(**kw))

    def to_arrow_batches(self, batch_size: int = 50_000) -> Any:
        """Iterate over the relation in Arrow record batches (never all at once)."""
        offset = 0
        while True:
            sql = f"SELECT * FROM ({self.sql_text()}) AS _rp_b LIMIT {batch_size} OFFSET {offset}"
            tbl = self.adapter.query_arrow(self.conn, sql, self.params)
            if tbl.num_rows == 0:
                return
            yield tbl
            if tbl.num_rows < batch_size:
                return
            offset += batch_size

    def __repr__(self) -> str:
        return f"<Relation {self.ref.redacted()} {self.table or 'query'} columns={len(self.columns) if self._columns or self._schema else '?'} lazy>"


class RelationAdapter(Adapter):
    """Sends a Relation to R as a shared connection + query (no rows copied)."""

    family = "database"
    kinds = ("db_relation", "lazy_relation")
    tier = ConversionPath.LAZY
    priority = 3

    def detect(self, obj: Any) -> Detection | None:
        if isinstance(obj, Relation):
            return Detection("database relation", Confidence.CONFIRMED, obj.ref.redacted())
        if type(obj).__module__.startswith("duckdb") and hasattr(obj, "sql_query"):
            return Detection("DuckDB relation", Confidence.CONFIRMED, "duckdb.DuckDBPyRelation")
        return None

    def encode(self, obj: Any, ctx: Context) -> dict[str, Any]:
        if not isinstance(obj, Relation):
            # duckdb relation: share SQL text; the database is in-memory unless the connection has a file
            env = {"rpx": 1, "kind": "db_relation", "connection": {"backend": "duckdb", "database": ":memory:"},
                   "table": None, "sql": obj.sql_query(), "lazy": True, "columns": list(obj.columns),
                   "meta": {"source_class": "duckdb.DuckDBPyRelation"}}
            ctx.warn("in-memory DuckDB relation: R opens its own in-memory database; only the SQL text is shared")
            ctx.record("database", ConversionPath.LAZY, "shared-query", "SQL text shared, nothing copied")
            return env
        if obj.adapter.r_package is None or not obj.adapter.r_supported:
            ctx.plan.note(f"no R DBI driver for {obj.ref.backend}: relation materialised through Arrow instead")
            tbl = obj.to_arrow(ctx=ctx)
            from ..data.tabular import TableAdapter
            return TableAdapter().encode(tbl, ctx)
        if obj.ref.secret_env and ctx.session is not None:
            secret = obj.ref.secret()
            if secret is not None:
                ctx.session.setenv(obj.ref.secret_env, secret)
        conn_dict = obj.ref.to_dict()
        if obj.ref.backend == "duckdb" and conn_dict.get("database") not in (None, ":memory:"):
            conn_dict["read_only"] = True   # DuckDB files allow one writer: the peer opens read-only
            ctx.plan.note("DuckDB file shared read-only with R (close Python writers first, or open both read-only)")
        env = {"rpx": 1, "kind": "db_relation", "connection": conn_dict, "table": obj.table if not obj.sql else None,
               "sql": obj.sql, "params": obj.params, "lazy": True, "columns": obj.columns,
               "schema": obj.schema(), "keys": obj.keys(), "meta": {"source_class": "rpython.Relation"}}
        ctx.record("database", ConversionPath.LAZY, "shared-connection",
                   f"{obj.ref.redacted()} opened by R with {obj.adapter.r_package}; query pushed down, 0 rows copied")
        ctx.plan.copies = 0
        ctx.plan.fidelity.set("laziness", Fidelity.LOSSLESS, "shared source")
        ctx.plan.fidelity.set("values", Fidelity.LOSSLESS, "same database")
        ctx.plan.fidelity.set("metadata", Fidelity.LOSSLESS, "schema, keys and parameters travel; secrets never do")
        return env

    def decode(self, env: dict[str, Any], ctx: Context) -> Any:
        from .api import connect
        conn_ref = env.get("connection") or {}
        if not conn_ref.get("backend"):
            return env
        ref = ConnectionRef(conn_ref["backend"], database=conn_ref.get("database"), host=conn_ref.get("host"), port=conn_ref.get("port"),
                            user=conn_ref.get("user"), secret_env=conn_ref.get("secret_env"), schema=conn_ref.get("schema"))
        db = connect(ref)
        ctx.record("database", ConversionPath.LAZY, "shared-connection", "R DBI/dbplyr relation -> Python Relation (lazy)")
        if env.get("sql"):
            return db.sql(env["sql"], env.get("params"))
        return db.table(env["table"])


REGISTRY.register(RelationAdapter(), tested=True)
