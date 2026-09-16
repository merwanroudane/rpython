# RPython — Master Implementation Prompt

> **Repository:** https://github.com/merwanroudane/rpython  
> **Author / project owner:** Dr. Merwan Roudane  
> **Working package name:** `rpython`  
> **Primary goal:** build a production-quality, beginner-friendly, high-level, bidirectional R ↔ Python interoperability platform in which R and Python are equal first-class citizens.

---

# 0. INSTRUCTIONS TO CLAUDE — READ THIS ENTIRE FILE BEFORE TOUCHING CODE

You are responsible for designing, implementing, testing, documenting, benchmarking, and preparing this repository as a complete R–Python interoperability library.

This is **not** a request for a proof of concept, thin wrapper, demo, toy bridge, or incomplete MVP.

The project must aim to provide a **native-feel experience** in both directions:

- When the user works with **R**, the experience should feel like working naturally in R.
- When the user works with **Python**, the experience should feel like working naturally in Python.
- Moving data, variables, functions, packages, models, results, plots, metadata, files, and database-backed objects between the two languages should require as little ceremony as possible.
- R and Python must be treated as **equal first-class runtimes**. Do not make one direction excellent and the other secondary.
- Common operations must be high-level and understandable to a beginner.
- Advanced users must still have escape hatches, explicit controls, raw object access, backend selection, custom converters, and diagnostics.

Before implementation, inspect the repository fully. It may initially be empty. If it is empty, create a clean professional project structure from scratch.

Do not ask the user to manually complete routine engineering work that you can perform yourself. Work continuously through implementation, testing, fixing, retesting, documentation, packaging, and verification.

## Absolute execution rule

Do **not** stop after creating a skeleton or a few modules. Do not leave core features as placeholders.

For every core feature:

1. design it,
2. implement it,
3. run it,
4. test it,
5. intentionally test edge cases,
6. fix failures,
7. rerun related tests,
8. rerun the broader suite,
9. document it,
10. verify documentation examples actually execute.

If a test fails, investigate and fix it. Do not simply report the failure and move on unless the limitation is truly external and unavoidable. In that case, implement the safest fallback possible and document the exact limitation.

The final repository must not contain unfinished core features described with:

- `TODO`
- `FIXME`
- `coming soon`
- `not implemented`
- placeholder implementations
- fake success paths
- untested examples

A core subsystem that is weak while another subsystem is excellent is **not acceptable**.

---

# 1. CORE PRODUCT PHILOSOPHY

The central philosophy is:

> **Maximum flexibility, minimum ceremony, native feel, semantic safety, transparent fallbacks, and no silent corruption of statistical meaning.**

The user should not need to learn internals of `rpy2`, `reticulate`, Arrow converters, R embedding, IPC, subprocess orchestration, HTTP serialization, or object proxying just to use a common R or Python package.

The public API must hide backend complexity.

Internally, the implementation may use multiple engines such as:

- embedded R through `rpy2`
- subprocess R execution
- isolated R worker processes
- an R companion package
- Apache Arrow / PyArrow / Arrow C Data Interface
- IPC
- temporary files when necessary
- shared database connections
- Rserve-like process isolation when useful
- HTTP/REST only when appropriate for remote execution
- generic object proxies
- custom optimized adapters

But the public API should remain stable and high-level.

The design principle is:

```text
One public API
      ↓
Runtime / backend router
      ↓
Best available engine
      ↓
Automatic semantic conversion or proxy fallback
```

---

# 2. THIS PROJECT MUST GO BEYOND EXISTING R–PYTHON TOOLS

Before implementation, re-check current official documentation, release notes, open/closed GitHub issues, compatibility notes, and representative user complaints for the major tools below. Do not rely only on this document; verify the current state before coding.

The purpose of competitor research is **not** to copy code. It is to understand strengths, friction points, failure modes, and missing abstractions.

## 2.1 Competitor baseline

At minimum inspect:

1. `rpy2`
2. `reticulate`
3. `rpy2-arrow`
4. Apache Arrow R/Python interoperability
5. `plumber`
6. `Rserve`
7. `pyreadr`
8. `rdata`
9. SoS Notebook
10. IRkernel and Jupyter R integrations
11. relevant R/Python notebook bridges and package-management integrations
12. any newer active projects that provide R ↔ Python interoperability

Useful official starting points include:

- https://rpy2.github.io/
- https://rstudio.github.io/reticulate/
- https://arrow.apache.org/
- https://www.rplumber.io/ and Posit plumber documentation
- https://www.rforge.net/Rserve/
- https://github.com/ofajardo/pyreadr
- https://github.com/vnmabus/rdata
- https://vatlab.github.io/sos-docs/
- https://irkernel.github.io/

Re-verify URLs if projects have moved.

## 2.2 What to preserve from competitors

Preserve the strongest ideas where appropriate:

### From rpy2

- real R execution from Python
- R package access
- Python ↔ R object conversion
- Jupyter magic integration
- custom conversion extensibility

### From reticulate

- Python access from R
- environment discovery ideas
- Python package interoperability
- dependency-management ideas such as declarative requirements
- object conversion and proxy concepts

### From Arrow / rpy2-arrow

- high-performance tabular transfer
- low-copy / zero-copy opportunities
- large-data interoperability
- stable language-neutral memory formats

### From Plumber / Rserve-style approaches

- isolation
- remote execution
- process separation
- resilience when embedded runtimes are not suitable

### From pyreadr / rdata

- RDS/RData file interoperability
- pure file conversion where R runtime is unnecessary
- extensible deserialization concepts

### From SoS / notebook tools

- multi-language notebook ergonomics
- language-cell concepts
- variable exchange across runtimes

## 2.3 Friction points that RPython must improve

The library must explicitly target the kinds of problems repeatedly encountered in existing bridges:

- low-level conversion APIs exposed to ordinary users
- interpreter / environment ambiguity
- `R_HOME`, PATH, DLL, compiler, and library-path problems
- Jupyter kernel using a different Python than the shell
- R library paths differing from the active R runtime
- Windows-specific setup friction
- Colab runtime setup friction
- dependency/version conflicts after pandas, NumPy, R, Python, or package upgrades
- conversion regressions after upstream dependency upgrades
- unnecessary copies of large data
- large/wide data conversion failures
- poor preservation of time-series semantics
- poor preservation of panel-data semantics
- loss or alteration of factor/category ordering
- timezone ambiguity
- missing-value semantic differences
- row-major vs column-major array differences
- model/S3/S4/R6/custom-object conversion problems
- notebook magic options being too low-level for beginners
- package installation requiring separate language-specific knowledge
- remote/server approaches being too ceremonious for local use
- file conversion libraries losing metadata or supporting only subsets of R object types
- lack of a user-facing round-trip semantic guarantee
- lack of one unified diagnostic tool
- lack of one unified package manager abstraction
- lack of one unified save/load abstraction
- asymmetric R→Python vs Python→R quality

## 2.4 Mandatory competitor-gap rule

Every meaningful competitor weakness discovered must map to:

```text
observed gap
    ↓
RPython requirement
    ↓
implementation
    ↓
automated test
    ↓
documentation example
    ↓
acceptance criterion
```

Do not write vague claims such as “better conversion.” Demonstrate them.

Example:

```text
Gap:
Ordered factors can lose ordering in some conversion paths.

RPython requirement:
Preserve categorical levels and ordering whenever a lossless mapping exists.

Test:
R ordered factor → Python categorical → R ordered factor.

Acceptance:
- same levels
- same order
- same missingness
- no silent downgrade
```

## 2.5 Marketing honesty

Do not claim RPython is “better” merely because a competitor comparison table says so.

Any public comparison in README/PyPI documentation must be factual, capability-based, reproducible, and respectful.

Never fabricate benchmark numbers, issue counts, compatibility claims, or unsupported superiority statements.

---

# 3. DIFFERENTIATION: FEATURES THAT MUST GO BEYOND A THIN WRAPPER

The project must target all of the following as integrated first-class capabilities:

1. Native-feel Python experience.
2. Native-feel R experience.
3. True bidirectional interoperability.
4. Semantic Data Layer.
5. First-class time-series support.
6. First-class panel-data support.
7. Smart automatic conversion.
8. Smart transfer planning.
9. Automatic Arrow acceleration when appropriate.
10. Generic proxy fallback for unknown/custom objects.
11. Safe isolated execution mode.
12. Compatibility firewall against upstream version changes.
13. Environment autopilot.
14. Universal R/Python package manager.
15. Jupyter-first support.
16. Google Colab-first support.
17. VS Code / terminal support.
18. Cross-platform support.
19. Simple `%r`, `%%r`, `%py`, `%%py` magics.
20. Unified result model.
21. Seamless plotting.
22. Cross-language save/load.
23. Database interoperability.
24. Formula interoperability.
25. Unicode-safe handling including Arabic and French.
26. Automatic diagnostics.
27. Safe auto-fix where feasible.
28. Explain Mode.
29. Round-trip fidelity validation.
30. Compatibility Registry.
31. Real-package torture testing.
32. Stress testing.
33. Nightly / scheduled compatibility testing where practical.
34. README examples executed as tests.
35. Beginner Command Catalog.
36. Extension API for future converters, runtimes, and adapters.

These are not isolated gimmicks. They must form one coherent system.

---

# 4. EQUAL FIRST-CLASS LANGUAGES

The architecture must not have:

```text
Python → R    excellent
R → Python    limited
```

or the reverse.

It must aim for:

```text
Python ↔ R
```

with comparable quality, diagnostics, documentation, package access, object handling, plotting, persistence, and notebook experience.

Create:

- a primary Python package
- an R companion package or equivalent R-facing layer when needed to provide a truly symmetric R experience

The R companion must not be an afterthought.

---

# 5. HIGH-LEVEL PUBLIC API

The public API should be small, memorable, beginner-friendly, composable, and discoverable.

The exact names may be refined if testing shows a better design, but the intended experience should remain approximately this simple.

## 5.1 Python-side start

```python
import rpython as rp

r = rp.R()
```

Basic execution:

```python
r("1 + 1")
```

or:

```python
r.run("1 + 1")
```

Package access:

```python
forecast = r.package("forecast")
```

Package installation:

```python
r.install("forecast")
```

Example high-level call:

```python
fit = forecast.auto_arima(y)
pred = fit.forecast(12)
pred.plot()
pred.save("forecast.xlsx")
```

The user must not need to manually create `robjects`, converters, R vectors, or activate local converters for ordinary cases.

## 5.2 R-side experience

Provide equally high-level access from R to Python.

Conceptually:

```r
library(rpython)

py <- python()
sklearn <- py$package("sklearn")
```

The exact R API should be made idiomatic for R users.

Do not force R users to understand Python runtime internals for common use.

## 5.3 Simple by default, powerful when needed

Default mode:

- automatic environment detection
- automatic common-type conversion
- automatic transfer backend selection
- automatic plot display
- clear errors

Advanced mode must expose:

- raw R object
- raw Python object
- backend selection
- conversion policy
- transfer policy
- proxy controls
- timeout
- process isolation
- environment selection
- package source
- explicit dtype mapping
- metadata policies

---

# 6. NATIVE-FEEL INTEROPERABILITY

The guiding rule is:

> If using an R package through RPython feels substantially harder than using it directly in R, redesign the API.

and:

> If using a Python package through RPython feels substantially harder than using it directly in Python, redesign the API.

Also:

> If a beginner must understand bridge internals to convert a common object, the abstraction has failed.

Do not unnecessarily translate R code into Python or Python code into R.

The preferred model is:

- R code executes natively in R.
- Python code executes natively in Python.
- RPython handles communication, conversion, metadata, persistence, display, and diagnostics.

A future optional code-translation helper may exist, but code translation must not be the foundation of interoperability.

---

# 7. RUNTIME ROUTER / EXECUTION ENGINES

Create an execution abstraction that can route operations to the safest and most efficient backend.

Potential backends:

1. embedded R
2. isolated R worker process
3. subprocess execution
4. persistent R session
5. R companion process
6. remote R service when configured
7. file-only conversion for RDS/RData when no runtime is required

Use capability detection rather than assuming a backend always works.

## 7.1 Safe mode

Provide a safe/isolation option so problematic native packages cannot necessarily crash the user's main Python process/kernel.

Conceptually:

```python
r = rp.R(safe=True)
```

or:

```python
with rp.safe():
    ...
```

If an R package crashes, segfaults, or corrupts the worker process, RPython should preserve the main session when possible and return a meaningful diagnostic.

## 7.2 Local first, remote optional

Normal local use must not require a REST server.

Remote execution may be supported through the same high-level API, but remote complexity must remain behind an adapter.

---

# 8. SEMANTIC DATA LAYER — CENTRAL DIFFERENTIATOR

Do not merely move values. Preserve **statistical and structural meaning**.

Create an internal semantic representation, for example `DataEnvelope`, `SemanticData`, or a better name.

It should be able to carry:

- values
- schema
- data type
- column types
- row/index semantics
- column names
- labels
- units when present
- missing-value semantics
- categorical levels
- categorical order
- factor reference information when relevant
- date/time information
- timezone
- time frequency
- time start/end
- irregularity
- entity identifier
- time identifier
- panel structure
- balanced/unbalanced panel status
- duplicate entity-time keys
- missing periods
- original runtime
- original class
- serialization origin
- conversion history
- lossy/lossless status
- warnings

Never silently change statistical meaning merely to make a conversion succeed.

If a lossless conversion is impossible:

1. preserve the original object through a proxy when possible,
2. or perform an explicitly reported lossy conversion only if policy allows,
3. explain exactly what is lost.

---

# 9. DATA TYPE COVERAGE

Support and test common primitives and scientific/statistical objects.

## 9.1 Python types

At minimum design support for:

- `int`
- `float`
- `complex`
- `bool`
- `str`
- `bytes`
- `None`
- `list`
- `tuple`
- `dict`
- `set` where meaningful
- NumPy scalars
- NumPy vectors/matrices/ndarrays
- masked arrays where feasible
- pandas `Series`
- pandas `DataFrame`
- pandas nullable dtypes
- pandas `Categorical`
- pandas `DatetimeIndex`
- pandas `PeriodIndex`
- pandas `Timedelta`
- pandas `MultiIndex`
- timezone-aware datetime
- Polars Series/DataFrame
- PyArrow Array/Table/RecordBatch
- xarray objects
- sparse data where feasible
- Python dataclasses or structured objects where a meaningful mapping exists

## 9.2 R types

At minimum design support for:

- numeric
- integer
- logical
- complex
- character
- raw
- vector
- named vector
- matrix
- array
- list
- named list
- data.frame
- tibble
- data.table
- factor
- ordered factor
- Date
- POSIXct/POSIXlt where appropriate
- difftime
- `ts`
- `mts`
- `zoo`
- `xts`
- S3
- S4
- R6
- environment/reference objects when meaningful

Unknown or custom objects must not automatically be rejected.

---

# 10. MISSING VALUES / SPECIAL VALUES

Implement an explicit `MissingValuePolicy` or equivalent.

Handle and test differences among:

### R

- `NA`
- typed `NA`
- `NaN`
- `NULL`
- `Inf`
- `-Inf`

### Python / NumPy / pandas

- `None`
- `numpy.nan`
- `pandas.NA`
- `NaT`
- `numpy.inf`
- `-numpy.inf`

Default behavior should aim to preserve semantic intent.

Conceptual configuration:

```python
rp.config(missing="preserve")
```

Never collapse distinct missingness concepts silently when that matters to downstream analysis.

---

# 11. CATEGORICAL / FACTOR SAFETY

Preserve whenever possible:

- levels
- order
- ordered/unordered status
- unused levels where relevant
- missing levels
- reference/baseline information where relevant to model semantics

Round-trip tests are mandatory.

Example acceptance path:

```text
R ordered factor
→ Python pandas.Categorical
→ R ordered factor
```

Must preserve order and levels.

---

# 12. DATE, TIME, TIMEZONE, FREQUENCY

Date/time conversion is a critical subsystem.

Support:

- Date
- datetime
- timezone-aware datetime
- timezone-naive datetime with explicit policy
- timedeltas/difftime
- `DatetimeIndex`
- `PeriodIndex`
- R `Date`
- R `POSIXct`
- common frequency semantics

Preserve timezone whenever available.

Do not silently reinterpret ambiguous date strings such as `01/02/2025`.

If parsing is ambiguous, provide an explicit diagnostic or require the user to select a policy.

---

# 13. TIME SERIES AS A FIRST-CLASS DATA STRUCTURE

Do not reduce time series to raw arrays by default.

Recognize and preserve:

- temporal index
- start
- end
- frequency
- timezone
- regular/irregular status
- missing periods
- seasonal frequency
- multiple series
- metadata

Design meaningful mappings among:

- R `ts`
- R `mts`
- R `zoo`
- R `xts`
- pandas `DatetimeIndex`
- pandas `PeriodIndex`
- appropriate Python time-series objects

If exact class parity is impossible, preserve semantics through metadata.

Provide explicit high-level helpers such as:

```python
rp.as_timeseries(...)
```

or a better API.

---

# 14. PANEL DATA AS A FIRST-CLASS DATA STRUCTURE

This is a key differentiator for econometrics/research users.

Support explicit panel metadata:

- entity ID
- time ID
- balanced / unbalanced
- duplicates
- missing periods
- sorting
- number of entities
- number of periods
- frequency if temporal
- irregular panels
- nested/grouped panels where feasible

Provide a high-level declaration such as:

```python
panel = rp.panel(df, id="country", time="year")
```

or equivalent.

Support safe auto-detection where confidence is high, but **never silently guess** ambiguous panel structure.

Provide a structure report:

```python
panel.describe_structure()
```

Possible output:

```text
Type: Panel Data
Entity: country
Time: year
Frequency: Annual
Entities: 48
Periods: 2000–2025
Balanced: No
Duplicates: 0
Missing periods: 14
```

Test balanced/unbalanced panels, duplicate keys, string/integer IDs, annual/quarterly/monthly dates, irregular time, missing periods, and large panels.

---

# 15. OTHER RESEARCH DATA SEMANTICS

Design the semantic layer so it can represent or extend toward:

- cross-sectional data
- repeated cross sections
- longitudinal data
- hierarchical / multilevel data
- spatial data
- event data
- survival data
- financial time series
- high-frequency data

Do not over-engineer unsupported domains, but ensure the architecture allows adapters without redesigning the core.

---

# 16. FORMULA INTEROPERABILITY

Support statistical/econometric formulas safely.

Consider:

- `y ~ x1 + x2`
- interactions
- transformations
- categorical variables
- fixed effects
- lags/leads
- splines or package-specific formula syntax
- namespace calls

Do not translate formulas blindly if semantics differ between packages/languages.

Create a `Formula` abstraction only if it reduces ambiguity without making simple usage harder.

When no safe translation exists, preserve the formula in its native runtime.

---

# 17. VARIABLE NAMES / UNICODE / INTERNATIONALIZATION

Support and test:

- ASCII names
- spaces
- hyphens
- punctuation
- very long names
- duplicate names
- Arabic variable names
- French accents
- Unicode strings
- multilingual values
- multilingual plot labels
- Unicode file paths where supported by the OS

Never silently rename a user's variable without a reversible mapping.

If a runtime requires a safe internal name, maintain a `NameMappingRegistry` or equivalent:

```text
original name ↔ internal safe name
```

Restore original names on round trip where possible.

---

# 18. SMART TRANSFER PLANNER

The user should normally call a high-level transfer/execution function and let RPython decide the optimal mechanism.

The planner should consider:

- object type
- object size
- memory pressure
- current runtime
- backend capabilities
- Arrow compatibility
- whether a copy is necessary
- whether a shared database/query is preferable
- whether conversion is lossless
- whether a proxy is safer

Example strategy:

```text
small primitive        → native conversion
small DataFrame        → native converter
large table            → Arrow
very large database    → shared/lazy query
unsupported model      → native object proxy
remote session         → IPC/Arrow/serialized protocol
```

Do not require users to write `use_arrow=True` for ordinary cases.

Allow advanced override.

---

# 19. LARGE DATA / PERFORMANCE / MEMORY

Design specifically for data that does not fit comfortably into duplicate in-memory copies.

Support where feasible:

- Arrow transfer
- chunked transfer
- streaming
- lazy evaluation
- database pushdown
- shared files / Parquet
- memory mapping where appropriate

Benchmark representative sizes:

- tiny
- small
- medium
- 100k rows
- 1M+ rows where CI/resources permit
- wide tables
- mixed-type tables

Measure:

- elapsed time
- memory overhead
- number of copies when detectable
- conversion path chosen

Never fabricate performance claims.

---

# 20. DATABASE INTEROPERABILITY

Do not force every database-backed workflow through:

```text
SQL → pandas → R copy
```

Support or plan adapters for common systems such as:

- SQLite
- DuckDB
- PostgreSQL
- MySQL/MariaDB
- SQL Server
- Arrow datasets
- Parquet datasets
- other DBI/SQLAlchemy-compatible systems when possible

Allow R and Python to operate on the same underlying source when this is safer and more efficient.

Provide lazy/shared connection strategies where appropriate.

Avoid leaking credentials into logs, errors, result metadata, or saved bundles.

---

# 21. UNIVERSAL PACKAGE MANAGER

Package installation must be high-level and symmetric.

## R sources

Support or route appropriately among:

- CRAN
- Bioconductor
- GitHub
- local packages
- custom repositories

## Python sources

Support or route appropriately among:

- PyPI
- `uv`
- `pip`
- Conda where appropriate
- GitHub
- local wheel
- local project

Desired Python-facing usage:

```python
r.install("forecast")
forecast = r.package("forecast")
```

Desired R-facing usage should be equally simple for Python packages.

Detect package source automatically when reasonably safe.

If a package requires system dependencies, Java, CUDA, compilers, external SDKs, licenses, or OS-specific libraries, do not pretend installation is universal. Provide a precise diagnostic and actionable commands.

## Unknown package rule

**Unknown must not mean unsupported.**

Use:

```text
Known package
→ optimized adapter if available

Unknown package
→ generic loader
→ inspect call/result
→ generic conversion
→ proxy fallback if necessary
```

---

# 22. ENVIRONMENT AUTOPILOT

Create a robust environment layer.

Support/detect where feasible:

- system Python
- `venv`
- `uv`
- Conda
- Poetry
- Jupyter kernels
- VS Code environments
- Google Colab runtimes
- Docker/container environments
- multiple installed R versions
- multiple R library trees

Detect:

- active Python executable
- Python version
- active R executable
- R version
- `R_HOME`
- PATH mismatches
- architecture (32/64-bit if relevant)
- compiler/toolchain requirements
- R library paths
- Jupyter kernel mismatch
- Arrow availability
- package version conflicts

Do not randomly select among multiple R or Python installations.

Allow explicit selection when needed.

---

# 23. UNIFIED LOCK / REPRODUCIBILITY LAYER

Consider a project-level manifest such as:

```text
rpython.lock
```

or another clear name.

It should orchestrate rather than unnecessarily replace native lock systems.

Potential relationship:

```text
rpython.lock
   ├── Python → pyproject.toml / uv.lock / requirements
   └── R      → renv.lock / DESCRIPTION metadata
```

Record enough information for reproducibility:

- Python version
- R version
- package versions
- package sources
- relevant runtime backend configuration
- platform metadata
- encoding/timezone only when semantically relevant

Provide restore/setup helpers.

This is especially important for ephemeral environments such as Colab.

---

# 24. GOOGLE COLAB AS A FIRST-CLASS TARGET

Do not merely mention Colab in documentation.

Create a tested Colab workflow from a fresh runtime:

1. install RPython
2. detect/provision R runtime if necessary
3. initialize bridge
4. install an R package
5. execute R
6. send pandas DataFrame to R
7. receive a result
8. produce/display an R plot
9. run notebook magics
10. restore dependencies after a fresh-runtime scenario

The public usage should be close to:

```python
!pip install rpython

import rpython as rp
rp.setup()
```

Then ordinary usage.

Colab runtimes are ephemeral; document and support restoration rather than pretending persistence exists.

---

# 25. JUPYTER / JUPYTERLAB AS FIRST-CLASS TARGETS

The user should not need to switch kernels repeatedly for ordinary mixed-language work.

Support concise magics.

Minimum conceptual set:

```text
%r
%%r
%py
%%py
```

Keep the core set intentionally small.

Allow optional flags such as:

```text
-i   input
-o   output
-s   silent
-v   verbose
```

Do not expose low-level converter configuration in beginner workflows.

Example:

```python
%%r -i df -o model

library(plm)
model <- plm(y ~ x1 + x2, data=df, model="within")
```

Explore a friendlier optional syntax only if it remains robust and unsurprising.

Auto-display plots and tables naturally.

Test:

- scalar input/output
- DataFrame
- time series
- panel data
- plots
- model objects
- warnings
- errors
- multiple outputs
- Unicode
- missing values

Do not make Jupyter support depend on a fragile single backend if a fallback can be provided.

---

# 26. VS CODE / TERMINAL / SCRIPT EXPERIENCE

The same API should work in:

- `.py` scripts
- `.R` scripts through companion API
- VS Code
- terminal
- Jupyter
- Colab

Avoid notebook-only assumptions in the core runtime.

---

# 27. FUNCTIONS AS FIRST-CLASS CROSS-LANGUAGE OBJECTS

Allow an R function to be used naturally from Python.

Example concept:

```python
calculate = r.function("calculate_index")
result = calculate(df, weight=2)
```

Allow Python callables to be exposed naturally to R through the companion layer where safe.

Preserve:

- argument names
- defaults where discoverable
- variadic arguments
- returned objects
- warnings/messages
- exceptions/errors

Provide signature/introspection information when feasible.

---

# 28. UNIVERSAL OBJECT PROXY

Do not attempt to forcibly convert every object.

For unsupported or semantically rich native objects, preserve them in the source runtime and expose a proxy.

## R object proxy

Examples:

- S3 models
- S4 objects
- R6 objects
- Bioconductor objects
- specialized econometric models
- package-specific result objects

Desired experience:

```python
model.summary()
model.coef()
model.predict()
model.plot()
model.methods()
model.raw
```

Methods should be delegated to R when the object remains in R.

## Python object proxy

Examples:

- scikit-learn pipelines
- PyTorch models
- xarray objects
- custom Python classes

R should be able to retain a proxy rather than flattening them into incomplete lists.

---

# 29. UNIFIED RESULT SYSTEM

Create a high-level result abstraction without forcing all users to interact with it explicitly.

For simple results, return natural native Python/R values whenever safe.

For richer results, expose structured access such as:

```python
result.value
result.table
result.model
result.plot
result.summary
result.stdout
result.messages
result.warnings
result.errors
result.metadata
result.raw
```

The beginner should be able to simply display `result` and get a sensible representation.

Do not wrap every scalar in an unnecessarily heavy result object.

---

# 30. PLOTTING INTEROPERABILITY

Plots must be first-class.

Support common R plotting systems where feasible:

- base graphics
- ggplot2
- lattice if practical
- htmlwidgets where practical

Support Python plotting systems where feasible:

- matplotlib
- Plotly
- Altair
- other common display objects through generic notebook display hooks

In Jupyter/Colab, plots should display automatically.

Provide consistent save behavior:

```python
plot.save("figure.png")
```

or another clean API.

Support appropriate formats:

- PNG
- SVG
- PDF
- HTML for interactive objects when applicable

Do not silently rasterize interactive plots unless required and reported.

---

# 31. SAVE / LOAD / PERSISTENCE

Create a high-level persistence layer.

Examples:

```python
rp.save(obj, "path")
obj.save("path")
obj = rp.load("path")
```

Support common data formats where meaningful:

- CSV
- TSV
- Excel
- Parquet
- Feather/Arrow IPC
- JSON
- RDS
- RData
- pickle only with clear security warnings
- NumPy formats
- Stata
- SPSS
- SAS where libraries permit
- SQL / DuckDB

For each format, understand what metadata can and cannot be preserved.

If a format such as CSV cannot preserve categorical ordering, timezone semantics, panel metadata, or object classes, warn clearly.

## Cross-language persistence bundle

For rich objects, design a bundle format that can preserve:

- native serialized object
- semantic metadata
- origin runtime
- package/class information
- environment metadata needed to reload
- optional portable representation

Do not convert complex models to lossy generic structures just to save them.

---

# 32. DIAGNOSTICS: `doctor()`, `check()`, `self_test()`, `fix()`

Diagnostics must be a major feature.

Provide an easy environment report such as:

```python
rp.doctor()
```

Potential output:

```text
Platform                 Linux
Environment              Google Colab
Python                    3.x      ✓
R                         4.x      ✓
Jupyter                   detected ✓
PyArrow                   available ✓
R package bridge          ready ✓
Python package bridge     ready ✓
Magics                    ready ✓
Plot transport            ready ✓

Issues:
- R package 'plm' missing

Suggested fix:
  rp.fix()
```

Implement:

- `check()` for a lightweight readiness test
- `self_test()` for interoperability tests
- `self_test(full=True)` for more extensive diagnostics
- `fix()` for safe automatic repairs
- `restore()` for reproducibility/environment restoration

Never auto-modify system configuration destructively without explicit safety checks.

---

# 33. EXPLAIN MODE

Provide a way for users and researchers to understand what RPython did internally.

Concept:

```python
rp.explain_last()
```

Possible report:

```text
Input: pandas.DataFrame
Detected semantics: Panel Data
Entity key: country
Time key: year
Transfer strategy: PyArrow
R representation: arrow::Table / data.frame adapter
Target package: plm
Result type: R S3 object 'plm'
Return strategy: RObjectProxy
Copies: 0 or best available estimate
Metadata preserved:
  entity ✓
  time ✓
  categories ✓
Warnings: none
```

This is especially valuable for teaching, debugging, reproducibility, and research transparency.

---

# 34. ROUND-TRIP FIDELITY ENGINE

Round-trip testing is not optional.

For supported types test:

```text
Python → R → Python
R → Python → R
```

Validate as applicable:

- values
- dtype/type
- shape
- column names
- index
- categories
- category ordering
- missing values
- timezone
- frequency
- time index
- panel keys
- metadata

Expose user-facing fidelity information where useful:

```text
Lossless ✓
```

or:

```text
Lossy conversion ⚠
Reason: target format cannot preserve ordered categories.
```

Never label a conversion lossless unless it has actually been validated.

---

# 35. COMPATIBILITY FIREWALL

Upstream libraries change.

Do not rely only on hard-coded versions.

Create a compatibility strategy using:

- semantic version constraints where appropriate
- capability detection
- runtime probes
- converter feature detection
- fallback conversion paths
- Arrow fallback
- proxy fallback
- informative diagnostics

Example:

```text
primary pandas converter fails
      ↓
Arrow-supported path
      ↓
safe serialization path
      ↓
proxy / explicit limitation
```

Do not crash immediately if a safe alternative exists.

---

# 36. COMPATIBILITY REGISTRY

Create a maintainable registry for known package/object compatibility where it genuinely helps.

Possible structure:

```text
compatibility/
  pandas.yaml
  numpy.yaml
  polars.yaml
  pyarrow.yaml
  ggplot2.yaml
  forecast.yaml
  plm.yaml
  fixest.yaml
  sklearn.yaml
  statsmodels.yaml
```

Track only useful information such as:

- tested versions
- known issues
- preferred transfer path
- custom adapter
- fallback
- special semantic rules

Do not make the registry a whitelist.

Unknown packages must still use generic interoperability.

---

# 37. BEGINNER-FIRST EXPERIENCE

A beginner should not need prior knowledge of both languages.

The documentation and API must answer common questions immediately:

- How do I start R from Python?
- How do I start Python from R?
- How do I install an R package?
- How do I install a Python package?
- How do I load a package?
- How do I send a DataFrame?
- How do I retrieve a DataFrame?
- How do I run an R block?
- How do I run a Python block?
- How do I call a function?
- How do I retrieve a model?
- How do I display a plot?
- How do I save a result?
- How do I use time-series data?
- How do I use panel data?
- How do I connect to a database?
- How do I fix environment problems?

Every beginner example should explain:

1. what the code does,
2. why each important line exists,
3. what object is returned,
4. what the expected output means,
5. common mistakes.

---

# 38. BEGINNER COMMAND CATALOG

Create a dedicated beginner catalog, for example:

```text
docs/beginner-catalog.md
```

Also include a concise version in README.

Organize it into:

## A. Starting / setup

- setup
- doctor
- check
- self-test
- create R session
- access Python session

## B. Packages

- install R package
- install Python package
- load R package
- load Python package
- update/check package
- source selection

## C. Data

- send DataFrame
- receive DataFrame
- vector/list/dict/matrix
- missing values
- categories/factors
- dates
- time series
- panel data
- large data

## D. Code execution

- single line
- multi-line block
- `.R` file
- `.py` file
- functions
- package functions

## E. Results

- scalar
- table
- model
- summary
- plot
- warnings
- errors
- raw object

## F. Notebook / Colab

- `%r`
- `%%r`
- `%py`
- `%%py`
- inputs
- outputs
- plots

## G. Save / load

- data
- results
- plots
- models
- cross-language bundle

## H. Diagnostics

- doctor
- explain
- fix
- restore
- self-test

The catalog should include copy/paste-ready examples.

---

# 39. README / PYPI DOCUMENTATION — MUST BE EXCELLENT

The root `README.md` is a product surface, not an afterthought.

It must work well on both GitHub and PyPI.

A researcher landing on PyPI should be able to find the code they need immediately without searching across many external pages.

## Required README sections

1. Hero/logo
2. One-sentence value proposition
3. Badges
4. What RPython is
5. Why it exists
6. Key differentiators
7. Comparison with existing tools, factual and respectful
8. Installation
9. R prerequisites
10. Python prerequisites
11. First 60-second example
12. Python → R quick start
13. R → Python quick start
14. R package from Python
15. Python package from R
16. DataFrame transfer
17. Time-series example
18. Panel-data example
19. Plotting example
20. Saving/loading example
21. Jupyter magics
22. Google Colab workflow
23. Database example
24. Large-data behavior
25. Environment doctor
26. Explain mode
27. Beginner command catalog
28. Troubleshooting
29. Architecture overview
30. Performance/benchmark methodology
31. Compatibility policy
32. Contributing
33. License
34. Citation/author information if appropriate

## README teaching rule

Do not present unexplained code walls.

For foundational examples include:

- what the code does
- explanation before the code
- code
- explanation after the code
- expected result

README examples must be kept executable through CI/doc tests.

---

# 40. DOCUMENTATION TREE

Create a complete documentation structure such as:

```text
docs/
├── beginner-catalog.md
├── installation.md
├── quickstart.md
├── environments.md
├── packages.md
├── data-conversion.md
├── time-series.md
├── panel-data.md
├── databases.md
├── large-data.md
├── functions.md
├── models-and-proxies.md
├── plotting.md
├── saving-loading.md
├── jupyter-colab.md
├── diagnostics.md
├── explain-mode.md
├── compatibility.md
├── troubleshooting.md
├── architecture.md
├── benchmarks.md
├── faq.md
└── examples/
```

Use a documentation framework if it improves usability, but do not make the package dependent on the docs build at runtime.

---

# 41. VISUAL DESIGN / LOGO / README IMAGES

The project must have a professional visual identity.

Create or define assets under a directory such as:

```text
assets/
  logo.svg
  logo-light.svg
  logo-dark.svg
  icon.svg
  hero.svg
  architecture.svg
  workflow.svg
  conversion-map.svg
  notebook-demo.svg
  result-object.svg
```

If image-generation capability is unavailable in the execution environment, create professional SVG diagrams programmatically and leave clear prompts/specifications for raster/logo generation — but do not leave the README visually empty.

## Logo direction

The logo should communicate:

- R ↔ Python
- bridge/interoperability
- data flow
- simplicity
- modern technical quality

It should be:

- visually strong
- clean
- modern
- recognizable at small size
- suitable for GitHub and PyPI
- usable on light and dark backgrounds

Avoid a cluttered logo.

Use a warm, attractive, professional palette rather than a dull corporate-only palette.

Do not improperly reproduce trademarked logos in a way that implies official affiliation. If visual references to R/Python are used, respect their branding/trademark guidance.

## Required README visuals

At minimum include:

1. logo
2. hero banner
3. architecture diagram
4. workflow diagram
5. R ↔ Python conversion map
6. notebook/Colab usage visual
7. unified result visual

Every diagram should help understanding, not merely decorate.

---

# 42. CLI

Provide a useful command-line interface where it improves workflows.

Potential commands:

```text
rpython doctor
rpython setup
rpython check
rpython self-test
rpython fix
rpython env
rpython packages
rpython install r forecast
rpython install py pandas
rpython lock
rpython restore
```

Keep CLI naming consistent with the Python/R APIs.

---

# 43. ERROR HANDLING

Errors must be human-readable and actionable.

Avoid exposing only long low-level stack traces to beginners.

Error response model should identify:

- what failed
- in which runtime
- likely cause
- environment details relevant to the failure
- suggested fix
- whether RPython attempted a fallback
- raw traceback accessible for advanced debugging

Example:

```text
R package installation failed

Package: packageA
Reason: requires R >= X
Current R: Y

Recommended action:
  rpython env create ...

Technical details:
  available with --verbose / result.raw_error
```

Warnings and messages from R/Python should be captured without being silently discarded.

---

# 44. SECURITY AND SAFETY

Interoperability libraries execute arbitrary user code by design; nevertheless, avoid creating extra risks.

- never expose credentials in logs
- sanitize temporary-file handling
- clean temporary resources
- warn about untrusted pickle loading
- do not silently execute package install scripts from unknown sources
- distinguish trusted package repositories from arbitrary URLs
- document remote-execution security
- avoid shell injection when constructing subprocess commands
- use argument arrays instead of unsafe shell concatenation
- respect user environment boundaries

---

# 45. REAL-WORLD PACKAGE TEST MATRIX

Do not test only toy packages.

Use representative packages from multiple categories.

The exact package list may evolve based on current compatibility and CI constraints, but cover categories such as:

## R examples

- dplyr
- tidyr
- data.table
- ggplot2
- forecast or current successor/time-series package
- plm
- fixest
- vars
- urca
- randomForest
- xgboost where practical
- arrow
- DBI
- duckdb

## Python examples

- numpy
- pandas
- polars
- pyarrow
- scipy
- statsmodels
- linearmodels
- scikit-learn
- xgboost where practical
- matplotlib
- plotly
- duckdb
- sqlalchemy

Do not hard-code the product around only these packages.

---

# 46. PACKAGE TORTURE TESTS

Test packages/functions that return or emit:

- scalar
- vector
- matrix
- DataFrame/data.frame
- nested list/dict
- model object
- S3 object
- S4 object
- R6 object
- custom Python class
- plot
- interactive plot
- warning
- message
- error
- file output
- multiple outputs

Test argument passing, return conversion, proxy fallback, repr/display, saving, and reloading.

---

# 47. EDGE CASE TESTS

Test at least:

- empty DataFrame
- one-row DataFrame
- zero-column object where valid
- duplicate column names
- non-English column names
- Arabic names
- French accents
- spaces in names
- special characters
- very long names
- duplicate indexes
- missing dates
- irregular time series
- unbalanced panels
- duplicate entity-time keys
- timezone differences
- daylight-saving transitions where relevant
- `Inf`
- `-Inf`
- `NaN`
- `NA`
- `NULL`
- `None`
- `pd.NA`
- `NaT`
- ordered factors
- high-cardinality factors
- nested objects
- wide data
- long data
- large data

---

# 48. PROPERTY-BASED / FUZZ / RANDOMIZED CONVERSION TESTS

Where feasible, add property-based tests for conversion invariants.

Generate combinations of:

- numeric ranges
- missingness
- strings
- categories
- dates
- timezones
- nested containers
- column shapes

Validate round-trip properties and absence of silent corruption.

Use randomized testing responsibly and make failures reproducible with seeds.

---

# 49. CROSS-PLATFORM / VERSION CI MATRIX

At minimum design CI for:

- Linux
- Windows
- macOS

and supported Python versions, likely including current production-relevant versions such as:

- Python 3.11
- Python 3.12
- Python 3.13

Only claim versions actually tested.

Test supported current R versions based on what the actual ecosystem supports at implementation time.

Do not blindly claim Python/R versions that the backend stack cannot support.

Include separate or conditional jobs for:

- core Python tests
- core R tests
- interoperability tests
- conversion tests
- notebook tests
- docs examples
- package build
- wheel/sdist validation

Use scheduled compatibility jobs where useful to detect upstream breakage early.

---

# 50. GOOGLE COLAB / NOTEBOOK SMOKE TESTS

Create runnable notebook examples and smoke-test them where automation permits.

Required scenarios:

```text
fresh runtime
→ install RPython
→ setup
→ R detected/provisioned
→ install R package
→ run R code
→ transfer pandas data
→ return result
→ display R plot
→ use %%r
→ run diagnostics
```

Keep an explicit Colab example notebook in the repository.

---

# 51. DOCUMENTATION EXAMPLES ARE TESTS

Every critical README/docs example must be executable or mechanically validated.

Avoid documentation drift.

If API changes, CI should catch stale examples.

---

# 52. SELF-TEST EXPERIENCE

Implement a user-facing interoperability self-test.

Conceptual output:

```text
Python → R scalar           ✓
R → Python scalar           ✓
pandas → R data.frame       ✓
R data.frame → pandas       ✓
categorical/factor          ✓
datetime                    ✓
time series                 ✓
panel metadata              ✓
R package call              ✓
Python package call         ✓
plot transfer               ✓
Arrow transfer              ✓
Jupyter integration         ✓
```

`self_test(full=True)` may run slower tests and optional-package checks.

---

# 53. BALANCED EXCELLENCE GATE

This project must not have an intentionally weak core subsystem.

Do not compensate for a weak subsystem by making another subsystem excellent.

Before declaring release readiness, evaluate at least:

| Core area | Required quality |
|---|---|
| Python → R | production-quality |
| R → Python | production-quality |
| R packages | production-quality |
| Python packages | production-quality |
| conversion | production-quality |
| time series | first-class |
| panel data | first-class |
| database interoperability | robust |
| large data | robust fallback strategy |
| functions | bidirectional |
| model objects | conversion/proxy safety |
| results | easy and consistent |
| plotting | bidirectional and notebook-friendly |
| persistence | metadata-aware |
| Jupyter | officially tested |
| Colab | officially documented/tested |
| local scripts | officially tested |
| Windows | tested |
| Linux | tested |
| macOS | tested |
| environments | robust |
| diagnostics | strong |
| performance | benchmarked |
| Unicode/Arabic | tested |
| beginner API | simple |
| advanced API | powerful |
| documentation | comprehensive |
| CI/CD | comprehensive |
| round-trip fidelity | enforced |

---

# 54. DEFINITION OF DONE

The project is **not complete** merely because:

- Python can call R
- R can call Python
- DataFrames can move between them

Those are baseline capabilities already available elsewhere.

The project may be called release-ready only when all core acceptance gates are satisfied.

Minimum release checklist:

```text
[ ] package installs cleanly
[ ] Python runtime detected correctly
[ ] R runtime detected correctly
[ ] R packages can be installed/loaded
[ ] Python packages can be installed/loaded
[ ] Python → R execution works
[ ] R → Python execution works
[ ] round-trip conversion works for supported types
[ ] pandas/data.frame works
[ ] NumPy/matrix works
[ ] categorical/factor works
[ ] dates/timezones work
[ ] missing values are handled intentionally
[ ] time-series semantics are preserved
[ ] panel semantics are preserved
[ ] large-table transfer has a performant path
[ ] databases have a safe interoperability path
[ ] unknown package generic fallback works
[ ] unsupported rich object proxy works
[ ] model object workflow works
[ ] plots display and save correctly
[ ] save/load works
[ ] Jupyter magics work
[ ] Colab workflow works
[ ] environment doctor works
[ ] explain mode works
[ ] self-test works
[ ] failure paths are tested
[ ] Unicode/Arabic/French tests pass
[ ] README examples execute
[ ] docs build succeeds
[ ] wheel/sdist build succeeds
[ ] CI passes on supported systems
[ ] benchmark report is reproducible
[ ] no core TODO/FIXME/placeholders remain
```

If a genuinely unavoidable limitation exists, document:

- exact cause
- environments affected
- how RPython detects it
- fallback behavior
- user workaround

Do not hide limitations.

---

# 55. RELEASE READINESS REPORT

At the end of implementation, generate a real report such as:

```text
Subsystem                    Passed / Total    Status
----------------------------------------------------
R Runtime                    ... / ...         PASS
Python Runtime               ... / ...         PASS
Data Conversion              ... / ...         PASS
Time Series                  ... / ...         PASS
Panel Data                   ... / ...         PASS
Package Interop              ... / ...         PASS
Plotting                     ... / ...         PASS
Persistence                  ... / ...         PASS
Jupyter                      ... / ...         PASS
Colab                        ... / ...         PASS
Environment Management       ... / ...         PASS
Diagnostics                  ... / ...         PASS
Documentation Examples       ... / ...         PASS
```

Never invent test counts. Populate this from actual test runs.

A failed core subsystem means the release is not ready.

---

# 56. PROPOSED PROJECT STRUCTURE

Use a clean structure. Adapt as needed, but preserve separation of concerns.

Example:

```text
rpython/
├── pyproject.toml
├── README.md
├── LICENSE
├── CHANGELOG.md
├── CONTRIBUTING.md
├── CODE_OF_CONDUCT.md
├── MASTER_PROMPT.md
├── src/
│   └── rpython/
│       ├── __init__.py
│       ├── api.py
│       ├── config.py
│       ├── runtime/
│       │   ├── base.py
│       │   ├── router.py
│       │   ├── embedded_r.py
│       │   ├── process_r.py
│       │   └── remote.py
│       ├── conversion/
│       │   ├── registry.py
│       │   ├── semantic.py
│       │   ├── native.py
│       │   ├── arrow.py
│       │   ├── dates.py
│       │   ├── categories.py
│       │   └── missing.py
│       ├── data/
│       │   ├── envelope.py
│       │   ├── timeseries.py
│       │   ├── panel.py
│       │   └── formula.py
│       ├── packages/
│       │   ├── manager.py
│       │   ├── r_packages.py
│       │   └── py_packages.py
│       ├── env/
│       │   ├── detect.py
│       │   ├── doctor.py
│       │   ├── fix.py
│       │   └── lock.py
│       ├── proxy/
│       │   ├── r_object.py
│       │   └── py_object.py
│       ├── results/
│       │   ├── result.py
│       │   └── display.py
│       ├── plotting/
│       ├── persistence/
│       ├── database/
│       ├── notebook/
│       ├── diagnostics/
│       ├── compatibility/
│       └── cli.py
├── r-package/
│   ├── DESCRIPTION
│   ├── NAMESPACE
│   ├── R/
│   ├── tests/
│   └── vignettes/
├── compatibility/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── roundtrip/
│   ├── packages/
│   ├── notebook/
│   ├── colab/
│   ├── performance/
│   └── edge_cases/
├── docs/
├── examples/
├── notebooks/
├── assets/
└── .github/workflows/
```

Do not create giant files that mix unrelated concerns.

---

# 57. CODE QUALITY

Use:

- clear typed Python APIs
- focused modules
- helpful docstrings
- minimal public surface
- internal abstractions with clear boundaries
- structured logging
- reproducible tests
- linting/formatting
- static type checking where useful
- no unnecessary global state
- context managers for sessions/resources
- deterministic cleanup of worker processes/temp files

Avoid cleverness that makes debugging difficult.

---

# 58. EXTENSIBILITY API

Provide a documented way for contributors to add:

- converters
- semantic adapters
- package-specific adapters
- runtime backends
- persistence formats
- database adapters
- plotting adapters
- compatibility rules

A new converter should not require rewriting the runtime.

A new runtime should not require rewriting the semantic layer.

---

# 59. BENCHMARKING

Compare representative RPython workflows against relevant baseline approaches only when comparisons are fair.

Benchmark dimensions:

- startup time
- scalar calls
- DataFrame conversion
- Arrow transfer
- large table transfer
- plot return
- repeated function calls
- memory overhead

Publish methodology, hardware/environment metadata, and package versions.

Do not cherry-pick favorable numbers.

---

# 60. README COMPETITOR COMPARISON

Include a factual table titled something like:

## How RPython complements and extends existing R–Python tools

Possible dimensions:

| Capability | Typical existing approach | RPython target |
|---|---|---|
| Python → R | available in rpy2-style tools | high-level native-feel |
| R → Python | available in reticulate-style tools | symmetric native-feel |
| large data | manual Arrow setup may be needed | automatic transfer planner |
| time-series semantics | often manual | first-class semantic layer |
| panel semantics | often manual | first-class panel layer |
| unknown rich objects | conversion may fail | proxy fallback |
| environment debugging | manual/tool-specific | unified doctor/fix |
| package installation | separate ecosystems | unified package manager |
| notebooks | tool-specific magics | concise symmetric magics |
| conversion transparency | limited | explain mode |
| round-trip validation | usually not user-facing | fidelity engine |

Only publish claims verified against current documentation/tests.

---

# 61. REAL-WORLD END-TO-END SCENARIOS

Before release, execute complete workflows, not isolated unit calls.

## Scenario A — Python researcher using R econometrics

1. open Python/Jupyter
2. load pandas data
3. declare panel structure
4. install/load an R econometrics package
5. pass panel data to R
6. fit model
7. retrieve summary
8. plot diagnostics/results
9. save model/result
10. reload and inspect metadata

## Scenario B — R researcher using Python ML

1. open R
2. load a data.frame
3. access scikit-learn
4. split/train model
5. receive predictions
6. return them to R
7. plot/save results
8. preserve factor/date semantics

## Scenario C — Colab

1. fresh runtime
2. install RPython
3. setup
4. install R package
5. use `%%r`
6. transfer data
7. return plot/model
8. doctor/self-test

## Scenario D — Large data

1. large table
2. automatic transfer planner selects Arrow/lazy strategy
3. validate memory/performance
4. preserve types

## Scenario E — Unknown package/custom object

1. load package not in compatibility registry
2. call representative function
3. receive unknown native object
4. proxy created
5. inspect methods
6. call method
7. save/reload if feasible

---

# 62. DO NOT HIDE BACKEND LIMITATIONS; HIDE BACKEND COMPLEXITY

This distinction is essential.

The user should not need to know low-level backend details during normal use.

But if a backend limitation affects correctness, performance, or supported behavior, RPython must explain it honestly.

Never silently emulate success.

---

# 63. DEVELOPMENT EXECUTION STRATEGY

Use a disciplined implementation sequence, but continue through the whole task rather than stopping after each stage.

Suggested sequence:

1. inspect repository
2. re-research current competitors/issues
3. write architecture decision notes
4. scaffold Python package
5. scaffold R companion package
6. implement environment detection
7. implement runtime abstraction
8. implement primitive conversion
9. implement pandas/data.frame conversion
10. implement semantic metadata layer
11. implement dates/timezones/categories/missingness
12. implement time-series semantics
13. implement panel semantics
14. implement Arrow strategy
15. implement package managers
16. implement function/package call proxies
17. implement result/proxy system
18. implement plotting
19. implement persistence
20. implement database interoperability
21. implement magics
22. implement CLI/doctor/self-test/explain
23. implement compatibility registry/firewall
24. build exhaustive tests
25. run package torture tests
26. run cross-platform/version tests where available
27. run docs examples
28. fix all core failures
29. build README/docs/assets
30. build package artifacts
31. generate release readiness report

Do not wait for user confirmation between routine implementation stages.

---

# 64. TEST → FIX → RETEST LOOP

For every failure:

```text
Failure
  ↓
Reproduce
  ↓
Identify root cause
  ↓
Fix
  ↓
Run focused regression test
  ↓
Run related subsystem tests
  ↓
Run full relevant suite
  ↓
Continue
```

Maintain a visible internal issue list until all core issues are resolved.

Do not stop at the first error.

---

# 65. PACKAGE NAME / DISTRIBUTION CHECK

The repository is named `rpython` and the working import name is `rpython`.

Before publishing, verify:

- PyPI name availability/conflicts
- CRAN/R-package naming conflicts if an R companion package is published
- import-name clarity
- case-sensitivity concerns

Do not rename the repository silently. If a distribution-name conflict exists, preserve project identity and document the safest packaging choice.

---

# 66. AUTHOR / PROJECT METADATA

Use project owner information consistently:

**Dr. Merwan Roudane**

Repository:

https://github.com/merwanroudane/rpython

Add author metadata to packaging, docs, and citation information where appropriate.

Do not invent institutional affiliations that are not provided in the repository.

---

# 67. README HERO COPY — DIRECTION

Create a strong concise headline, for example in spirit:

> **R and Python, one seamless research workspace.**

Then a short description explaining that RPython provides a high-level, bidirectional, semantic bridge for code, packages, data, models, plots, databases, notebooks, and reproducible environments.

Do not overclaim “zero errors” or universal compatibility with every package in existence.

A more credible promise is:

> Common workflows should work automatically; unfamiliar or non-convertible objects should fall back safely to proxies or explicit diagnostics rather than silently corrupting meaning.

---

# 68. ACCEPTANCE PRINCIPLES TO KEEP VISIBLE DURING DEVELOPMENT

1. **R and Python are equal citizens.**
2. **Native code stays native whenever practical.**
3. **Common operations are one or a few clear lines.**
4. **Unknown package ≠ unsupported package.**
5. **Unknown object ≠ forced lossy conversion.**
6. **No silent semantic corruption.**
7. **No silent timezone reinterpretation.**
8. **No silent panel/time-series metadata loss.**
9. **Large data should not be copied blindly.**
10. **Notebook convenience must not break script usage.**
11. **A clean beginner API must coexist with advanced controls.**
12. **Errors must explain what to do next.**
13. **README examples must actually run.**
14. **Documentation is part of the product.**
15. **One strong subsystem does not excuse a weak one.**
16. **Do not declare completion while core tests fail.**

---

# 69. FINAL DELIVERABLES

By the end, the repository should contain, at minimum:

- complete Python package
- complete R-facing companion layer/package required for symmetry
- clean public API
- runtime router
- semantic data layer
- time-series support
- panel-data support
- package managers
- environment manager
- Arrow/large-data strategy
- result/proxy system
- plotting support
- persistence layer
- database layer
- Jupyter magics
- Colab workflow
- CLI
- doctor/check/self-test/fix/restore/explain tooling
- compatibility registry
- comprehensive automated tests
- benchmark suite
- CI workflows
- README suitable for GitHub and PyPI
- beginner command catalog
- full documentation
- logo/visual assets or professional SVG equivalents
- runnable notebooks/examples
- packaging metadata
- changelog/contributing/license files
- release-readiness report based on real tests

---

# 70. FINAL INSTRUCTION

Build RPython as a **coherent interoperability platform**, not a collection of unrelated helpers.

The target user experience is:

```text
Native R Experience
        ↕
Semantic, high-level, safe interoperability layer
        ↕
Native Python Experience
```

The user should be able to work with:

- code
- variables
- functions
- packages
- data
- time series
- panel data
- databases
- models
- results
- plots
- files
- saving/loading
- Jupyter
- Colab
- local scripts
- environments
- dependencies

without repeatedly fighting conversion boilerplate or runtime configuration.

At the same time, the library must remain honest about cases that cannot be represented losslessly.

The ultimate quality bar is not “can R call Python?” or “can Python call R?”

The quality bar is:

> **Can a beginner, researcher, advanced user, and developer each use the same system at the level of abstraction they need, while preserving correctness, semantic meaning, reproducibility, extensibility, and native-language feel?**

Do not consider the project finished until the answer is supported by real tests, real examples, and complete documentation.
