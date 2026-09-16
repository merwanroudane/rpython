# RPython — Universal Data Types, Structures, Domains & Databases Interoperability Specification

> **Status:** MANDATORY extension of `MASTER_PROMPT.md`  
> **Repository:** https://github.com/merwanroudane/rpython  
> **Author / project owner:** Dr. Merwan Roudane  
> **Rule:** Claude must read and implement this file together with `MASTER_PROMPT.md`. Neither file is optional.

---

# 1. PURPOSE

RPython must not be designed only around `data.frame ↔ pandas.DataFrame`, time series, panel data, or ordinary statistical tables.

It must be designed as a **general-purpose, high-level, bidirectional interoperability system for the broadest practical set of data types, data structures, scientific objects, domain-specific structures, database-backed structures, and computational objects used across R and Python**.

The target is:

```text
R object / structure / dataset / database / scientific object
                         ↕
            RPython semantic interchange layer
                         ↕
Python object / structure / dataset / database / scientific object
```

The system must aim for **complete semantic exchange**, not merely value copying.

For every supported object family, RPython must attempt to preserve the object’s relevant meaning, including where applicable:

- values
- scalar type
- container type
- shape
- dimensions
- dimension order
- names
- row names
- column names
- indexes
- hierarchical indexes
- keys
- primary keys
- foreign keys
- constraints
- schema
- nullable semantics
- units
- labels
- category levels
- category ordering
- coding schemes
- attributes
- metadata
- provenance
- data source
- encoding
- timezone
- frequency
- coordinates
- coordinate reference system
- topology
- graph direction
- edge multiplicity
- node/edge attributes
- weights
- spatial geometry type
- raster resolution
- raster extent
- nodata values
- chunking
- compression
- sparse representation
- tensor device/dtype where meaningful
- missing-value semantics
- storage format
- model class
- package/class origin
- laziness/query plan where feasible

The library must never silently discard semantically important information simply because the receiving language uses a different native representation.

---

# 2. FUNDAMENTAL RULE: COMPLETE WHEN POSSIBLE, PROXY WHEN NECESSARY

For each object, choose the safest of the following paths:

```text
A. Lossless native conversion
B. Lossless standard interchange representation
C. Metadata-preserving adapter
D. Lazy/shared representation
E. Native object proxy
F. Explicitly documented lossy conversion, only when user policy allows
```

Never choose a lossy conversion merely because it is easy to implement.

If a direct equivalent does not exist:

1. keep the source object alive when possible,
2. expose a native-object proxy,
3. preserve class/package/runtime metadata,
4. allow method calls to execute in the source runtime,
5. explain why a native conversion was not used.

Core rule:

> **Unknown structure ≠ unsupported structure.**

Unknown structures should pass through introspection, generic conversion, standard interchange representations, or proxy fallback.

---

# 3. UNIVERSAL DATA MODEL

Extend the Semantic Data Layer from `MASTER_PROMPT.md` into a general universal model.

The internal representation should be capable of describing at least:

```text
SemanticObject
├── identity
│   ├── source_runtime
│   ├── source_package
│   ├── source_class
│   └── object_id / proxy_handle
├── logical_type
├── physical_type
├── schema
├── shape / dimensions
├── axes / indexes
├── metadata
├── semantic_roles
├── missingness
├── encoding
├── storage
├── domain_semantics
├── conversion_history
├── fidelity_report
└── fallback_strategy
```

Do not make this object heavy for ordinary users. It may be internal and lazily constructed.

---

# 4. SCALAR AND PRIMITIVE TYPES

Support and test bidirectional semantics for all common primitive families.

## Python-side primitives

- `None`
- `bool`
- arbitrary-precision `int`
- `float`
- `complex`
- `decimal.Decimal`
- `fractions.Fraction` where meaningful
- `str`
- `bytes`
- `bytearray`
- `memoryview`
- enum values
- UUIDs
- date/time primitives
- NumPy scalar dtypes

## R-side primitives

- logical
- integer
- double/numeric
- complex
- character
- raw
- `NA` variants
- `NaN`
- `Inf`, `-Inf`
- `NULL`

## Numeric precision

Detect and report risks involving:

- Python arbitrary-precision integers vs R integer/double limits
- `int64`
- unsigned integers
- float32 vs float64
- long double availability
- Decimal/fixed decimal
- complex precision

Use Arrow decimal or explicit encoded representation where useful.

Do not silently round large identifiers.

---

# 5. BASIC CONTAINERS AND COLLECTIONS

Support:

## Python

- list
- tuple
- namedtuple
- dict
- OrderedDict
- defaultdict where meaningful
- set
- frozenset
- dataclass
- attrs objects where reasonable
- Pydantic models where safe and useful
- iterators/generators through explicit materialization or proxy policy

## R

- atomic vectors
- named vectors
- lists
- named lists
- pairlists where relevant
- language/call objects when needed
- expressions
- environments via proxy only unless a safe mapping exists

Preserve names and nesting.

Nested containers must support recursive conversion with cycle detection.

Detect recursive/self-referential structures and use proxy/reference semantics rather than infinite recursion.

---

# 6. MATRICES, ARRAYS, ND ARRAYS, TENSORS

Support and test:

## Python ecosystems

- NumPy ndarray
- NumPy matrix only for compatibility
- NumPy masked arrays
- SciPy dense/sparse matrices
- xarray `DataArray`
- xarray `Dataset`
- PyTorch Tensor
- TensorFlow Tensor when installed
- JAX arrays when installed
- CuPy arrays when installed
- Dask arrays where feasible

## R ecosystems

- matrix
- array
- Matrix package sparse matrices
- DelayedArray where feasible
- torch tensors in R
- stars arrays where appropriate
- package-specific multidimensional arrays

Preserve:

- shape
- dimension names
- axis names
- axis order
- dtype
- missing/masked state
- sparse vs dense representation
- chunking/laziness when feasible
- device (`CPU`, `CUDA`, etc.) only when a compatible target exists

## Memory layout

R and many numerical R objects use column-major conventions; NumPy often defaults to row-major C order.

RPython must explicitly account for:

- C order
- Fortran order
- strides
- contiguous/non-contiguous arrays

Never silently transpose or reorder axes.

Expose conversion diagnostics for memory-order changes when relevant.

---

# 7. SPARSE DATA

Sparse data must be first-class, not converted to dense by default.

Support concepts such as:

- CSR
- CSC
- COO
- DIA
- block sparse
- symmetric sparse matrices
- sparse logical matrices

Potential ecosystems:

- Python `scipy.sparse`
- pandas sparse types
- R `Matrix`
- sparse model matrices

Preserve:

- shape
- values
- row/column indices
- sparse format when possible
- symmetry/triangular properties where represented
- dimnames

Never densify large sparse matrices without explicit user permission and a memory estimate.

---

# 8. TABULAR DATA — BROAD SUPPORT

Support more than `pandas.DataFrame` and `data.frame`.

## Python tabular structures

- pandas DataFrame
- pandas Series
- Polars DataFrame
- Polars LazyFrame
- PyArrow Table
- PyArrow RecordBatch
- PyArrow Dataset
- DuckDB relations
- Dask DataFrame where feasible
- Modin or other compatible dataframe protocols when practical
- dataframe interchange protocol (`__dataframe__`) where useful

## R tabular structures

- data.frame
- tibble
- data.table
- Arrow Table/RecordBatch/Dataset
- DuckDB/dbplyr-backed tables
- lazy database tables
- package-specific tabular objects

Preserve:

- schema
- names
- column order
- dtypes
- nullability
- row identifiers/index meaning
- categorical semantics
- nested columns/list columns
- extension types when possible
- lazy query state where possible

---

# 9. ARROW NESTED AND COMPLEX TYPES

Use Arrow where appropriate to support language-neutral schemas including:

- primitive arrays
- strings/binary
- decimal
- timestamp/date/time
- duration
- dictionary/categorical
- list
- large list
- fixed-size list
- struct
- map
- union where supported
- nested struct/list combinations

Preserve custom field/schema metadata when safe.

Do not flatten nested Arrow data merely to fit a DataFrame if a richer representation can be preserved.

---

# 10. TIME SERIES — ALL MAJOR FORMS

Time series are already required by `MASTER_PROMPT.md`; extend coverage beyond basic regular univariate series.

Support semantics for:

- regular univariate time series
- regular multivariate time series
- irregular time series
- multiple-frequency series
- seasonal series
- high-frequency/intraday series
- tick data
- event-time series
- panel time series
- hierarchical time series
- grouped time series
- functional time series
- long-format time-series tables
- wide-format time-series matrices
- streaming time series
- interval-valued time series where practical

R ecosystems may include:

- `ts`
- `mts`
- `zoo`
- `xts`
- `tsibble`
- package-specific forecast/time-series classes

Python ecosystems may include:

- pandas Series/DataFrame with DatetimeIndex/PeriodIndex
- xarray
- sktime structures
- darts structures
- statsmodels data
- package-specific forecasting objects

Preserve:

- timestamps
- period semantics
- frequency
- timezone
- seasonal period
- irregularity
- missing intervals
- duplicate timestamps policy
- value columns
- series identifiers
- hierarchy/group keys

---

# 11. CROSS-SECTIONAL DATA

Treat cross-sectional data as an explicit semantic form when useful.

Preserve:

- observation IDs
- weights
- strata
- clusters
- sampling design metadata
- units
- labels
- categorical coding

Support survey/economic datasets where rows may have sampling and design meaning beyond a generic table.

---

# 12. PANEL / LONGITUDINAL DATA

Retain all requirements from the main prompt and extend to:

- balanced panel
- unbalanced panel
- short panel
- long panel
- dynamic panel
- rotating panel
- pseudo-panel/cohort panel
- repeated observations
- multi-index panels
- nested panels
- multi-level longitudinal data
- irregular observation intervals

Preserve:

- entity IDs
- time IDs
- cohort/group IDs
- panel ordering
- duplicate keys
- gaps
- balance state
- frequency
- observation weights
- cluster IDs

---

# 13. REPEATED CROSS-SECTIONS

Represent repeated cross-sections distinctly from true panel data.

Preserve:

- survey/wave/time indicator
- independent observation identity
- sampling strata
- weights
- cluster variables
- harmonized variable metadata

Never incorrectly infer panel identity simply because the same categories appear over time.

---

# 14. HIERARCHICAL / MULTILEVEL / NESTED DATA

Support structures such as:

- students within schools
- patients within hospitals
- employees within firms
- regions within countries
- repeated measures within persons
- crossed/random-effects structures

Preserve:

- level identifiers
- nesting relationships
- crossed-group relationships
- group ordering
- random-effect grouping semantics when represented

Allow conversion to/from tables without discarding grouping metadata.

---

# 15. SURVEY DATA AND LABELLED DATA

Survey datasets require metadata beyond values.

Support concepts common in:

- R `haven`
- labelled vectors
- survey package objects
- Python pandas/pyreadstat ecosystems

Preserve where possible:

- variable labels
- value labels
- user-defined missing values
- tagged missing values
- weights
- strata
- PSU/cluster IDs
- finite population corrections
- replicate weights
- survey design metadata

Support file families:

- Stata
- SPSS
- SAS

Avoid converting labelled numeric codes to plain numbers without metadata.

---

# 16. EVENT HISTORY / SURVIVAL DATA

Support survival/event-history semantics.

Potential concepts:

- start time
- stop time
- censoring indicator
- event type
- competing risks
- recurrent events
- left truncation
- interval censoring
- subject ID
- strata

R structures may include `Surv` and package-specific survival objects.

Python structures may include pandas-based survival tables and objects from `lifelines`, `scikit-survival`, or other packages.

If there is no safe native equivalent, retain a semantic wrapper or proxy.

---

# 17. SPATIAL / GEOSPATIAL VECTOR DATA

Spatial data must be first-class.

Support major geometry families:

- Point
- MultiPoint
- LineString
- MultiLineString
- Polygon
- MultiPolygon
- GeometryCollection
- empty geometries
- Z/M dimensions where ecosystem support exists

Relevant ecosystems include:

## R

- `sf`
- `sfc`
- `sfg`
- legacy `sp` objects when encountered

## Python

- GeoPandas `GeoDataFrame`
- GeoPandas `GeoSeries`
- Shapely geometries
- PyProj CRS objects

Preserve:

- geometry
- active geometry column
- multiple geometry columns where supported
- geometry type
- CRS
- EPSG/WKT/PROJ representation
- axis ordering
- dimensionality
- precision information where relevant
- spatial index metadata only if meaningful/reconstructible
- feature attributes

Use standard representations such as WKB/WKT/GeoArrow where beneficial, but do not lose CRS.

Never silently assume EPSG:4326.

Never silently transform coordinates during conversion unless explicitly requested.

---

# 18. RASTER / GRID / EARTH OBSERVATION DATA

Support raster and gridded structures.

Potential R ecosystems:

- `terra`
- `raster`
- `stars`

Potential Python ecosystems:

- rasterio
- rioxarray
- xarray
- GDAL-backed structures

Preserve:

- extent/bounds
- resolution
- dimensions
- bands/layers
- CRS
- geotransform
- nodata value
- masks
- units
- time/band coordinates
- chunking
- lazy/on-disk behavior

Do not materialize massive rasters into RAM unless required.

Prefer shared files, GDAL-compatible representations, xarray/Arrow-like metadata, or proxy/lazy adapters.

---

# 19. SPATIOTEMPORAL DATA

Support combined space-time semantics:

- spatial panel data
- moving objects
- trajectories
- repeated spatial observations
- raster time stacks
- point events over time
- spatial time series

Preserve both:

- temporal semantics
- spatial CRS/geometry semantics

No conversion may preserve one while silently dropping the other.

---

# 20. POINT PATTERN / TRAJECTORY / MOVEMENT DATA

Support semantic adapters for:

- point processes
- spatial point patterns
- GPS tracks
- trajectories
- movement paths
- origin-destination records
- mobility data

Preserve IDs, time order, coordinates, CRS, and segment relationships.

---

# 21. NETWORK / GRAPH DATA — FIRST-CLASS

All major graph/network families must be considered.

Potential R ecosystems:

- `igraph`
- `network`
- `tidygraph`
- `graph`/Bioconductor structures

Potential Python ecosystems:

- NetworkX
- python-igraph
- graph-tool when available
- PyTorch Geometric objects via adapters/proxies
- DGL objects via adapters/proxies

Support semantic graph families:

- undirected graph
- directed graph
- multigraph
- multidigraph
- weighted graph
- unweighted graph
- signed network
- attributed network
- bipartite/two-mode network
- multipartite network
- multilayer/multiplex network
- temporal/dynamic network
- evolving network
- spatial network
- hypergraph when supported
- knowledge graph
- tree
- forest
- DAG
- citation network
- social network
- economic input-output network
- trade network
- financial network
- supply-chain network
- transportation network

Preserve:

- node IDs
- node types
- node attributes
- edge IDs where needed
- source/target
- direction
- parallel edges
- self loops
- edge attributes
- weights
- signs
- timestamps
- layers
- bipartite membership
- graph-level attributes
- ordering only when semantically meaningful

Do not automatically collapse a multigraph to a simple graph.

Do not lose edge direction.

Do not coerce non-string node IDs without reversible mapping.

---

# 22. TREES, HIERARCHIES, DAGs AND TAXONOMIES

Support hierarchical structures including:

- rooted tree
- unrooted tree
- dendrogram
- phylogenetic tree
- taxonomy
- ontology DAG
- dependency graph
- organizational hierarchy

Preserve topology, labels, branch lengths/weights where present, root information, node/edge metadata.

Use Newick/GraphML/JSON-like standards only when they preserve required semantics.

---

# 23. KNOWLEDGE GRAPHS / RDF-LIKE STRUCTURES

Support or provide adapters for:

- triples
- quads
- subject-predicate-object
- named graphs
- ontology terms
- URI/IRI identifiers
- literals with datatype/language

Potential formats/protocols:

- RDF
- Turtle
- JSON-LD
- N-Triples
- SPARQL-backed data

Do not flatten RDF identifiers and typed literals into ambiguous strings.

---

# 24. TEXT / NLP DATA

Support text data beyond plain character vectors.

Structures may include:

- corpus
- document collection
- tokens
- token sequences
- sentence boundaries
- document-term matrix
- term-document matrix
- sparse bag-of-words matrices
- TF-IDF matrices
- n-gram structures
- linguistic annotations
- entity spans
- dependency parses
- embeddings

Potential R ecosystems:

- quanteda
- tm
- tidytext
- text2vec

Potential Python ecosystems:

- pandas/text columns
- scikit-learn text matrices
- spaCy docs/spans via proxy/adapters
- NLTK structures
- Hugging Face datasets/tokenizer outputs

Preserve:

- document IDs
- token offsets
- vocabulary mapping
- sparse structure
- feature names
- encoding
- language metadata when available

---

# 25. IMAGE DATA

Support practical exchange of image objects when installed ecosystems permit.

Representations may include:

- encoded image bytes
- NumPy array
- PIL Image
- OpenCV matrix
- R raster/magick image objects

Preserve:

- width/height
- channel count/order
- dtype/bit depth
- color space when known
- alpha channel
- orientation metadata where relevant
- spatial/georeferencing metadata for geospatial imagery

Do not silently swap RGB/BGR channels.

---

# 26. AUDIO DATA

Support practical adapters for:

- waveform arrays
- sample rate
- channels
- bit depth
- time axis
- spectrograms
- feature matrices

Do not exchange only the raw numeric vector while dropping the sample rate.

---

# 27. VIDEO DATA

For large video objects, prioritize proxy/file/streaming representations rather than copying frames blindly.

Preserve metadata such as:

- codec/container where relevant
- frame rate
- timestamps
- dimensions
- audio tracks where applicable
- frame indexing

Use lazy references to source files/streams when appropriate.

---

# 28. FUNCTIONAL DATA

Support functional-data-analysis representations where practical:

- functions observed on grids
- basis expansions
- coefficients
- basis metadata
- functional curves
- functional time series

Potential ecosystems include R `fda` and Python FDA packages.

Preserve domain grids/basis definitions, not only coefficient matrices.

---

# 29. ECONOMIC / ECONOMETRIC SPECIAL DATA

Economics is a priority domain, but must live inside the broader universal system.

Support semantic handling for:

- macroeconomic time series
- microeconomic cross sections
- household surveys
- firm-level data
- panel/longitudinal data
- repeated cross sections
- pseudo-panels
- cohort data
- input-output tables
- social accounting matrices
- trade matrices
- bilateral flow data
- origin-destination matrices
- financial return series
- yield curves
- term structures
- order-book/high-frequency data
- event-study data
- treatment/control causal datasets
- staggered-adoption DID data
- duration/unemployment spell data
- spatial econometric data
- spatial weights matrices
- regional panels
- gravity-model dyads
- country-pair data
- network economic data
- firm ownership networks
- supply-chain networks
- macroeconomic vintages / real-time datasets
- mixed-frequency datasets

Preserve identifiers, vintages, units, seasonality, frequency, economic labels, weights, and structural keys.

---

# 30. DYADIC / PAIRWISE / RELATIONAL DATA

Support data indexed by pairs:

- country-country
- firm-firm
- person-person
- origin-destination
- lender-borrower

Preserve:

- sender/source ID
- receiver/target ID
- directed vs undirected semantics
- time
- relationship type
- weight/value

Provide safe conversion to/from graph structures and long relational tables without losing meaning.

---

# 31. INPUT-OUTPUT / MATRIX ECONOMIC DATA

Support structured economic matrices such as:

- input-output tables
- Leontief matrices
- social accounting matrices
- bilateral trade matrices
- transition matrices
- covariance/correlation matrices
- adjacency/weights matrices

Preserve row/column entity names and semantic orientation.

Never silently reorder rows/columns independently.

---

# 32. SPATIAL WEIGHTS MATRICES

Spatial econometric weights require explicit semantics.

Support:

- binary contiguity
- distance weights
- k-nearest neighbors
- row-standardized matrices
- sparse weights
- directed weights

Preserve:

- region IDs
- normalization/standardization
- zero-neighbor handling
- sparse structure

Potential adapters should recognize common spatial-econometrics packages in R and Python.

---

# 33. MACHINE LEARNING DATA STRUCTURES

Support common ML inputs/outputs:

- feature matrices
- target vectors
- multi-output targets
- sample weights
- group labels
- train/validation/test splits metadata
- sparse features
- categorical features
- preprocessing pipelines via proxy
- model matrices
- embeddings
- prediction arrays
- probability matrices

Do not pretend a trained model is merely data; model objects should generally remain native proxies unless a standardized representation is genuinely appropriate.

---

# 34. DEEP LEARNING DATA STRUCTURES

Support or proxy:

- PyTorch tensors/models/datasets/dataloaders
- R torch tensors/models
- TensorFlow tensors/models when present
- JAX arrays/models where practical

Preserve or report:

- dtype
- shape
- device
- gradient requirement
- layout
- sparse/dense status

Do not move GPU tensors to CPU silently without reporting it.

Complex model graphs should normally remain native objects behind proxies.

---

# 35. SCIENTIFIC MULTIDIMENSIONAL DATA

Support labeled scientific arrays and datasets.

Examples:

- climate data
- meteorological grids
- oceanography
- simulations
- remote sensing
- multidimensional experiments

Potential mappings:

- Python xarray `DataArray` / `Dataset`
- R stars / array-like structures
- NetCDF/HDF-backed objects

Preserve:

- dimensions
- named coordinates
- coordinate variables
- units
- attributes
- calendar where applicable
- chunking/lazy behavior

---

# 36. BIOINFORMATICS / GENOMICS / OMICS

Provide architecture and adapters/proxies for important scientific object ecosystems.

Potential R/Bioconductor objects:

- `SummarizedExperiment`
- `SingleCellExperiment`
- `GRanges`
- expression matrices
- assay collections
- genomic ranges

Potential Python objects:

- AnnData
- pandas/NumPy/SciPy sparse matrices
- genomic interval structures

Preserve:

- assays/matrices
- row metadata
- column metadata
- feature IDs
- sample IDs
- genomic coordinates
- annotations
- sparse representation
- layers
- embeddings
- provenance

Do not flatten complex multi-assay objects into a single table.

---

# 37. MEDICAL / CLINICAL DATA

Support semantic wrappers/adapters for:

- longitudinal patient data
- event records
- repeated measurements
- survival outcomes
- coded categorical variables
- clinical tables
- laboratory panels

Avoid embedding sensitive credentials or protected data in logs/diagnostics.

Interoperability must preserve IDs and coding semantics but should not weaken privacy practices.

---

# 38. CHEMISTRY / MOLECULAR DATA

Design an extension path for:

- molecular graphs
- fingerprints
- descriptors
- SMILES strings with explicit semantic type
- SDF/mol structures

Use proxy or standardized exchange formats where native object conversion is unsafe.

---

# 39. PHYLOGENETIC / ECOLOGICAL DATA

Potential structures:

- phylogenetic trees
- community matrices
- species-site matrices
- ecological distance matrices
- spatial ecological observations

Preserve tree topology, branch lengths, labels, taxonomic IDs, matrix dimensions, and metadata.

---

# 40. EXPERIMENTAL / A-B / CAUSAL DATA

Support semantic metadata for:

- treatment assignment
- control group
- strata
- cluster randomization
- observation weights
- experiment arms
- pre/post periods
- event time
- censoring
- propensity scores when stored

Do not embed methodology-specific assumptions into generic conversion, but preserve fields/roles when explicitly declared.

---

# 41. PROBABILISTIC / BAYESIAN OBJECTS

MCMC/posterior objects may be complex and package-specific.

Potential representations include:

- posterior draws arrays
- chains
- iterations
- warmup flags
- parameter dimensions
- diagnostics

Support standardized draw tables/arrays where possible and proxy complete fitted model objects.

Do not reduce a Bayesian model fit to a DataFrame and discard diagnostics.

---

# 42. OPTIMIZATION / OPERATIONS RESEARCH STRUCTURES

Design adapters/proxies for:

- coefficient matrices
- sparse constraints
- bounds
- objective coefficients
- solution vectors
- duals
- solver result objects
- graph/network flow inputs

Preserve variable/constraint names and matrix ordering.

Solver model objects should generally remain native proxies.

---

# 43. SIMULATION / MONTE CARLO DATA

Support:

- repeated simulation results
- random seeds/state metadata when explicitly requested
- multidimensional draws
- experiment IDs
- scenario IDs
- parameter grids

Never claim reproducibility merely because data were transferred; RNG engines differ across R and Python.

Explicitly distinguish data interoperability from RNG equivalence.

---

# 44. DISTRIBUTED / LAZY DATA STRUCTURES

Support safe interoperability concepts for:

- Dask DataFrame/Array
- Spark DataFrames where feasible
- Arrow datasets
- DuckDB relations
- database lazy tables
- R `dbplyr` lazy tables
- disk-backed arrays

Do not automatically `collect()` massive lazy datasets.

Prefer:

- shared source
- query pushdown
- exported logical plan where safe
- Arrow/DuckDB interchange
- proxy/reference

Require explicit confirmation if materialization could exceed configured memory thresholds.

---

# 45. STREAMING DATA

Design an extension path for streaming/iterable data:

- record batches
- generators
- chunked readers
- sockets/streams
- message queues

Do not require the entire stream to be materialized.

Provide chunk/record-batch semantics where possible.

---

# 46. FILE-BACKED DATA

Support references to file-backed data without unnecessary full loads.

Formats may include:

- CSV/TSV
- Excel
- Parquet
- Feather/Arrow IPC
- ORC where ecosystems support it
- JSON/JSON Lines
- XML
- RDS/RData
- Stata
- SPSS
- SAS
- NetCDF
- HDF5
- GeoPackage
- GeoJSON
- Shapefile
- FlatGeobuf
- raster formats such as GeoTIFF
- GraphML/GEXF
- Newick
- image/audio/video formats through adapters

Where a file format cannot preserve full semantics, store sidecar metadata or use a richer format when possible.

---

# 47. DATABASES — UNIVERSAL DATABASE INTEROPERABILITY

Database interoperability must cover more than SQLite/PostgreSQL.

RPython should use an adapter architecture covering broad database categories.

## 47.1 Relational SQL databases

Design support/adapters for common systems such as:

- SQLite
- PostgreSQL
- MySQL
- MariaDB
- Microsoft SQL Server
- Oracle Database
- IBM Db2 where connectors are available
- CockroachDB where compatible

Use R DBI ecosystems and Python SQLAlchemy/DB-API ecosystems where appropriate.

## 47.2 Embedded analytical databases

- DuckDB
- SQLite
- other compatible embedded engines

DuckDB should be considered an important interchange engine because both R and Python can operate on shared Parquet/Arrow/database sources.

## 47.3 Cloud warehouses / analytical databases

Provide an adapter strategy for systems such as:

- BigQuery
- Snowflake
- Amazon Redshift
- Databricks SQL / lakehouse systems
- ClickHouse
- Trino/Presto-compatible systems
- cloud-hosted PostgreSQL-compatible warehouses

Do not hard-code cloud credentials.

## 47.4 Document databases

Provide adapter/proxy strategies for:

- MongoDB
- CouchDB-like document stores
- JSON document stores

Preserve nested document structure and IDs.

## 47.5 Key-value databases

Adapter strategy for:

- Redis
- RocksDB-like stores when accessible
- other key-value stores

Preserve binary vs string keys/values and TTL metadata where relevant.

## 47.6 Graph databases

Adapter strategy for:

- Neo4j
- Memgraph
- other property-graph systems
- RDF triple stores through SPARQL

Preserve node/edge IDs, labels/types, properties, directions, and relationships.

## 47.7 Time-series databases

Adapter strategy for:

- TimescaleDB
- InfluxDB
- QuestDB-like engines
- other time-series stores

Preserve timestamp precision, tags/dimensions, fields/measures, timezone, and frequency semantics where relevant.

## 47.8 Spatial databases

Support spatial database semantics such as:

- PostGIS
- SpatiaLite
- spatial extensions in DuckDB/other engines

Preserve geometry type, SRID/CRS, and spatial columns.

## 47.9 Vector databases / embedding stores

Design adapters for vector-search systems where useful:

- pgvector
- Milvus
- Qdrant
- Weaviate
- Chroma
- Pinecone or similar managed systems if users configure credentials

Preserve:

- vector dtype/dimension
- record ID
- metadata payload
- distance metric configuration where discoverable

## 47.10 Search/index engines

Adapter strategy for:

- Elasticsearch
- OpenSearch
- Solr-like systems

Preserve nested document structures, IDs, mappings/schema where possible.

## 47.11 Data lakes and lakehouses

Support common interchange patterns around:

- Parquet
- Arrow datasets
- Delta Lake
- Iceberg
- Hudi where ecosystem support exists

Focus on shared/lazy access rather than copying full datasets.

---

# 48. DATABASE SEMANTIC CONTRACT

When transferring database-backed data between R and Python, preserve or explicitly report:

- schema/catalog
- table/view identity
- column types
- precision/scale
- nullability
- primary keys
- foreign keys when introspectable
- indexes where relevant
- partitioning
- ordering only when explicitly part of a query
- timezone/timestamp precision
- geometry metadata
- nested/document schema
- query parameters
- laziness/materialization state

Do not assume database row order.

Do not download a 100 GB table merely because the receiving runtime requested a table object.

Use query pushdown and lazy representations.

---

# 49. QUERY INTEROPERABILITY

Provide a high-level abstraction that can share queries safely.

Potential strategies:

- SQL text + bound parameters
- DBI/dbplyr relation proxy
- SQLAlchemy relation/query proxy
- DuckDB relation
- Arrow dataset scanner

Never construct SQL through unsafe string concatenation of user values.

Preserve parameter binding.

---

# 50. SCHEMA / TYPE NEGOTIATION

Implement a universal type-negotiation layer.

Before conversion, determine:

1. source logical type,
2. source physical type,
3. target capabilities,
4. lossless candidates,
5. best interchange backend,
6. estimated copy/memory cost,
7. metadata risks.

Then choose a transfer plan.

The transfer plan should be inspectable in Explain Mode.

---

# 51. DATA PROTOCOLS AND STANDARD INTERCHANGE FORMATS

Where appropriate, use established standards rather than inventing proprietary encodings.

Consider:

- Apache Arrow / C Data Interface
- dataframe interchange protocol
- NumPy buffer/array protocols
- DLPack for tensor exchange when appropriate
- WKB/WKT/GeoArrow for geometry
- Parquet
- JSON/JSON-LD
- GraphML/GEXF where semantics fit
- NetCDF/HDF5 for scientific arrays
- DB protocols/ODBC/JDBC through native adapters

Do not use a standard merely because it exists; verify that it preserves the required semantics.

---

# 52. ZERO-COPY / LOW-COPY STRATEGY

Where both ecosystems support a compatible memory protocol, prefer low-copy transfer.

Potential technologies:

- Arrow C Data Interface
- Arrow C Stream Interface
- DLPack
- memory-mapped files
- shared Parquet/Arrow datasets

But correctness takes priority over zero-copy.

Never advertise zero-copy unless verified for that exact path.

---

# 53. SEMANTIC ROLES

Columns/fields may have roles beyond dtypes.

Allow optional semantic annotations such as:

- ID
- entity
- time
- treatment
- outcome
- weight
- cluster
- strata
- latitude
- longitude
- geometry
- source node
- target node
- edge weight
- event indicator
- duration
- text
- target/class label
- feature
- grouping variable

Do not infer high-stakes semantic roles silently unless confidence is extremely high and the result is presented as a suggestion.

---

# 54. METADATA NAMESPACE

Avoid collisions between library metadata and user metadata.

Use a namespaced internal metadata model.

Never overwrite user attributes with internal bridge fields.

Metadata should be serializable where practical and versioned.

---

# 55. CUSTOM CLASS / EXTENSION TYPES

Support third-party extension types through registries.

Provide APIs similar in spirit to:

```python
rp.register_converter(...)
rp.register_semantic_adapter(...)
rp.register_proxy_adapter(...)
```

and equivalent R companion APIs.

A package author should be able to support a new class without modifying RPython core.

---

# 56. CLASS INTROSPECTION

For unfamiliar objects inspect safely:

## R

- class
- S3 class vector
- S4 class/slots
- R6 class
- attributes
- methods

## Python

- type/module
- dataclass fields
- protocol support
- dataframe protocol
- array protocol
- Arrow protocol
- DLPack support
- relevant safe attributes

Avoid executing arbitrary properties during introspection when they may have side effects.

---

# 57. CONVERSION PRIORITY

Use a predictable hierarchy such as:

```text
1. exact optimized adapter
2. standard language-neutral protocol
3. generic semantic adapter
4. safe recursive conversion
5. native proxy
6. explicit error with solution
```

Do not jump directly from “no custom adapter” to failure.

---

# 58. ROUND-TRIP TEST MATRIX — EXPANDED

Add round-trip tests for each major family:

```text
R → Python → R
Python → R → Python
```

At minimum include:

- primitives
- nested collections
- arrays
- sparse matrices
- DataFrames
- nested Arrow types
- categories/factors
- dates/times/timezones
- regular/irregular time series
- panels
- labelled survey data
- survival data
- spatial vectors
- rasters/lazy raster proxies
- networks
- graph attributes
- text matrices
- scientific arrays
- genomic sparse matrices/adapters
- database lazy relations

For each family define what equality means.

Do not use a single generic `==` rule.

---

# 59. FIDELITY DIMENSIONS

The fidelity report should be able to distinguish:

- value fidelity
- type fidelity
- shape fidelity
- name fidelity
- index fidelity
- metadata fidelity
- semantic fidelity
- storage fidelity
- laziness fidelity
- topology fidelity
- CRS fidelity
- temporal fidelity

Example:

```text
Values:          lossless ✓
Dtypes:          lossless ✓
Index:           lossless ✓
CRS:             lossless ✓
Spatial index:   rebuilt, not preserved ℹ
Storage backend: changed ℹ
```

---

# 60. ECONOMICS TEST SUITE

Create dedicated end-to-end tests for:

- macro time series
- panel regression data
- repeated cross sections
- survey microdata with labels/weights
- spatial panel
- spatial weights matrix
- bilateral trade/dyadic data
- input-output matrix
- financial high-frequency data
- network economics graph
- mixed-frequency macro data

Use small synthetic/test datasets for CI and optional larger benchmarks separately.

---

# 61. OTHER-DOMAIN TEST SUITE

Create representative tests for:

- GIS vector data
- raster data
- network/graph data
- survival data
- text/sparse corpus
- scientific multidimensional arrays
- bioinformatics sparse/annotated data where optional dependencies allow
- image metadata
- audio metadata
- database lazy relations

Mark optional-dependency tests clearly but do not omit the architecture.

---

# 62. PROPERTY-BASED STRUCTURE TESTS

Extend property-based/fuzz tests to generate:

- nested list/struct combinations
- heterogeneous tabular schemas
- duplicate names
- null-heavy structures
- extreme numeric values
- Unicode names
- random graph structures
- sparse matrices
- irregular timestamps
- panel gaps
- geometry collections where libraries permit

Record seeds for reproducibility.

---

# 63. SCALE TESTS

Test behavior at multiple scales:

```text
1 object
10 rows
1,000 rows
100,000 rows
1,000,000+ rows where infrastructure permits
very wide tables
large sparse matrices
large graphs
large rasters through lazy/proxy paths
```

The goal is not to make every CI run enormous; create tiers:

- fast unit
- standard integration
- extended
- nightly/stress

---

# 64. MEMORY SAFETY

Before potentially dangerous materialization/conversion, estimate memory when possible.

Examples:

- sparse → dense
- lazy DB relation → DataFrame
- raster → array
- Dask → pandas
- Arrow dataset → in-memory table

If estimated memory exceeds a configurable threshold:

- select a lazy/chunked strategy,
- or warn and require explicit override.

---

# 65. DATABASE CREDENTIAL SAFETY

Never store passwords/tokens in:

- SemanticObject metadata
- conversion history
- Explain Mode output
- logs
- lock files
- saved bundles
- README examples

Preserve connection identity through safe connection handles/config references, not secret serialization.

---

# 66. SAVING UNIVERSAL STRUCTURES

Persistence must understand the object family.

Examples:

- tabular → Parquet/Arrow/CSV/Excel depending requested semantics
- spatial vector → GeoPackage/GeoParquet/GeoJSON where appropriate
- raster → GeoTIFF/NetCDF/Zarr as appropriate
- graph → GraphML/GEXF/edge-node bundle
- multidimensional scientific data → NetCDF/Zarr/HDF5
- rich native model → native serialization + metadata bundle

Do not make CSV the universal fallback for rich data.

---

# 67. UNIVERSAL BUNDLE FORMAT

Design an optional RPython bundle for objects whose semantics span multiple files/metadata layers.

Potential contents:

```text
manifest.json
semantic_metadata.json
native/
portable/
assets/
environment/
```

The bundle should be versioned and forward-compatible where possible.

Do not invent a bundle format for cases already solved cleanly by open standards.

---

# 68. BEGINNER API MUST REMAIN SIMPLE

All of this complexity must remain behind a high-level interface.

The beginner should still be able to write concepts such as:

```python
rp.to_r(data)
rp.to_python(data)
```

or normally pass objects directly to functions without explicit conversion.

Special semantic declarations should be concise:

```python
panel = rp.panel(df, id="country", time="year")
spatial = rp.spatial(gdf)
network = rp.network(graph)
```

Do not require a user to manually construct the internal universal schema.

---

# 69. AUTO-DETECTION WITH SAFETY

RPython may detect likely semantic structures, but must distinguish:

- confirmed
- strongly inferred
- ambiguous
- unknown

Examples:

```text
Detected: GeoDataFrame with CRS EPSG:4326 — confirmed from object metadata.
```

versus:

```text
Possible panel structure: country × year — suggestion only.
```

Never auto-promote ordinary columns to coordinates, treatment indicators, IDs, or dates when ambiguity can affect analysis.

---

# 70. EXPLAIN MODE — UNIVERSAL DATA

`rp.explain_last()` should explain complex transfers.

Example spatial:

```text
Source: geopandas.GeoDataFrame
Rows: 4,812
Geometry: Polygon/MultiPolygon
CRS: EPSG:4326
Target: R sf
Transfer: WKB + Arrow attributes
CRS preserved: yes
Geometry preserved: yes
Attribute schema preserved: yes
Spatial index: rebuilt on target
Fidelity: lossless for represented fields
```

Example graph:

```text
Source: networkx.MultiDiGraph
Nodes: 2,000
Edges: 18,921
Directed: yes
Parallel edges: yes
Node attributes: 4
Edge attributes: 6
Target: R igraph adapter
Issue: target adapter cannot represent one Python object-valued attribute losslessly
Strategy: attribute stored in proxy sidecar
Fidelity: values/topology lossless; one attribute proxy-preserved
```

---

# 71. COMPATIBILITY REGISTRY — DATA STRUCTURES

Extend compatibility registry entries to include object families and package classes.

Examples:

```text
pandas.DataFrame
polars.DataFrame
pyarrow.Table
xarray.Dataset
geopandas.GeoDataFrame
networkx.Graph
networkx.MultiDiGraph
scipy.sparse.csr_matrix
R data.frame
tibble
data.table
sf
SpatRaster
igraph
Matrix
Surv
SummarizedExperiment
```

Each registry entry may define:

- detection
- optimized converter
- standard interchange path
- metadata rules
- fidelity tests
- known limitations
- proxy fallback

Registry remains an optimization, not a whitelist.

---

# 72. DOCUMENTATION — UNIVERSAL DATA CATALOG

Add a dedicated documentation page:

```text
docs/data-structures-catalog.md
```

It must answer:

- What data types are supported?
- What conversion path is used?
- Is conversion lossless?
- What metadata are preserved?
- What happens if no direct mapping exists?
- What optional packages are needed?
- Can the object be round-tripped?
- Can it be saved/reloaded?

Group the catalog by:

- primitives
- collections
- arrays/tensors
- sparse
- tabular
- time series
- panel/longitudinal
- survey/labelled
- survival/event
- spatial vector
- raster
- spatiotemporal
- networks/graphs
- text/NLP
- media
- scientific multidimensional
- economics
- bioinformatics
- databases
- custom objects

---

# 73. README REQUIREMENT

The root README must make clear that RPython is not restricted to classic tabular econometric data.

Include a visual “Data Universe” or “Interoperability Map” showing at least:

```text
Tabular
Time Series
Panel
Cross Section
Survey
Spatial
Raster
Spatiotemporal
Networks
Graphs
Sparse Matrices
Scientific Arrays
Text
Databases
ML/DL Tensors
Domain Objects
Custom Objects
```

Do not overload the hero section with every type; link to the complete catalog.

---

# 74. REQUIRED ARCHITECTURE EXTENSIONS

Extend the project structure with modules such as:

```text
src/rpython/data/
├── semantic.py
├── registry.py
├── primitives.py
├── collections.py
├── arrays.py
├── sparse.py
├── tabular.py
├── temporal.py
├── panel.py
├── survey.py
├── survival.py
├── spatial.py
├── raster.py
├── spatiotemporal.py
├── network.py
├── text.py
├── media.py
├── scientific.py
├── economics.py
└── custom.py

src/rpython/database/
├── base.py
├── registry.py
├── sql.py
├── embedded.py
├── warehouse.py
├── document.py
├── keyvalue.py
├── graph.py
├── timeseries.py
├── spatial.py
├── vector.py
├── search.py
└── lakehouse.py
```

Exact file names may differ, but keep boundaries clean.

---

# 75. OPTIONAL DEPENDENCIES

Do not install the entire scientific ecosystem for every user.

Use optional extras, lazy imports, and capability detection.

Possible extras conceptually:

```text
rpython[arrow]
rpython[spatial]
rpython[network]
rpython[database]
rpython[scientific]
rpython[ml]
rpython[all]
```

Choose packaging names carefully.

Core installation must remain reasonably lightweight.

When an optional converter is needed, error messages should show exactly which extra/package to install.

---

# 76. NO FALSE “ALL TYPES” CLAIM

The engineering goal is universal extensibility and very broad built-in coverage.

Do not make an impossible public claim such as:

> “Every existing R and Python object can always be converted losslessly.”

Instead, the product promise should be:

> RPython provides broad semantic conversion for common and scientific data structures, standard interchange paths where available, and safe native proxies for objects that have no lossless cross-language representation.

This is stronger and technically honest.

---

# 77. CORE ACCEPTANCE TEST — NO PARTIAL EXCHANGE

For every object family marked “supported,” test more than whether values arrived.

A supported conversion must document and validate all relevant dimensions of meaning.

For example:

## Spatial

Not enough:

```text
coordinates transferred ✓
```

Required:

```text
geometry ✓
attributes ✓
CRS ✓
geometry type ✓
missing geometry ✓
feature order ✓
round trip ✓
```

## Network

Not enough:

```text
edge list transferred ✓
```

Required:

```text
nodes ✓
edges ✓
direction ✓
parallel edges ✓
self loops ✓
weights ✓
node attributes ✓
edge attributes ✓
round trip ✓
```

## Time series

Not enough:

```text
values transferred ✓
```

Required:

```text
values ✓
time index ✓
frequency ✓
timezone ✓
missing periods ✓
series identity ✓
round trip ✓
```

This principle applies to every supported family.

---

# 78. CORE ACCEPTANCE TEST — BOTH DIRECTIONS

A structure is not considered fully supported if only:

```text
R → Python
```

works well.

Test:

```text
R → Python
Python → R
R → Python → R
Python → R → Python
```

Where one direction is inherently impossible, document the reason and provide a proxy/portable representation rather than silently calling the feature “fully supported.”

---

# 79. DATABASE ACCEPTANCE TESTS

At minimum create test adapters/smoke tests for a practical representative set:

- SQLite
- DuckDB
- PostgreSQL in CI/service where practical
- one document database path if infrastructure permits
- one graph database path if infrastructure permits
- one vector-store adapter path if dependencies permit
- one spatial SQL path such as PostGIS or lightweight equivalent

Use mock/interface tests for systems that cannot reasonably run in normal CI, but also provide documented optional integration tests.

Do not claim a vendor integration was tested live if it was not.

---

# 80. FINAL UNIVERSAL DATA DEFINITION OF DONE

This extension is complete only when:

```text
[ ] universal semantic registry exists
[ ] primitive conversions tested
[ ] nested containers tested
[ ] arrays/tensors strategy implemented
[ ] sparse data preserved without forced densification
[ ] tabular ecosystems covered
[ ] Arrow nested types considered
[ ] time-series families covered
[ ] cross-sectional semantics documented
[ ] panel/longitudinal semantics covered
[ ] repeated cross-section semantics covered
[ ] hierarchical/multilevel semantics covered
[ ] survey/labelled semantics covered
[ ] survival/event data strategy exists
[ ] spatial vector conversion tested
[ ] raster strategy exists with lazy behavior
[ ] spatiotemporal strategy exists
[ ] network/graph topology preservation tested
[ ] trees/DAGs/hierarchies strategy exists
[ ] text/NLP structures covered
[ ] image/audio/video metadata strategies documented
[ ] functional data extension path exists
[ ] economics-specific structures tested
[ ] scientific multidimensional data covered
[ ] bioinformatics adapter/proxy strategy exists
[ ] distributed/lazy objects do not force materialization
[ ] streaming/chunked path exists where practical
[ ] universal database adapter architecture exists
[ ] SQL relational paths tested
[ ] analytical/embedded DB path tested
[ ] document/graph/vector/time-series/spatial DB extension points exist
[ ] database credentials are never serialized
[ ] schema negotiation implemented
[ ] fidelity reporting expanded beyond values
[ ] round-trip tests cover multiple object families
[ ] Explain Mode reports semantic preservation
[ ] README includes universal data overview
[ ] docs/data-structures-catalog.md exists
[ ] unsupported custom classes fall back to proxies rather than destructive conversion
```

---

# 81. FINAL CLAUDE INSTRUCTION FOR THIS EXTENSION

Do not interpret “all data types and structures” as a request to make a giant list without implementation.

The architecture must make broad support technically sustainable through:

```text
Detection
   ↓
Semantic classification
   ↓
Capability negotiation
   ↓
Best lossless standard/adapter
   ↓
Fidelity validation
   ↓
Proxy fallback when necessary
```

The objective is that a researcher can move naturally between R and Python whether the object is:

- a scalar,
- a DataFrame,
- an econometric panel,
- an irregular time series,
- a spatial GeoDataFrame,
- a raster cube,
- a sparse matrix,
- a multilayer network,
- a survival dataset,
- a labelled survey,
- an xarray scientific dataset,
- a genomic annotated matrix,
- a database relation,
- a vector-search collection,
- a custom package model,
- or a future structure RPython has never seen before.

For known structures, provide rich semantic adapters.

For standards-compatible structures, use efficient open interchange protocols.

For unknown/non-convertible structures, preserve the native object through a proxy.

The user should never be forced to destroy an object's meaning merely to cross the R/Python boundary.
