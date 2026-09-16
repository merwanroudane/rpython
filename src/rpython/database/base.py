"""Database interoperability core (sections 47-49, 65).

* :class:`ConnectionRef` -- how both runtimes identify the *same* data
  source.  It never contains a secret: passwords/tokens live in the
  process-local :class:`SecretVault` and reach the R worker only through
  an in-memory ``setenv`` message (never through envelopes, logs, explain
  output or bundles).
* :class:`Relation` -- a lazy table/query.  Nothing is fetched until you
  ask (``head``, ``to_pandas``, ``to_arrow``); materialisation goes
  through the memory guard.
* :class:`DatabaseAdapter` -- per-backend behaviour, registered in
  :mod:`rpython.database.registry`.
"""
from __future__ import annotations

import hashlib
import os
import threading
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse, parse_qs, unquote


class SecretVault:
    """Process-local secret store.  Keys are opaque ids; values are never serialised."""

    def __init__(self) -> None:
        self._s: dict[str, str] = {}
        self._lock = threading.Lock()

    def put(self, secret: str) -> str:
        key = "RPYTHON_SECRET_" + hashlib.sha256(secret.encode()).hexdigest()[:12].upper()
        with self._lock:
            self._s[key] = secret
        return key

    def get(self, key: str) -> str | None:
        with self._lock:
            return self._s.get(key) or os.environ.get(key)

    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None


VAULT = SecretVault()

_BACKEND_ALIASES = {
    "postgres": "postgresql", "psql": "postgresql", "pg": "postgresql", "timescaledb": "postgresql", "timescale": "postgresql",
    "questdb": "postgresql", "cockroachdb": "postgresql", "cockroach": "postgresql", "redshift": "redshift",
    "mariadb": "mysql", "sqlserver": "mssql", "mssql+pyodbc": "mssql", "oracle": "oracle", "db2": "db2", "ibm_db_sa": "db2",
    "mongodb": "mongodb", "mongo": "mongodb", "redis": "redis", "neo4j": "neo4j", "bolt": "neo4j", "memgraph": "neo4j",
    "influxdb": "influxdb", "influx": "influxdb", "elasticsearch": "elasticsearch", "opensearch": "opensearch",
    "bigquery": "bigquery", "snowflake": "snowflake", "databricks": "databricks", "clickhouse": "clickhouse",
    "trino": "trino", "presto": "trino", "qdrant": "qdrant", "chroma": "chroma", "milvus": "milvus", "weaviate": "weaviate",
    "pinecone": "pinecone", "delta": "delta", "iceberg": "iceberg", "parquet": "parquet", "arrow": "arrow", "spatialite": "sqlite",
}


@dataclass
class ConnectionRef:
    backend: str
    database: str | None = None
    host: str | None = None
    port: int | None = None
    user: str | None = None
    secret_env: str | None = None          # name of an env var (or vault key) holding the password/token
    schema: str | None = None
    read_only: bool = False
    options: dict[str, Any] = field(default_factory=dict)   # never secrets

    @classmethod
    def from_url(cls, url: str, **kw: Any) -> "ConnectionRef":
        """Parse a SQLAlchemy/URI-style URL.  An inline password is moved into the vault."""
        if "://" not in url:
            # bare path -> sqlite / duckdb by extension
            low = url.lower()
            if low.endswith((".duckdb", ".ddb")):
                return cls("duckdb", database=url, **kw)
            if low == ":memory:":
                return cls("duckdb", database=":memory:", **kw)
            return cls("sqlite", database=url, **kw)
        u = urlparse(url)
        scheme = u.scheme.split("+")[0].lower()
        backend = _BACKEND_ALIASES.get(scheme, scheme)
        ref = cls(backend, database=(u.path or "").lstrip("/") or None, host=u.hostname, port=u.port,
                  user=unquote(u.username) if u.username else None, **kw)
        if backend in ("sqlite", "duckdb"):
            ref.database = url.split("://", 1)[1] or ":memory:"
            if ref.database.startswith("/") and os.name == "nt" and len(ref.database) > 2 and ref.database[2] == ":":
                ref.database = ref.database[1:]
            ref.host = ref.port = ref.user = None
        if u.password:
            ref.secret_env = VAULT.put(unquote(u.password))
        q = parse_qs(u.query)
        for k, v in q.items():
            if any(s in k.lower() for s in ("password", "token", "secret", "key")):
                ref.secret_env = VAULT.put(v[0])
            else:
                ref.options[k] = v[0]
        return ref

    def to_dict(self) -> dict[str, Any]:
        """Serialisable and *secret-free*."""
        return {"backend": self.backend, "database": self.database, "host": self.host, "port": self.port,
                "user": self.user, "secret_env": self.secret_env, "schema": self.schema, "read_only": self.read_only,
                "options": {k: v for k, v in self.options.items()}}

    def redacted(self) -> str:
        auth = f"{self.user}:***@" if self.user else ""
        loc = f"{auth}{self.host or ''}{':' + str(self.port) if self.port else ''}"
        return f"{self.backend}://{loc}/{self.database or ''}"

    def secret(self) -> str | None:
        return VAULT.get(self.secret_env) if self.secret_env else None

    def key(self) -> str:
        return "|".join(str(x) for x in (self.backend, self.host, self.port, self.database, self.user, self.schema))

    def __repr__(self) -> str:
        return f"<ConnectionRef {self.redacted()}>"


class DatabaseAdapter:
    """Base class.  Subclasses implement ``connect`` and ``query``; optional hooks refine behaviour."""

    backend: str = ""
    category: str = "relational"
    requires: tuple[str, ...] = ()
    r_package: str | None = None
    r_supported: bool = False
    tested_live: bool = False
    supports_sql: bool = True

    def available(self) -> bool:
        import importlib.util
        return all(importlib.util.find_spec(p) is not None for p in self.requires)

    def connect(self, ref: ConnectionRef) -> Any:  # pragma: no cover - abstract
        raise NotImplementedError

    def close(self, conn: Any) -> None:
        try:
            conn.close()
        except Exception:
            pass

    def tables(self, conn: Any) -> list[str]:
        raise NotImplementedError

    def schema(self, conn: Any, table: str) -> list[dict[str, Any]]:
        """Columns with type/nullable/primary-key information where introspectable."""
        raise NotImplementedError

    def keys(self, conn: Any, table: str) -> dict[str, Any]:
        return {"primary_key": [], "foreign_keys": [], "indexes": []}

    def query_arrow(self, conn: Any, sql: str, params: Any = None, limit: int | None = None) -> Any:
        """Return a pyarrow.Table (preferred) for ``sql`` with bound ``params``."""
        raise NotImplementedError

    def query_pandas(self, conn: Any, sql: str, params: Any = None, limit: int | None = None) -> Any:
        return self.query_arrow(conn, sql, params, limit).to_pandas()

    def count(self, conn: Any, sql: str, params: Any = None) -> int | None:
        try:
            t = self.query_pandas(conn, f"SELECT COUNT(*) AS n FROM ({sql}) AS _rp_sub", params)
            return int(t.iloc[0, 0])
        except Exception:
            return None

    def write(self, conn: Any, table: str, df: Any, mode: str = "fail") -> None:
        raise NotImplementedError

    def quote(self, ident: str) -> str:
        return '"' + ident.replace('"', '""') + '"'

    def limit_sql(self, sql: str, limit: int) -> str:
        return f"SELECT * FROM ({sql}) AS _rp_sub LIMIT {int(limit)}"

    def __repr__(self) -> str:
        return f"<{type(self).__name__} backend={self.backend} category={self.category} live_tested={self.tested_live}>"
