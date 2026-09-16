# Universal Data Structures Catalog

This page answers, for every object family RPython knows about:

* **What is supported?** (Python side, R side)
* **Which conversion path is used?** — the tier from the priority hierarchy:
  *A* lossless native, *B* lossless standard interchange (Arrow / WKB / DLPack), *C* metadata-preserving adapter,
  *D* lazy/shared representation, *E* native-object proxy
* **Is it lossless?** and **what metadata are preserved?**
* **What happens when no direct mapping exists?**
* **Which optional packages are needed?**
* **Can it be round-tripped?** (`R → Python → R` and `Python → R → Python`) and **saved/reloaded?**

The registry is an optimisation, not a whitelist: any object not listed here falls back to safe
recursive conversion and then to a **native proxy** (the object stays alive in its runtime and
its methods are called remotely). `rpython catalog` prints the live registry of your installation.

Legend: ✓ lossless · ℹ preserved with a documented change · ↻ proxy · — not applicable

---

## Primitives

| Python | R | Path | Preserved | Notes |
|---|---|---|---|---|
| `None` | `NULL` | A | — | in a vector: `NA` |
| `bool`, `np.bool_` | `logical` | A | ✓ | `None`/`pd.NA` → `NA` |
| `int` (32-bit range) | `integer` | A | ✓ | R integer is 32-bit |
| `int` beyond 2³¹, `np.int64`, `np.uint64` | `bit64::integer64` (or character if *bit64* absent) | A | ✓ | shipped as decimal strings, **never rounded**; Explain Mode reports the risk |
| `float`, `np.float64` | `double` | A | ✓ | `nan` → `NaN`, `inf` → `Inf` (see [Missing values](#missing-values)) |
| `np.float32` | `double` | A | ℹ | widened; dtype restored on round trip |
| `complex` | `complex` | A | ✓ | |
| `str` | `character` | A | ✓ | UTF-8 end to end (Arabic, French, CJK tested) |
| `bytes`, `bytearray`, `memoryview` | `raw` | A | ✓ | base64 on the wire |
| `decimal.Decimal` | `character` with class `rpx_decimal` | C | ℹ | exact string, no float rounding |
| `fractions.Fraction` | class `rpx_fraction` | C | ℹ | |
| `uuid.UUID` | class `rpx_uuid` | C | ℹ | |
| `datetime.date` | `Date` | A | ✓ | |
| aware `datetime`/`pd.Timestamp` | `POSIXct` with `tzone` | A | ✓ | instant **and** zone preserved |
| naive `datetime` | `POSIXct` tz `"UTC"` + attribute `rpython_naive` | A | ℹ | wall-clock kept, never reinterpreted; returns naive |
| `timedelta`, `pd.Timedelta` | `difftime` (secs) | A | ✓ | |
| `enum.Enum` | value + class metadata | A | ✓ | enum restored on round trip |

Round trip: both directions. Save: any tabular/JSON format.

## Missing values

| Source | R | Back in Python |
|---|---|---|
| `None`, `pd.NA`, `pd.NaT` | `NA` | `None` in collections; `NaN` in float64 columns/arrays (pandas semantics); `pd.NA` in nullable dtypes |
| `float('nan')` scalar / numpy array | `NaN` | `nan` |
| `NaN` in a **pandas float64 column** | `NA` (pandas treats NaN as missing) — `rp.config(missing="nan")` keeps `NaN` | `NaN` |
| R `NA` only | | `NaN` in float64 (numpy-native) |
| R `NA` **and** `NaN` in the same vector | | `pandas Float64` array keeps them distinct (reported in Explain Mode) |
| `Inf`, `-Inf` | `Inf`, `-Inf` | `inf`, `-inf` |

Nothing is collapsed silently: every decision is visible in `rp.explain_last()`.

## Collections

| Python | R | Path | Notes |
|---|---|---|---|
| homogeneous `list`/`tuple`/`set` of scalars | atomic vector (+ container metadata) | A | container type restored on round trip |
| heterogeneous `list` | unnamed `list` | A | recursive |
| `dict` (str keys) / `OrderedDict` / `defaultdict` | named `list` | A | key order kept; non-string keys travel as encoded keys |
| `namedtuple`, `dataclass`, `attrs`, `pydantic` | named `list` + class path | A | rebuilt on round trip |
| self-referential structures | reference marker | A | cycle detected, never infinite recursion |
| generators / iterators | proxy | E | never materialised; R pulls values through the proxy |
| R `pairlist`, `expression`, `call` | character (deparsed) via forced conversion, else proxy | C/E | |
| R `environment`, `R6`, `S4`, closures | proxy | E | fields/slots/methods reachable from Python |

## Arrays and tensors

| Python | R | Path | Preserved |
|---|---|---|---|
| `np.ndarray` (any dims) | `matrix` / `array` | A (JSON) / B (Arrow ≥ 50 k elements) | shape ✓ values ✓ dtype ℹ (restored) |
| memory order C / F, non-contiguous views | column-major array | A | order shipped explicitly, **no silent transpose**; `a[i, j]` ↔ `a[i+1, j+1]` |
| `np.ma.MaskedArray` | array with `NA` | A | mask ✓ |
| `np.matrix` | `matrix` | A | compat only |
| `torch.Tensor` (CPU/GPU) | array | B | dtype/device/`requires_grad` reported; GPU → CPU copy **reported** |
| `jax`, `cupy` arrays | array | B | via `__array__` |
| `dask.array` | array (guarded) | D | memory guard: refuses above threshold |
| R `dimnames` | `LabeledArray` (`.dimnames`, `.to_xarray()`) | A | names ✓ |

Round trip: both directions. Save: `.npy`, `.npz`, `.rds`, `.rpx`.

## Sparse matrices

Requires `scipy` (Python) and `Matrix` (R).

| Python | R | Notes |
|---|---|---|
| `csc_matrix` | `dgCMatrix` | format ✓ indices ✓ values ✓ dimnames ✓ |
| `csr_matrix` | `dgRMatrix` | |
| `coo_matrix` | `dgTMatrix` | |
| `dia`/`lil`/`dok`/`bsr` | `dgCMatrix` | format changed ℹ (reported) |
| logical sparse | `lgCMatrix` | |
| `dsCMatrix` (symmetric) → | full `csc` | expanded ℹ (scipy has no symmetric flag) |
| `torch` sparse COO | `dgTMatrix` | |
| pandas `SparseDtype` | `dgTMatrix` | |

Never densified without `rp.to_dense(m, allow=True)`; the memory guard estimates the dense size first.

## Tabular data

| Python | R | Path |
|---|---|---|
| `pandas.DataFrame` | `data.frame` (`tibble`/`data.table` identity kept when it came from R) | A (JSON) / **B Arrow IPC** ≥ 5 000 rows |
| `pandas.Series`, `pandas.Index` | vector (named when indexed) | A |
| `polars.DataFrame` | `tibble` | B |
| `polars.LazyFrame` | collected only under the memory guard (`rp.lazy()` keeps it lazy) | D |
| `pyarrow.Table` / `RecordBatch` | `tibble` | B |
| `pyarrow.dataset.Dataset` | `arrow::open_dataset()` on the **same files** | D — 0 copies |
| `dask.DataFrame` | guarded compute | D |
| dataframe-interchange / `__arrow_c_stream__` objects (Modin, cuDF, …) | `tibble` | B |
| numpy structured array | `data.frame` | A |

Preserved: column order & names (Unicode, spaces, duplicates via reversible suffixes) ✓ · dtypes incl. nullable
`Int64`/`boolean`/`string`/`str` ✓ · categories **with levels and order** ✓ · datetime tz ✓ ·
`Period`, `Interval`, `timedelta`, `date`, list and struct columns ✓ · index/MultiIndex (carried as leading
columns, restored) ✓ · `df.attrs` (JSON-serialisable) ✓ · row names ✓.

## Arrow nested types

`list`, `large_list`, `fixed_size_list`, `struct`, `map`, dictionary, decimal, timestamp/date/time/duration
travel through Arrow IPC; nested columns are **not flattened** (R receives list / data.frame columns).
Schema metadata is kept in `meta.schema_metadata`. Decimal, complex and interval columns use the JSON path.

## Time series

`rp.timeseries(df, time="date", freq="M", ids=[...])` or automatic for `DatetimeIndex` / `PeriodIndex`.

| Form | R | Python |
|---|---|---|
| regular univariate/multivariate (freq 1/4/12/52/…) | `ts` / `mts` | `Series`/`DataFrame` with `DatetimeIndex`+freq or `PeriodIndex` |
| irregular, tz-aware, duplicates | `xts` (or `zoo`) | `DatetimeIndex` |
| grouped / hierarchical (`ids=`) | `tsibble` | long DataFrame + metadata |
| R `ts` with unusual frequency | | numeric time index (no calendar anchor) ℹ |

Preserved: values ✓ time index ✓ frequency ✓ timezone ✓ missing periods (counted, kept as gaps) ✓
duplicates (counted, kept) ✓ series identity ✓ seasonal period ✓. Mixed-frequency sets: `rp.mixed_frequency()`.

## Panel / longitudinal, cross-section, repeated cross-section, hierarchical

`rp.panel(df, id=, time=)`, `rp.cross_section()`, `rp.repeated_cross_section(df, wave=)`, `rp.hierarchical(df, levels=)`.
R: `plm::pdata.frame` (when *plm* is installed and keys are unique) or `data.frame` + `rpython.panel` attribute.
Python: `(id, time)` MultiIndex DataFrame (what `linearmodels` expects) with the block in `df.attrs["rpython"]["panel"]`.

Preserved: entity/time keys ✓ balance ✓ gaps ✓ duplicates ✓ ordering ✓ frequency ✓ weights/cluster/strata/cohort roles ✓.
Auto-detection only ever produces a *suggestion* in Explain Mode.

## Survey / labelled data

`rp.labelled(df, variable_labels=, value_labels=, missing_values=, weight=, strata=, psu=, fpc=, replicate_weights=)`
or `LabelledFrame.from_pyreadstat(df, meta)`. R: `haven::labelled` / `labelled_spss` columns + `rpython.survey`
design attribute (ready for `survey::svydesign`). Stata/SPSS/SAS files via `rp.load("x.dta")` (needs `pyreadstat`).

## Survival / event history

`rp.survival(df, time=, event=, time2=, type="right|left|interval|counting|mstate", id=, strata=)` ↔ `survival::Surv`
(covariates travel as an attached data.frame). Python helpers `.to_lifelines()`, `.to_sksurv()`.

## Spatial vector

Needs `shapely` (+ `geopandas` for a `GeoDataFrame`, `pyproj` for CRS objects) and `sf`.

| Python | R | Preserved |
|---|---|---|
| `GeoDataFrame`, `GeoSeries`, shapely geometry, `rp.spatial(df, lon=, lat=, crs=)` | `sf` / `sfc` / `sfg` | geometry (WKB) ✓ geometry type ✓ CRS (WKT2 + EPSG) ✓ active + extra geometry columns ✓ empty/missing geometries ✓ attributes ✓ feature order ✓; spatial index rebuilt ℹ |

The CRS is **never assumed** (no silent EPSG:4326) and coordinates are never transformed.

## Raster / grid

`rp.raster("dem.tif")` → **lazy file reference** opened by `terra::rast()` / `rasterio` on each side (0 copies);
`rp.Raster(array, transform, crs, nodata)` for in-memory grids (memory-guarded). Extent, resolution, bands, CRS,
geotransform, nodata, band/time coordinates preserved. NetCDF/Zarr: `rp.netcdf(path)` ↔ `stars`/`ncdf4`.

## Spatiotemporal

`rp.spatiotemporal(gdf, time=, id=, kind="spatial_panel|trajectory|events|spatial_timeseries")` carries **both**
the spatial block (geometry, CRS) and the temporal/panel block; neither is dropped.

## Networks / graphs / trees / knowledge graphs

Needs `networkx` (or `python-igraph`) and `igraph` (R).

| Python | R |
|---|---|
| `Graph`, `DiGraph`, `MultiGraph`, `MultiDiGraph`, `igraph.Graph`, `rp.network(edges, nodes, directed=)` | `igraph` (also accepts `tidygraph`, `network`) |

Preserved: node ids (int/str; other types via reversible map) ✓ direction ✓ **parallel edges** ✓ self loops ✓ weights ✓
node/edge/graph attributes ✓ bipartite type ✓ layers/time/sign columns ✓; DAG/tree flags reported.
Triples/quads: `rp.triples_to_network()`; SPARQL bindings keep term type, datatype and language.
`torch_geometric`/DGL objects stay behind proxies.

## Text / NLP

`rp.dtm(matrix, docs, terms, weighting)` ↔ `quanteda::dfm` (or `Matrix` with dimnames); `rp.corpus(df, text=, doc_id=)`
↔ `quanteda::corpus` (or data.frame). Vocabulary, document ids, sparsity and weighting kept. spaCy/HF objects → proxy.

## Media

`rp.Image` (channel order, layout, dtype, colour space, orientation — channels **never swapped**), `rp.audio(samples,
sample_rate=)` (the sample rate always travels), `rp.video(path)`/`rp.image(path)`/`rp.audio(path)` lazy references with
probed metadata (ffprobe/PIL/soundfile when available).

## Scientific multidimensional (xarray)

`xarray.DataArray`/`Dataset` ↔ R array with `dimnames` + `rpython.coords`/`rpython.attrs` attributes (or `stars`).
Dims, coordinates, attrs, units, calendar preserved. Chunked/file-backed datasets are shared as **NetCDF references**.

## Economics

`rp.io_table`, `rp.trade_matrix` (named rows/cols, orientation, units, year) · `rp.spatial_weights` (style, kind, islands;
↔ `spdep::listw`) · `rp.dyadic` (directed pairwise tables ↔ networks) · `rp.mixed_frequency` · `rp.vintages` ·
`rp.experiment` (treatment/outcome/unit/time/cohort roles, never inferred) · `rp.simulation` (RNG equivalence
explicitly **not** claimed).

## Bioinformatics, chemistry, phylogenetics, functional data

No dedicated converters ship yet; these ecosystems go through the generic paths: `SummarizedExperiment`/`AnnData`-like
objects stay behind proxies with their assays reachable as tables/sparse matrices, Newick/SDF/SMILES travel as strings
with their class marker, `fda` basis objects as proxies. Adapters can be registered without touching the core
(`rp.register_semantic_adapter`, `rpx_register_encoder`).

## Databases

Connection references never contain secrets (they live in a process-local vault; R receives an env-var name through
an in-memory message). Relations are lazy; parameters are always bound.

| Backend | Python client | R side | Live-tested |
|---|---|---|---|
| SQLite | stdlib | `RSQLite` | ✓ |
| DuckDB (+ Parquet/Arrow lakes) | `duckdb` | `duckdb` / `arrow` | ✓ |
| PostgreSQL/Timescale/QuestDB/Cockroach, MySQL/MariaDB, SQL Server, Oracle, Db2, Redshift, Snowflake, BigQuery, Databricks, ClickHouse, Trino | SQLAlchemy dialects | `RPostgres`, `RMariaDB`, `odbc`, `bigrquery` | interface-tested |
| MongoDB | `pymongo` | `mongolite` | fakes |
| Redis | `redis` | `redux` | fakes |
| Neo4j/Memgraph, SPARQL | `neo4j`, `SPARQLWrapper` | `neo4r`, `SPARQL` | fakes |
| InfluxDB | `influxdb_client` | — (Arrow materialisation) | fakes |
| PostGIS, SpatiaLite, DuckDB-spatial | SQL + WKB | `sf` | interface |
| qdrant/chroma/milvus/weaviate/pinecone | vendor clients | — | interface |
| Elasticsearch/OpenSearch | vendor clients | `elastic` | fakes |
| Delta Lake, Iceberg | `deltalake`, `pyiceberg` | `arrow` | interface |

## Custom objects and proxies

Anything else: `rp.introspect(obj)` (no properties evaluated) → proxy. From Python, an R proxy offers
`obj.method()`, `obj.field`, `obj.methods()`, `obj.to_python()`, `obj.save("x.rds")`. From R, a Python proxy offers
`obj$attr`, `obj$method()`, `py_to_r(obj)`. Round trip returns the **same** object.

## Persistence

`rp.save(obj, path)` chooses the writer by family and extension; lossy formats (CSV, Excel, JSON) warn and write a
`.rpx.json` sidecar that `rp.load()` uses to restore dtypes, categories, tz, index and semantic blocks. `.rpx` bundles
(`manifest.json`, `semantic_metadata.json`, `portable/`, `native/`) hold anything, including R-native objects.
