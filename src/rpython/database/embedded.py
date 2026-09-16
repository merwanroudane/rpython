"""Embedded analytical engines (section 47.2): DuckDB -- the preferred
interchange engine because R and Python can both open the same file /
Parquet / Arrow source and push queries down."""
from __future__ import annotations

from typing import Any

from .base import ConnectionRef, DatabaseAdapter


class DuckDBAdapter(DatabaseAdapter):
    backend = "duckdb"
    category = "embedded"
    requires = ("duckdb",)
    r_package = "duckdb"
    r_supported = True
    tested_live = True

    def connect(self, ref: ConnectionRef) -> Any:
        import duckdb
        con = duckdb.connect(ref.database or ":memory:", read_only=ref.read_only)
        if ref.options.get("spatial"):
            con.execute("INSTALL spatial; LOAD spatial;")
        return con

    def tables(self, conn: Any) -> list[str]:
        return [r[0] for r in conn.execute("SELECT table_name FROM information_schema.tables ORDER BY 1").fetchall()]

    def schema(self, conn: Any, table: str) -> list[dict[str, Any]]:
        rows = conn.execute("SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE table_name = ? ORDER BY ordinal_position", [table]).fetchall()
        pk = set()
        try:
            for r in conn.execute("SELECT constraint_column_names FROM duckdb_constraints() WHERE table_name = ? AND constraint_type = 'PRIMARY KEY'", [table]).fetchall():
                pk.update(r[0])
        except Exception:
            pass
        return [{"name": r[0], "type": r[1], "nullable": r[2] == "YES", "primary_key": r[0] in pk} for r in rows]

    def keys(self, conn: Any, table: str) -> dict[str, Any]:
        pk = [c["name"] for c in self.schema(conn, table) if c["primary_key"]]
        fks = []
        try:
            for r in conn.execute("SELECT constraint_column_names, constraint_text FROM duckdb_constraints() WHERE table_name = ? AND constraint_type = 'FOREIGN KEY'", [table]).fetchall():
                fks.append({"column": r[0], "text": r[1]})
        except Exception:
            pass
        return {"primary_key": pk, "foreign_keys": fks, "indexes": []}

    def query_arrow(self, conn: Any, sql: str, params: Any = None, limit: int | None = None) -> Any:
        if limit is not None:
            sql = self.limit_sql(sql, limit)
        return conn.execute(sql, params or []).fetch_arrow_table()

    def query_pandas(self, conn: Any, sql: str, params: Any = None, limit: int | None = None) -> Any:
        if limit is not None:
            sql = self.limit_sql(sql, limit)
        return conn.execute(sql, params or []).df()

    def count(self, conn: Any, sql: str, params: Any = None) -> int | None:
        return int(conn.execute(f"SELECT COUNT(*) FROM ({sql})", params or []).fetchone()[0])

    def write(self, conn: Any, table: str, df: Any, mode: str = "fail") -> None:
        conn.register("_rp_df", df)
        q = self.quote(table)
        if mode == "replace":
            conn.execute(f"CREATE OR REPLACE TABLE {q} AS SELECT * FROM _rp_df")
        elif mode == "append":
            conn.execute(f"INSERT INTO {q} SELECT * FROM _rp_df")
        else:
            conn.execute(f"CREATE TABLE {q} AS SELECT * FROM _rp_df")
        conn.unregister("_rp_df")

    def register_files(self, conn: Any, name: str, path: str) -> None:
        """Expose Parquet/CSV/Arrow files as a view (shared, lazy)."""
        low = path.lower()
        reader = "read_parquet" if low.endswith((".parquet", ".pq")) else "read_csv_auto" if low.endswith((".csv", ".tsv")) else "read_json_auto" if low.endswith(".json") else None
        if reader is None:
            raise ValueError(f"unsupported file for DuckDB view: {path}")
        conn.execute(f"CREATE OR REPLACE VIEW {self.quote(name)} AS SELECT * FROM {reader}(?)", [path])
