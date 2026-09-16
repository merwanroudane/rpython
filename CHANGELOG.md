# Changelog

## 0.1.1 (2026-09-16)

Release-engineering corrections following the 0.1.0 audit:

* Packaging: the `all` extra is an explicit union of runtime extras (it previously self-referenced the
  distribution under the wrong name); the compatibility registry (`*.yaml`) now ships inside the package
  (`rpython/compatibility/`) and is read through `importlib.resources` with a clear
  `CompatibilityResourceError` instead of a silent empty registry; `rpython catalog` and `rp.doctor()` report it.
* Conversion: labelled scientific arrays (xarray) are no longer turned into `stars` objects when *stars* is
  installed in R — they stay R arrays with attributes, so an xarray round trip returns an xarray (this broke the
  interop CI on every OS).
* CI: interop matrix now covers Python 3.11–3.13 on Linux/macOS/Windows; new `wheel` job builds the
  distribution and smoke-tests it from a clean venv outside the source tree (`tools/wheel_smoke.py`);
  version-consistency gate (`tools/check_versions.py`); failure summaries published to the run page.
* R package: `Depends: R (>= 4.1)` declared (native pipe / lambda syntax); README/docs claims aligned with
  what CI verifies.
* Release report split into local / CI / artifact sections with commit SHA, run URLs and artifact SHA256; a
  release is only called ready when the CI runs of the same SHA are green.
* Hygiene: stray `Rplot001.png` removed, R artefacts ignored; `docs/security.md` added.
* Portability: SVG export requires `svglite` or a cairo-enabled R and verifies the written file; Python discovery from R
  reports why each candidate interpreter was rejected and no longer inherits R's LD_LIBRARY_PATH additions (which made a
  toolchain Python load the OS libpython); large R vectors use Arrow; Python→R messages are length-prefixed frames.

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
