"""Database adapter registry: backend name -> adapter (section 47)."""
from __future__ import annotations

from typing import Any

from .base import DatabaseAdapter
from .embedded import DuckDBAdapter
from .lakehouse import (DeltaAdapter, DuckDBSpatialAdapter, IcebergAdapter, ParquetLakeAdapter, PostGISAdapter,
                        SpatiaLiteAdapter)
from .nosql import (ElasticAdapter, InfluxAdapter, MongoAdapter, Neo4jAdapter, RedisAdapter, SPARQLAdapter,
                    VectorStoreAdapter)
from .sql import SQLAlchemyAdapter, SQLiteAdapter

_ADAPTERS: dict[str, DatabaseAdapter] = {}


def register(adapter: DatabaseAdapter, *names: str) -> DatabaseAdapter:
    for n in names or (adapter.backend,):
        _ADAPTERS[n] = adapter
    return adapter


def get(backend: str) -> DatabaseAdapter:
    ad = _ADAPTERS.get(backend)
    if ad is None:
        raise KeyError(f"no database adapter for backend {backend!r}; known: {', '.join(sorted(_ADAPTERS))}")
    if not ad.available():
        raise ImportError(f"backend {backend!r} needs Python package(s): {', '.join(ad.requires)}  "
                          f"(pip install {' '.join(ad.requires)})")
    return ad


def catalog() -> list[dict[str, Any]]:
    seen = set()
    out = []
    for name, ad in _ADAPTERS.items():
        if id(ad) in seen:
            continue
        seen.add(id(ad))
        out.append({"backend": ad.backend, "aliases": [n for n, a in _ADAPTERS.items() if a is ad], "category": ad.category,
                    "python_requires": list(ad.requires), "available": ad.available(), "r_package": ad.r_package,
                    "r_supported": ad.r_supported, "tested_live": ad.tested_live, "sql": ad.supports_sql})
    return out


register(SQLiteAdapter(), "sqlite")
register(DuckDBAdapter(), "duckdb")
for _b in ("postgresql", "mysql", "mssql", "oracle", "db2", "redshift", "snowflake", "bigquery", "databricks", "clickhouse", "trino"):
    register(SQLAlchemyAdapter(_b), _b)
register(MongoAdapter(), "mongodb")
register(RedisAdapter(), "redis")
register(Neo4jAdapter(), "neo4j")
register(SPARQLAdapter(), "sparql")
register(InfluxAdapter(), "influxdb")
for _v in ("qdrant", "chroma", "milvus", "weaviate", "pinecone"):
    register(VectorStoreAdapter(_v), _v)
register(ElasticAdapter("elasticsearch"), "elasticsearch")
register(ElasticAdapter("opensearch"), "opensearch")
register(ParquetLakeAdapter(), "parquet", "arrow")
register(DeltaAdapter(), "delta")
register(IcebergAdapter(), "iceberg")
register(PostGISAdapter(), "postgis")
register(SpatiaLiteAdapter(), "spatialite")
register(DuckDBSpatialAdapter(), "duckdb-spatial")
