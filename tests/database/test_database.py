"""Database layer: connection references never leak secrets, relations are lazy,
parameters are bound, SQLite/DuckDB/Parquet-lake work live; other backends
are interface-tested with fakes (section 79)."""
import os

import numpy as np
import pandas as pd
import pytest

import rpython as rp
from rpython.database.base import ConnectionRef, VAULT
from rpython.database import registry
from rpython.data.context import MemoryGuardError
from tests.conftest import has


def test_connection_ref_never_serialises_secret():
    ref = ConnectionRef.from_url("postgresql://alice:s3cret@db.example.org:5432/research?sslmode=require")
    assert ref.backend == "postgresql" and ref.user == "alice" and ref.host == "db.example.org" and ref.port == 5432
    d = ref.to_dict()
    assert "s3cret" not in str(d) and "s3cret" not in ref.redacted() and "s3cret" not in repr(ref)
    assert ref.secret() == "s3cret" and ref.secret_env in VAULT
    assert ref.options == {"sslmode": "require"}
    assert ConnectionRef.from_url("mydata.duckdb").backend == "duckdb"
    assert ConnectionRef.from_url("x.sqlite").backend == "sqlite"
    assert ConnectionRef.from_url("timescaledb://h/db").backend == "postgresql"
    assert ConnectionRef.from_url("mongodb://h:27017/db").backend == "mongodb"


def test_sqlite_relation_lazy_and_bound(tmp_path):
    db = rp.connect(f"sqlite:///{tmp_path / 'a.sqlite'}")
    df = pd.DataFrame({"id": [1, 2, 3], "country": ["FR", "DE", "FR"], "v": [1.5, 2.5, 3.5]})
    db.write("obs", df)
    rel = db.table("obs")
    assert rel.count() == 3 and rel.columns == ["id", "country", "v"]
    flt = rel.filter("country = ? AND v > ?", ["FR", 2.0])
    assert flt.to_pandas()["id"].tolist() == [3]
    with pytest.raises(ValueError):
        rel.filter("country = 'FR'")            # inline literals refused
    assert rel.select("id").head(2).columns.tolist() == ["id"]
    assert "lazy" in repr(rel) and "Materialised: no" in rel.describe_structure()
    assert sum(b.num_rows for b in rel.to_arrow_batches(2)) == 3
    db.close()


@pytest.mark.skipif(not has("duckdb"), reason="duckdb")
def test_duckdb_relation_and_memory_guard(tmp_path):
    db = rp.connect(f"duckdb:///{tmp_path / 'b.duckdb'}")
    df = pd.DataFrame({"a": np.arange(1000), "b": np.random.rand(1000)})
    db.write("t", df)
    rel = db.table("t")
    assert rel.count() == 1000 and rel.schema()[0]["name"] == "a"
    rp.config(memory_threshold_bytes=100)
    try:
        with pytest.raises(MemoryGuardError):
            rel.to_pandas()
        assert len(rel.to_pandas(allow_materialize=True)) == 1000
    finally:
        rp.reset_config()
    assert len(rel.limit(5).to_polars() if has("polars") else rel.limit(5).to_pandas()) == 5
    db.close()


@pytest.mark.skipif(not (has("duckdb") and has("pyarrow")), reason="duckdb+pyarrow")
def test_parquet_lake(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    pq.write_table(pa.table({"x": [1, 2], "y": ["a", "b"]}), str(tmp_path / "p1.parquet"))
    pq.write_table(pa.table({"x": [3], "y": ["c"]}), str(tmp_path / "p2.parquet"))
    db = rp.connect(ConnectionRef("parquet", database=str(tmp_path)))
    rel = db.table("dataset")
    assert rel.count() == 3 and rel.to_pandas().sort_values("x")["y"].tolist() == ["a", "b", "c"]


def test_registry_catalog_is_honest():
    cat = registry.catalog()
    live = {c["backend"] for c in cat if c["tested_live"]}
    assert live <= {"sqlite", "duckdb", "parquet"}
    assert {"mongodb", "redis", "neo4j", "influxdb", "qdrant", "elasticsearch", "delta", "postgis", "bigquery", "snowflake"} <= {c["backend"] for c in cat}
    with pytest.raises(KeyError):
        registry.get("nosuchdb")


class _FakeMongoCollection:
    def __init__(self, docs):
        self.docs = docs

    def find(self, q=None):
        return _Cursor([d for d in self.docs if all(d.get(k) == v for k, v in (q or {}).items())])

    def count_documents(self, q):
        return len(list(self.find(q)))


class _Cursor(list):
    def limit(self, n):
        return _Cursor(self[:n])


class _FakeMongoDB(dict):
    def list_collection_names(self):
        return list(self)


def test_document_adapter_keeps_nested_docs():
    from rpython.database.nosql import MongoAdapter
    db = _FakeMongoDB(users=_FakeMongoCollection([{"_id": 1, "name": "a", "address": {"city": "Paris"}}, {"_id": 2, "name": "b"}]))
    ad = MongoAdapter()
    assert ad.tables(db) == ["users"]
    docs = ad.find(db, "users", {"name": "a"})
    assert docs[0]["address"]["city"] == "Paris" and ad.count(db, "users", {}) == 2
    assert {c["name"] for c in ad.schema(db, "users")} == {"_id", "name", "address"}


def test_sparql_bindings_keep_term_types():
    from rpython.database.nosql import SPARQLAdapter

    class W:
        def setQuery(self, q):
            pass

        def query(self):
            class R:
                def convert(self_):
                    return {"results": {"bindings": [{"s": {"type": "uri", "value": "http://ex/a"},
                                                        "o": {"type": "literal", "value": "3", "datatype": "http://www.w3.org/2001/XMLSchema#int"}}]}}
            return R()
    df = SPARQLAdapter().query_pandas(W(), "SELECT ?s ?o WHERE {}")
    assert df.loc[0, "s__type"] == "uri" and df.loc[0, "o__datatype"].endswith("#int")


@pytest.mark.r
@pytest.mark.skipif(not has("duckdb"), reason="duckdb")
def test_shared_relation_with_r(r, tmp_path):
    if not r.capabilities["packages"].get("duckdb"):
        pytest.skip("R duckdb not installed")
    path = tmp_path / "shared.duckdb"
    db = rp.connect(f"duckdb:///{path}")
    db.write("panel", pd.DataFrame({"country": ["FR", "DE", "FR"], "year": [2000, 2000, 2001], "gdp": [1., 2., 3.]}))
    rel = db.table("panel").filter("year >= ?", [2001])
    rel.schema(); rel.count()
    db.close()
    r["rel"] = rel
    txt = rp.explain_last(print_it=False)
    assert "0 (query pushdown)" in txt and "s3cret" not in txt
    n = r("nrow(dplyr::collect(rel))") if r.capabilities["packages"].get("dbplyr") else r("nrow(DBI::dbGetQuery(rel$con, rel$sql))")
    assert int(n) == 1
    back = r["rel"]
    assert isinstance(back, rp.Relation) and back.count() == 1


@pytest.mark.r
def test_sqlite_from_r_to_python(r, tmp_path):
    if not r.capabilities["packages"].get("RSQLite"):
        pytest.skip("RSQLite not installed")
    p = str(tmp_path / "r.sqlite").replace("\\", "/")
    r(f"con <- DBI::dbConnect(RSQLite::SQLite(), '{p}'); DBI::dbWriteTable(con, 'mt', head(mtcars, 5)); rel <- rpx_relation(con, table = 'mt')")
    back = r["rel"]
    assert isinstance(back, rp.Relation) and back.count() == 5 and "mpg" in back.columns
    r("DBI::dbDisconnect(con)")
