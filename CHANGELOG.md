# Changelog

## 0.1.0 (2026-09-16)

First release.

* Semantic data layer with adapters for primitives, collections, arrays/tensors, sparse matrices, tabular data
  (pandas/Polars/Arrow/interchange), time series, panel/cross-section/repeated cross-section/hierarchical data,
  labelled survey data, survival data, spatial vectors, rasters, spatiotemporal data, networks/graphs/triples,
  text (DTM/corpus), media (image/audio/video), scientific labelled arrays (xarray), economics structures
  (input-output, trade, spatial weights, dyadic, mixed frequency, vintages, experiments, simulations),
  lazy/streaming objects and universal proxies.
* Isolated R worker (`rp.R()`), R-side `python()` client, shared RPX envelope (JSON + Arrow IPC + WKB).
* Database layer: secret-free connection references, lazy relations with pushdown and bound parameters,
  adapters for SQLite, DuckDB, SQLAlchemy dialects, Parquet/Delta/Iceberg lakes, MongoDB, Redis, Neo4j,
  SPARQL, InfluxDB, vector stores, Elasticsearch/OpenSearch, PostGIS/SpatiaLite/DuckDB-spatial.
* Explain Mode, fidelity engine, `doctor/check/self_test/fix/restore`, Jupyter/Colab magics, CLI,
  `rpython.lock`, `.rpx` bundles, family-aware save/load with sidecars.
