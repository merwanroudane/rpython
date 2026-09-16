# Databases

```python
import pandas as pd, rpython as rp
db = rp.connect("sqlite:///demo.sqlite")
db.write("t", pd.DataFrame({"a": [1, 2, 3], "s": ["x", "y", "z"]}))
rel = db.table("t").filter("a > ?", [1]).select("a")
print(rel.count(), rel.columns, rel.head())
for batch in rel.to_arrow_batches(2):
    print(batch.num_rows)
```

* URLs: `sqlite:///file`, `duckdb:///file`, `postgresql://user:pw@host/db` (the password goes to the vault), `mysql://`, `mssql://`, `oracle://`, `bigquery://`, `snowflake://`, `mongodb://`, `redis://`, `neo4j://`, `influxdb://`, Parquet folders (`ConnectionRef("parquet", database=path)`), `delta://`, `iceberg://`.
* `rel.to_pandas()` / `.to_arrow()` / `.to_polars()` are memory-guarded; `.limit()`, `.filter()`, `.select()` push down.
* Sharing with R: `r["rel"] = rel` sends the connection reference + SQL; R opens the same source with DBI/dbplyr and never receives a password (only the name of an env var). DuckDB files are opened read-only on the second side.
* From R: `rpx_relation(con, table = "t")` sends a lazy relation to Python.
* Spatial SQL: `db.read_spatial("table")` for PostGIS / SpatiaLite / DuckDB-spatial returns WKB-decoded geometries with the SRID.
* Which backends are live-tested is printed by `rpython catalog` (SQLite, DuckDB, Parquet lake); the others are interface-tested with fakes.
