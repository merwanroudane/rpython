"""Write the compatibility registry, CHANGELOG, CONTRIBUTING, CODE_OF_CONDUCT, LICENSE.

Run: python tools/make_project_files.py
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
files: dict[str, str] = {}

files["src/rpython/compatibility/pandas.yaml"] = """package: pandas
runtime: python
tested_versions: ["2.2", "3.0.5"]
preferred_path: arrow-ipc (>= 5000 rows), json otherwise
notes:
  - pandas 3 default string dtype "str" is preserved distinctly from "string" (StringDtype)
  - float64 NaN is treated as missing (-> R NA) under missing="preserve"
  - PeriodDtype columns travel as ISO period strings with the dtype string for exact reconstruction
fallback: json columns -> proxy
"""
files["src/rpython/compatibility/pyarrow.yaml"] = """package: pyarrow
runtime: python
tested_versions: ["25.0.1"]
preferred_path: Feather v2 (Arrow IPC file) written to the session workdir
notes:
  - dictionary columns keep the ordered flag; the semantic sidecar re-applies levels in R
  - decimal/complex/interval columns fall back to the JSON path
fallback: json
"""
files["src/rpython/compatibility/polars.yaml"] = """package: polars
runtime: python
tested_versions: ["1.44.1"]
preferred_path: DataFrame.to_arrow() -> arrow-ipc; LazyFrame collected only under the memory guard
notes:
  - a polars source comes back as polars on the return trip (tibble on the R side)
"""
files["src/rpython/compatibility/arrow-r.yaml"] = """package: arrow
runtime: r
tested_versions: ["21.0.0"]
preferred_path: arrow::read_feather / write_feather; open_dataset for shared Parquet datasets
notes:
  - int64 columns are re-typed to bit64::integer64 only when values exceed the 32-bit range
  - missing arrow on the R side switches the planner to JSON and Explain Mode says so
"""
files["src/rpython/compatibility/plm.yaml"] = """package: plm
runtime: r
tested_versions: ["2.6-6"]
preferred_path: pdata.frame(index = c(id, time)) when (id, time) keys are unique
known_issues:
  - duplicate keys are rejected by plm -> data.frame + rpython.panel attribute is used instead (reported)
"""
files["src/rpython/compatibility/sf.yaml"] = """package: sf
runtime: r
tested_versions: ["1.0-21"]
preferred_path: WKB (base64 in JSON / binary in Arrow) + CRS as WKT2/EPSG
known_issues:
  - spatial indexes are rebuilt on the target
  - sfg with Z/M dimensions: dimension flag reported, WKB carries the coordinates
"""
files["src/rpython/compatibility/igraph.yaml"] = """package: igraph
runtime: r
tested_versions: ["2.1.4"]
preferred_path: graph_from_data_frame(edges, directed, vertices = nodes)
notes:
  - a non-"weight" weight attribute is aliased to E(g)$weight (igraph convention) and the alias dropped on return
  - integer node ids are restored as Python ints on the return trip
"""
files["src/rpython/compatibility/networkx.yaml"] = """package: networkx
runtime: python
tested_versions: ["3.6.1"]
preferred_path: node/edge tables + features block
notes:
  - MultiGraph keys travel in the "key" column
  - non-scalar node ids (tuples ...) use a reversible id_map
"""
files["src/rpython/compatibility/scipy.yaml"] = """package: scipy
runtime: python
tested_versions: ["1.13.1"]
preferred_path: csc/csr/coo -> Matrix dgC/dgR/dgT with 0-based indices
known_issues:
  - dia/lil/dok/bsr are transported as csc (storage change reported)
"""
files["src/rpython/compatibility/statsmodels.yaml"] = """package: statsmodels
runtime: python
tested_versions: []
preferred_path: results objects stay behind proxies; their tables (.params, .summary().tables) convert as pandas
notes:
  - not exercised in CI yet; the generic path applies
"""
files["src/rpython/compatibility/sklearn.yaml"] = """package: scikit-learn
runtime: python
tested_versions: ["1.7"]
preferred_path: estimators are proxies callable from R (fit/predict); numpy inputs/outputs convert natively
"""
files["src/rpython/compatibility/ggplot2.yaml"] = """package: ggplot2
runtime: r
tested_versions: ["4.0"]
preferred_path: ggplot objects are proxies; printing renders to PNG via the worker device; .save() uses ggsave
"""
files["src/rpython/compatibility/forecast.yaml"] = """package: forecast
runtime: r
tested_versions: ["8.24"]
preferred_path: forecast/Arima results stay as proxies; fitted/forecast ts components convert to pandas via field access
"""
files["src/rpython/compatibility/fixest.yaml"] = """package: fixest
runtime: r
tested_versions: []
preferred_path: fixest objects are proxies; coef()/vcov()/summary() convert to pandas/numpy
notes:
  - not exercised in CI yet; the generic path applies
"""
files["src/rpython/compatibility/numpy.yaml"] = """package: numpy
runtime: python
tested_versions: ["2.4.6"]
preferred_path: json inline (< 50k elements) or arrow-ipc; memory order shipped explicitly
notes:
  - int8/int16/uint8/uint16 widen to R integer; float32 widens to double; dtype restored on round trip
  - uint64 beyond int64 range is shipped as int64 strings (never rounded)
"""

files["CHANGELOG.md"] = """# Changelog

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
"""

files["CONTRIBUTING.md"] = """# Contributing

Thanks for helping make R and Python one workspace.

## Setup

```bash
git clone https://github.com/merwanroudane/rpython && cd rpython
pip install -e ".[dev]"
R -e 'install.packages(c("jsonlite","arrow","data.table","Matrix","xts","zoo","haven","survival","sf","igraph","plm","duckdb","RSQLite","dbplyr","testthat"))'
python -m pytest tests -q            # R-dependent tests are skipped when R is absent
R CMD INSTALL r-package && Rscript -e 'testthat::test_dir("r-package/tests/testthat", package = "rpython")'
```

After editing anything in `r-package/R/`, run `python tools/sync_r.py` (CI checks that the bundled copy is in sync).

## Adding a converter

1. Python: create an `Adapter` subclass in `src/rpython/data/<family>.py` (or call `rp.register_converter`),
   define `detect`, `encode`, `decode`, set `priority` (specific wrappers first) and register it with
   `REGISTRY.register(..., tested=True, limitations=(...))`.
2. R: add `rpx_encode_<family>` / `rpx_decode_<family>` in `r-package/R/` and dispatch on the class / `kind`.
3. Tests: a `Python -> envelope -> Python` round trip in `tests/roundtrip`, live `Python -> R -> Python` and
   `R -> Python -> R` tests in `tests/integration`, and a family-specific equality in `rpython/fidelity.py`.
4. Docs: a row in `docs/data-structures-catalog.md` stating what is preserved and what is not.

## Adding a database adapter

Subclass `DatabaseAdapter` in `src/rpython/database/`, register it in `database/registry.py`, keep
`tested_live=False` unless CI really runs the service, and add the R driver name (`r_package`).

## Style

Typed Python, focused modules, docstrings explaining *why*; no placeholder code in core paths; never claim a
conversion is lossless unless a test validates it. Commits are authored by their human contributors.
"""

files["CODE_OF_CONDUCT.md"] = """# Code of Conduct

This project follows the [Contributor Covenant](https://www.contributor-covenant.org/version/2/1/code_of_conduct/) v2.1.
Be respectful, assume good faith, and report unacceptable behaviour to merwanroudane920@gmail.com.
"""

files["LICENSE"] = """MIT License

Copyright (c) 2026 Merwan Roudane

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

if __name__ == "__main__":
    for rel, text in files.items():
        path = os.path.join(ROOT, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    print("wrote", len(files), "files")
