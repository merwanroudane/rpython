# Compatibility policy

* **Capability detection** over version pinning; the R worker reports installed packages, Python probes optional imports.
* **Fallback chains** per family: Arrow → JSON → proxy; plm → data.frame + attribute; geopandas → pandas + shapely; xts → zoo → data.frame.
* **Registry** (`compatibility/*.yaml`): tested versions, preferred paths, known issues. Not a whitelist.
* Tested: Python 3.11 / pandas 3.0 / numpy 2.4 / pyarrow 25 / polars 1.44; R 4.5.2 with arrow, sf, igraph, Matrix, xts, haven, survival, plm, duckdb. CI runs the interop suite (both directions) for Python 3.11–3.13 on Linux, macOS and Windows with the current R release, and smoke-tests the built wheel from a clean venv outside the source tree. R minimum: 4.1 (syntax), verified on 4.5.
* Upstream changes are caught by the scheduled compatibility workflow (`compat.yml`) which installs the latest pandas/pyarrow/R packages and reruns the round-trip matrix.
