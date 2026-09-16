"""Relational SQL adapters (section 47.1): SQLite (stdlib), generic
SQLAlchemy (PostgreSQL, MySQL/MariaDB, SQL Server, Oracle, Db2,
CockroachDB, ...).  R side: DBI + RSQLite / RPostgres / RMariaDB / odbc.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from .base import ConnectionRef, DatabaseAdapter


def _to_arrow(df: Any) -> Any:
    import pyarrow as pa
    return pa.Table.from_pandas(df, preserve_index=False)


class SQLiteAdapter(DatabaseAdapter):
    backend = "sqlite"
    category = "relational"
    r_package = "RSQLite"
    r_supported = True
    tested_live = True

    def connect(self, ref: ConnectionRef) -> Any:
        con = sqlite3.connect(ref.database or ":memory:", check_same_thread=False)
        con.row_factory = None
        if ref.options.get("spatialite"):
            try:
                con.enable_load_extension(True)
                con.load_extension("mod_spatialite")
            except Exception as e:
                raise RuntimeError(f"could not load SpatiaLite extension: {e}") from e
        return con

    def tables(self, conn: Any) -> list[str]:
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view') ORDER BY name")
        return [r[0] for r in cur.fetchall()]

    def schema(self, conn: Any, table: str) -> list[dict[str, Any]]:
        cur = conn.execute(f"PRAGMA table_info({self.quote(table)})")
        return [{"name": r[1], "type": r[2], "nullable": not r[3], "primary_key": bool(r[5])} for r in cur.fetchall()]

    def keys(self, conn: Any, table: str) -> dict[str, Any]:
        pk = [c["name"] for c in self.schema(conn, table) if c["primary_key"]]
        fks = [{"column": r[3], "ref_table": r[2], "ref_column": r[4]} for r in conn.execute(f"PRAGMA foreign_key_list({self.quote(table)})").fetchall()]
        idx = [r[1] for r in conn.execute(f"PRAGMA index_list({self.quote(table)})").fetchall()]
        return {"primary_key": pk, "foreign_keys": fks, "indexes": idx}

    def query_pandas(self, conn: Any, sql: str, params: Any = None, limit: int | None = None) -> Any:
        import pandas as pd
        if limit is not None:
            sql = self.limit_sql(sql, limit)
        cur = conn.execute(sql, params or [])
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
        return pd.DataFrame(rows, columns=cols)

    def query_arrow(self, conn: Any, sql: str, params: Any = None, limit: int | None = None) -> Any:
        return _to_arrow(self.query_pandas(conn, sql, params, limit))

    def write(self, conn: Any, table: str, df: Any, mode: str = "fail") -> None:
        df.to_sql(table, conn, if_exists={"fail": "fail", "replace": "replace", "append": "append"}[mode], index=False)


class SQLAlchemyAdapter(DatabaseAdapter):
    """Generic DB-API/SQLAlchemy adapter.  ``backend`` is the dialect name."""

    category = "relational"
    requires = ("sqlalchemy",)
    r_supported = True
    tested_live = False   # only the sqlite dialect is exercised in CI

    _DIALECT = {"postgresql": "postgresql+psycopg", "mysql": "mysql+pymysql", "mssql": "mssql+pyodbc", "oracle": "oracle+oracledb",
                "db2": "ibm_db_sa", "sqlite": "sqlite", "redshift": "redshift+psycopg2", "snowflake": "snowflake",
                "bigquery": "bigquery", "databricks": "databricks", "clickhouse": "clickhouse", "trino": "trino"}
    _RPKG = {"postgresql": "RPostgres", "mysql": "RMariaDB", "mssql": "odbc", "oracle": "odbc", "db2": "odbc", "sqlite": "RSQLite",
             "redshift": "RPostgres", "snowflake": "odbc", "bigquery": "bigrquery", "databricks": "odbc", "clickhouse": "RClickhouse", "trino": "RPresto"}

    def __init__(self, backend: str):
        self.backend = backend
        self.r_package = self._RPKG.get(backend)
        self.r_supported = self.r_package is not None
        self.tested_live = backend == "sqlite"

    def url(self, ref: ConnectionRef) -> Any:
        from sqlalchemy.engine import URL
        drv = ref.options.get("driver_dialect") or self._DIALECT.get(ref.backend, ref.backend)
        if ref.backend == "sqlite":
            return f"sqlite:///{ref.database or ''}" if ref.database not in (None, ":memory:") else "sqlite://"
        return URL.create(drv, username=ref.user, password=ref.secret(), host=ref.host, port=ref.port, database=ref.database,
                          query={k: str(v) for k, v in ref.options.items() if k != "driver_dialect"})

    def connect(self, ref: ConnectionRef) -> Any:
        import sqlalchemy as sa
        eng = sa.create_engine(self.url(ref))
        return eng

    def tables(self, conn: Any) -> list[str]:
        import sqlalchemy as sa
        return sa.inspect(conn).get_table_names()

    def schema(self, conn: Any, table: str) -> list[dict[str, Any]]:
        import sqlalchemy as sa
        insp = sa.inspect(conn)
        pk = set(insp.get_pk_constraint(table).get("constrained_columns") or [])
        return [{"name": c["name"], "type": str(c["type"]), "nullable": bool(c.get("nullable", True)), "primary_key": c["name"] in pk}
                for c in insp.get_columns(table)]

    def keys(self, conn: Any, table: str) -> dict[str, Any]:
        import sqlalchemy as sa
        insp = sa.inspect(conn)
        return {"primary_key": list(insp.get_pk_constraint(table).get("constrained_columns") or []),
                "foreign_keys": [{"column": fk["constrained_columns"], "ref_table": fk["referred_table"], "ref_column": fk["referred_columns"]}
                                 for fk in insp.get_foreign_keys(table)],
                "indexes": [i["name"] for i in insp.get_indexes(table)]}

    def query_pandas(self, conn: Any, sql: str, params: Any = None, limit: int | None = None) -> Any:
        import pandas as pd
        import sqlalchemy as sa
        if limit is not None:
            sql = self.limit_sql(sql, limit)
        stmt = sa.text(sql)
        with conn.connect() as c:
            if isinstance(params, (list, tuple)):
                # positional '?' placeholders -> named
                for i, _ in enumerate(params):
                    sql = sql.replace("?", f":p{i}", 1)
                stmt = sa.text(sql)
                params = {f"p{i}": v for i, v in enumerate(params)}
            res = c.execute(stmt, params or {})
            return pd.DataFrame(res.fetchall(), columns=list(res.keys()))

    def query_arrow(self, conn: Any, sql: str, params: Any = None, limit: int | None = None) -> Any:
        return _to_arrow(self.query_pandas(conn, sql, params, limit))

    def write(self, conn: Any, table: str, df: Any, mode: str = "fail") -> None:
        df.to_sql(table, conn, if_exists={"fail": "fail", "replace": "replace", "append": "append"}[mode], index=False)

    def quote(self, ident: str) -> str:
        if self.backend in ("mysql", "clickhouse", "bigquery", "databricks"):
            return "`" + ident.replace("`", "``") + "`"
        if self.backend == "mssql":
            return "[" + ident.replace("]", "]]") + "]"
        return '"' + ident.replace('"', '""') + '"'

    def limit_sql(self, sql: str, limit: int) -> str:
        if self.backend == "mssql":
            return f"SELECT TOP {int(limit)} * FROM ({sql}) AS _rp_sub"
        if self.backend == "oracle":
            return f"SELECT * FROM ({sql}) _rp_sub FETCH FIRST {int(limit)} ROWS ONLY"
        return super().limit_sql(sql, limit)
