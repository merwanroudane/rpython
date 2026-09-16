"""Non-relational adapters (sections 47.4-47.10): document, key-value,
property-graph / RDF, time-series, vector and search engines.

Each adapter wraps the vendor client when it is installed, exposes the
same ``Relation``-like surface where a tabular projection makes sense,
and otherwise returns native records (documents, key/value pairs,
nodes/edges) with their identity intact.  ``tested_live`` is False for
every adapter here: they are interface-tested with fakes in CI and have
documented optional integration tests (section 79) -- no vendor is
claimed as live-tested unless it was.
"""
from __future__ import annotations

from typing import Any, Iterable

import pandas as pd

from .base import ConnectionRef, DatabaseAdapter


def _to_arrow(df: pd.DataFrame) -> Any:
    import pyarrow as pa
    return pa.Table.from_pandas(df, preserve_index=False)


# --------------------------------------------------------------------------- document stores

class MongoAdapter(DatabaseAdapter):
    backend = "mongodb"
    category = "document"
    requires = ("pymongo",)
    r_package = "mongolite"
    r_supported = True
    supports_sql = False

    def connect(self, ref: ConnectionRef) -> Any:
        import pymongo
        auth = f"{ref.user}:{ref.secret()}@" if ref.user and ref.secret() else ""
        uri = f"mongodb://{auth}{ref.host or 'localhost'}:{ref.port or 27017}/"
        return pymongo.MongoClient(uri)[ref.database or "test"]

    def tables(self, conn: Any) -> list[str]:
        return sorted(conn.list_collection_names())

    def schema(self, conn: Any, table: str) -> list[dict[str, Any]]:
        sample = list(conn[table].find().limit(50))
        keys: dict[str, set[str]] = {}
        for d in sample:
            for k, v in d.items():
                keys.setdefault(k, set()).add(type(v).__name__)
        return [{"name": k, "type": "|".join(sorted(t)), "nullable": True, "primary_key": k == "_id"} for k, t in keys.items()]

    def find(self, conn: Any, table: str, query: dict[str, Any] | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        """Documents with nested structure and ``_id`` preserved (never flattened)."""
        cur = conn[table].find(query or {})
        if limit:
            cur = cur.limit(limit)
        return list(cur)

    def query_pandas(self, conn: Any, sql: str, params: Any = None, limit: int | None = None) -> pd.DataFrame:
        # ``sql`` is the collection name; params is the filter document
        docs = self.find(conn, sql, params, limit)
        return pd.DataFrame(docs)

    def query_arrow(self, conn: Any, sql: str, params: Any = None, limit: int | None = None) -> Any:
        return _to_arrow(self.query_pandas(conn, sql, params, limit))

    def count(self, conn: Any, sql: str, params: Any = None) -> int | None:
        return int(conn[sql].count_documents(params or {}))

    def write(self, conn: Any, table: str, df: Any, mode: str = "fail") -> None:
        if mode == "replace":
            conn[table].drop()
        conn[table].insert_many(df.to_dict("records") if isinstance(df, pd.DataFrame) else list(df))

    def limit_sql(self, sql: str, limit: int) -> str:
        return sql


# --------------------------------------------------------------------------- key-value

class RedisAdapter(DatabaseAdapter):
    backend = "redis"
    category = "keyvalue"
    requires = ("redis",)
    r_package = "redux"
    r_supported = True
    supports_sql = False

    def connect(self, ref: ConnectionRef) -> Any:
        import redis
        return redis.Redis(host=ref.host or "localhost", port=ref.port or 6379, db=int(ref.database or 0),
                           username=ref.user, password=ref.secret(), decode_responses=False)

    def tables(self, conn: Any) -> list[str]:
        return [k.decode(errors="replace") if isinstance(k, bytes) else k for k in conn.scan_iter(count=1000)]

    def schema(self, conn: Any, table: str) -> list[dict[str, Any]]:
        return [{"name": "key", "type": "bytes", "nullable": False, "primary_key": True},
                {"name": "value", "type": conn.type(table).decode(), "nullable": True, "primary_key": False},
                {"name": "ttl", "type": "int", "nullable": True, "primary_key": False}]

    def get(self, conn: Any, keys: Iterable[str]) -> pd.DataFrame:
        """Keys/values as bytes (binary vs string distinction kept) with TTL metadata."""
        rows = []
        for k in keys:
            v = conn.get(k)
            rows.append({"key": k, "value": v, "ttl": conn.ttl(k), "is_binary": isinstance(v, bytes) and not _is_text(v)})
        return pd.DataFrame(rows)

    def query_pandas(self, conn: Any, sql: str, params: Any = None, limit: int | None = None) -> pd.DataFrame:
        keys = [k for k in conn.scan_iter(match=sql or "*", count=1000)]
        if limit:
            keys = keys[:limit]
        return self.get(conn, keys)

    def query_arrow(self, conn: Any, sql: str, params: Any = None, limit: int | None = None) -> Any:
        return _to_arrow(self.query_pandas(conn, sql, params, limit))

    def count(self, conn: Any, sql: str, params: Any = None) -> int | None:
        return sum(1 for _ in conn.scan_iter(match=sql or "*"))

    def write(self, conn: Any, table: str, df: Any, mode: str = "fail") -> None:
        for _, row in df.iterrows():
            conn.set(row["key"], row["value"], ex=int(row["ttl"]) if "ttl" in row and pd.notna(row["ttl"]) and row["ttl"] > 0 else None)

    def limit_sql(self, sql: str, limit: int) -> str:
        return sql


def _is_text(b: bytes) -> bool:
    try:
        b.decode("utf-8")
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------- property graphs / RDF

class Neo4jAdapter(DatabaseAdapter):
    backend = "neo4j"
    category = "graph"
    requires = ("neo4j",)
    r_package = "neo4r"
    r_supported = True
    supports_sql = False   # Cypher

    def connect(self, ref: ConnectionRef) -> Any:
        from neo4j import GraphDatabase
        uri = f"bolt://{ref.host or 'localhost'}:{ref.port or 7687}"
        return GraphDatabase.driver(uri, auth=(ref.user, ref.secret()) if ref.user else None)

    def tables(self, conn: Any) -> list[str]:
        with conn.session() as s:
            return [r["label"] for r in s.run("CALL db.labels() YIELD label RETURN label")]

    def schema(self, conn: Any, table: str) -> list[dict[str, Any]]:
        with conn.session() as s:
            rec = s.run(f"MATCH (n:`{table}`) RETURN keys(n) AS k LIMIT 100")
            keys = sorted({k for r in rec for k in r["k"]})
        return [{"name": k, "type": "property", "nullable": True, "primary_key": False} for k in keys]

    def cypher(self, conn: Any, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        with conn.session() as s:
            return [r.data() for r in s.run(query, **(params or {}))]

    def subgraph(self, conn: Any, query: str = "MATCH (a)-[r]->(b) RETURN a, r, b LIMIT 10000", params: dict[str, Any] | None = None) -> Any:
        """Return an :class:`rpython.data.network.Network` with ids, labels, types, properties and direction kept."""
        from ..data.network import Network
        nodes: dict[Any, dict[str, Any]] = {}
        edges: list[dict[str, Any]] = []
        with conn.session() as s:
            for rec in s.run(query, **(params or {})):
                for v in rec.values():
                    if hasattr(v, "labels"):
                        nodes[v.element_id] = {"id": v.element_id, "labels": ";".join(sorted(v.labels)), **dict(v)}
                    elif hasattr(v, "type") and hasattr(v, "start_node"):
                        edges.append({"source": v.start_node.element_id, "target": v.end_node.element_id, "type": v.type, "edge_id": v.element_id, **dict(v)})
        return Network(pd.DataFrame(edges), pd.DataFrame(list(nodes.values())), directed=True, multigraph=True)

    def query_pandas(self, conn: Any, sql: str, params: Any = None, limit: int | None = None) -> pd.DataFrame:
        return pd.DataFrame(self.cypher(conn, sql, params))

    def query_arrow(self, conn: Any, sql: str, params: Any = None, limit: int | None = None) -> Any:
        return _to_arrow(self.query_pandas(conn, sql, params, limit))

    def count(self, conn: Any, sql: str, params: Any = None) -> int | None:
        return None

    def limit_sql(self, sql: str, limit: int) -> str:
        return sql if "LIMIT" in sql.upper() else f"{sql} LIMIT {int(limit)}"


class SPARQLAdapter(DatabaseAdapter):
    backend = "sparql"
    category = "graph"
    requires = ("SPARQLWrapper",)
    r_package = "SPARQL"
    r_supported = True
    supports_sql = False

    def connect(self, ref: ConnectionRef) -> Any:
        from SPARQLWrapper import SPARQLWrapper, JSON
        ep = ref.options.get("endpoint") or f"http://{ref.host}:{ref.port or 80}/{ref.database or 'sparql'}"
        w = SPARQLWrapper(ep)
        w.setReturnFormat(JSON)
        return w

    def tables(self, conn: Any) -> list[str]:
        return []

    def schema(self, conn: Any, table: str) -> list[dict[str, Any]]:
        return [{"name": n, "type": "rdf-term", "nullable": True, "primary_key": False} for n in ("subject", "predicate", "object")]

    def query_pandas(self, conn: Any, sql: str, params: Any = None, limit: int | None = None) -> pd.DataFrame:
        """Bindings keep RDF term *type* (uri / literal / bnode), datatype and language -- never flattened."""
        conn.setQuery(sql)
        res = conn.query().convert()
        rows = []
        for b in res["results"]["bindings"]:
            row: dict[str, Any] = {}
            for var, term in b.items():
                row[var] = term.get("value")
                row[f"{var}__type"] = term.get("type")
                if "datatype" in term:
                    row[f"{var}__datatype"] = term["datatype"]
                if "xml:lang" in term:
                    row[f"{var}__lang"] = term["xml:lang"]
            rows.append(row)
        return pd.DataFrame(rows)

    def query_arrow(self, conn: Any, sql: str, params: Any = None, limit: int | None = None) -> Any:
        return _to_arrow(self.query_pandas(conn, sql, params, limit))

    def count(self, conn: Any, sql: str, params: Any = None) -> int | None:
        return None

    def limit_sql(self, sql: str, limit: int) -> str:
        return sql if "LIMIT" in sql.upper() else f"{sql} LIMIT {int(limit)}"


# --------------------------------------------------------------------------- time-series stores

class InfluxAdapter(DatabaseAdapter):
    backend = "influxdb"
    category = "timeseries"
    requires = ("influxdb_client",)
    r_package = "influxdbr"
    r_supported = False
    supports_sql = False   # Flux

    def connect(self, ref: ConnectionRef) -> Any:
        from influxdb_client import InfluxDBClient
        url = f"http://{ref.host or 'localhost'}:{ref.port or 8086}"
        return InfluxDBClient(url=url, token=ref.secret(), org=ref.options.get("org"))

    def tables(self, conn: Any) -> list[str]:
        return [b.name for b in conn.buckets_api().find_buckets().buckets]

    def schema(self, conn: Any, table: str) -> list[dict[str, Any]]:
        return [{"name": "_time", "type": "timestamp[ns, tz=UTC]", "nullable": False, "primary_key": True},
                {"name": "_measurement", "type": "tag", "nullable": False, "primary_key": False},
                {"name": "_field", "type": "field", "nullable": False, "primary_key": False},
                {"name": "_value", "type": "double", "nullable": True, "primary_key": False}]

    def query_pandas(self, conn: Any, sql: str, params: Any = None, limit: int | None = None) -> pd.DataFrame:
        """Flux query -> DataFrame with ns-precision UTC timestamps, tags and fields kept as columns."""
        df = conn.query_api().query_data_frame(sql)
        if isinstance(df, list):
            df = pd.concat(df, ignore_index=True) if df else pd.DataFrame()
        return df

    def query_arrow(self, conn: Any, sql: str, params: Any = None, limit: int | None = None) -> Any:
        return _to_arrow(self.query_pandas(conn, sql, params, limit))

    def count(self, conn: Any, sql: str, params: Any = None) -> int | None:
        return None

    def limit_sql(self, sql: str, limit: int) -> str:
        return sql if "limit(" in sql else f"{sql} |> limit(n: {int(limit)})"


# --------------------------------------------------------------------------- vector stores

class VectorStoreAdapter(DatabaseAdapter):
    """qdrant / chroma / milvus / weaviate / pinecone: ids, vectors (dtype + dimension), payload, metric."""

    category = "vector"
    r_supported = False
    supports_sql = False
    _REQ = {"qdrant": "qdrant_client", "chroma": "chromadb", "milvus": "pymilvus", "weaviate": "weaviate", "pinecone": "pinecone"}

    def __init__(self, backend: str):
        self.backend = backend
        self.requires = (self._REQ[backend],)

    def connect(self, ref: ConnectionRef) -> Any:
        b = ref.backend
        if b == "qdrant":
            from qdrant_client import QdrantClient
            return QdrantClient(host=ref.host or "localhost", port=ref.port or 6333, api_key=ref.secret(), path=ref.database if ref.host is None and ref.database else None)
        if b == "chroma":
            import chromadb
            return chromadb.PersistentClient(path=ref.database) if ref.database and not ref.host else chromadb.HttpClient(host=ref.host or "localhost", port=ref.port or 8000)
        if b == "milvus":
            from pymilvus import MilvusClient
            return MilvusClient(uri=ref.database or f"http://{ref.host or 'localhost'}:{ref.port or 19530}", token=ref.secret())
        if b == "weaviate":
            import weaviate
            return weaviate.connect_to_local(host=ref.host or "localhost", port=ref.port or 8080)
        if b == "pinecone":
            from pinecone import Pinecone
            return Pinecone(api_key=ref.secret())
        raise ValueError(b)

    def tables(self, conn: Any) -> list[str]:
        b = self.backend
        if b == "qdrant":
            return [c.name for c in conn.get_collections().collections]
        if b == "chroma":
            return [c.name for c in conn.list_collections()]
        if b == "milvus":
            return list(conn.list_collections())
        if b == "weaviate":
            return list(conn.collections.list_all().keys())
        if b == "pinecone":
            return [i["name"] for i in conn.list_indexes()]
        return []

    def schema(self, conn: Any, table: str) -> list[dict[str, Any]]:
        info = self.collection_info(conn, table)
        return [{"name": "id", "type": "string|int", "nullable": False, "primary_key": True},
                {"name": "vector", "type": f"float32[{info.get('dimension')}]", "nullable": False, "primary_key": False},
                {"name": "payload", "type": "struct", "nullable": True, "primary_key": False}]

    def collection_info(self, conn: Any, table: str) -> dict[str, Any]:
        b = self.backend
        try:
            if b == "qdrant":
                c = conn.get_collection(table)
                vp = c.config.params.vectors
                return {"dimension": getattr(vp, "size", None), "metric": str(getattr(vp, "distance", "")), "count": c.points_count}
            if b == "chroma":
                col = conn.get_collection(table)
                return {"dimension": None, "metric": col.metadata.get("hnsw:space", "l2") if col.metadata else "l2", "count": col.count()}
            if b == "milvus":
                d = conn.describe_collection(table)
                dim = next((f["params"]["dim"] for f in d["fields"] if f.get("params", {}).get("dim")), None)
                return {"dimension": dim, "metric": None, "count": None}
            if b == "pinecone":
                d = conn.describe_index(table)
                return {"dimension": d.dimension, "metric": d.metric, "count": None}
        except Exception as e:
            return {"error": str(e)}
        return {}

    def fetch(self, conn: Any, table: str, limit: int = 1000) -> pd.DataFrame:
        """ids + vectors (numpy float32) + payload dicts."""
        b = self.backend
        rows: list[dict[str, Any]] = []
        if b == "qdrant":
            pts, _ = conn.scroll(table, limit=limit, with_vectors=True, with_payload=True)
            rows = [{"id": p.id, "vector": p.vector, "payload": p.payload} for p in pts]
        elif b == "chroma":
            r = conn.get_collection(table).get(limit=limit, include=["embeddings", "metadatas", "documents"])
            rows = [{"id": i, "vector": v, "payload": {**(m or {}), "document": d}} for i, v, m, d in
                    zip(r["ids"], r["embeddings"], r["metadatas"], r["documents"])]
        elif b == "milvus":
            for rec in conn.query(table, filter="", limit=limit, output_fields=["*"]):
                vec = next((v for k, v in rec.items() if isinstance(v, list) and v and isinstance(v[0], float)), None)
                rows.append({"id": rec.get("id"), "vector": vec, "payload": {k: v for k, v in rec.items() if k != "id" and v is not vec}})
        df = pd.DataFrame(rows)
        df.attrs["rpython"] = {"vector_store": {"backend": b, "collection": table, **self.collection_info(conn, table)}}
        return df

    def query_pandas(self, conn: Any, sql: str, params: Any = None, limit: int | None = None) -> pd.DataFrame:
        return self.fetch(conn, sql, limit or 1000)

    def query_arrow(self, conn: Any, sql: str, params: Any = None, limit: int | None = None) -> Any:
        return _to_arrow(self.query_pandas(conn, sql, params, limit))

    def count(self, conn: Any, sql: str, params: Any = None) -> int | None:
        return self.collection_info(conn, sql).get("count")

    def limit_sql(self, sql: str, limit: int) -> str:
        return sql


# --------------------------------------------------------------------------- search engines

class ElasticAdapter(DatabaseAdapter):
    category = "search"
    r_package = "elastic"
    r_supported = True
    supports_sql = False

    def __init__(self, backend: str = "elasticsearch"):
        self.backend = backend
        self.requires = ("opensearchpy",) if backend == "opensearch" else ("elasticsearch",)

    def connect(self, ref: ConnectionRef) -> Any:
        url = f"http://{ref.host or 'localhost'}:{ref.port or 9200}"
        if self.backend == "opensearch":
            from opensearchpy import OpenSearch
            return OpenSearch(url, http_auth=(ref.user, ref.secret()) if ref.user else None)
        from elasticsearch import Elasticsearch
        return Elasticsearch(url, basic_auth=(ref.user, ref.secret()) if ref.user else None, api_key=ref.secret() if not ref.user else None)

    def tables(self, conn: Any) -> list[str]:
        return sorted(conn.indices.get_alias(index="*").keys())

    def schema(self, conn: Any, table: str) -> list[dict[str, Any]]:
        m = conn.indices.get_mapping(index=table)
        props = m[table]["mappings"].get("properties", {})
        return [{"name": k, "type": v.get("type", "object"), "nullable": True, "primary_key": False} for k, v in props.items()]

    def search(self, conn: Any, index: str, body: dict[str, Any] | None = None, size: int = 1000) -> pd.DataFrame:
        """Hits with ``_id``, ``_score`` and the nested ``_source`` document kept intact."""
        res = conn.search(index=index, body=body or {"query": {"match_all": {}}}, size=size)
        rows = [{"_id": h["_id"], "_score": h.get("_score"), "_source": h["_source"]} for h in res["hits"]["hits"]]
        return pd.DataFrame(rows)

    def query_pandas(self, conn: Any, sql: str, params: Any = None, limit: int | None = None) -> pd.DataFrame:
        return self.search(conn, sql, params, limit or 1000)

    def query_arrow(self, conn: Any, sql: str, params: Any = None, limit: int | None = None) -> Any:
        return _to_arrow(self.query_pandas(conn, sql, params, limit))

    def count(self, conn: Any, sql: str, params: Any = None) -> int | None:
        return int(conn.count(index=sql, body={"query": (params or {}).get("query", {"match_all": {}})})["count"])

    def limit_sql(self, sql: str, limit: int) -> str:
        return sql
