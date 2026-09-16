"""Write the docs/*.md pages (except the hand-maintained data-structures-catalog.md).

Run: python tools/make_docs.py
Keeping the pages here makes "docs are tests" simple: tests/docs extracts every ```python block.
"""
import os

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")
docs: dict[str, str] = {}

docs["beginner-catalog.md"] = r'''# Beginner Command Catalog

Every entry: what it does, why the important line exists, what comes back, what to expect, common mistakes.
All Python blocks run as-is (they are part of the test suite).

## A. Starting / setup

```python
import rpython as rp
r = rp.R()          # starts an isolated R worker (or reuses the default one); r.capabilities tells you what R has
print(r.capabilities["r_version"])
print(rp.check())   # True when R answers; rp.doctor() prints the full report
```

* **Returns:** an `RSession`. Creating a second `rp.R(timeout=60)` with arguments starts a *new* worker.
* **Mistake:** calling `rp.R()` in a loop expecting fresh state — the default session persists (`r.restart()` resets it).

From R: `library(rpython); py <- python()` (needs `pip install rpython` in the chosen interpreter; set `RPYTHON_PYTHON` to pin it).

## B. Packages

```python
import rpython as rp
r = rp.R()
stats = r.package("stats")               # load (attaches nothing; functions are called as stats::name)
print(stats.median([3, 1, 2]))            # 2.0
print(r.installed("stats", "notapkg"))    # {'stats': True, 'notapkg': False}
# r.install("plm")                        # CRAN; "user/repo" -> GitHub; source="bioc" -> Bioconductor
```

* Dotted names: `forecast.auto_arima` resolves to `forecast::auto.arima`; keyword `n_ahead=` becomes `n.ahead=` when R expects it.
* **Mistake:** `r("library(plm)")` then `r("plm(...)")` works too, but `r.package("plm").plm(...)` is explicit and needs no attach.

## C. Data

```python
import numpy as np, pandas as pd, rpython as rp
r = rp.R()
r["v"] = [1.0, None, float("nan")]       # None -> NA, nan -> NaN (explicit tokens on the wire)
r["m"] = np.arange(6.0).reshape(2, 3)    # numpy -> matrix; m[1,2] in R == m[0,1] in Python
r["d"] = {"a": 1, "b": ["x", "y"]}       # dict -> named list
df = pd.DataFrame({"g": pd.Categorical(["a", "b"], ordered=True), "t": pd.date_range("2024", periods=2, tz="UTC")})
r["df"] = df                              # categories + order + timezone preserved
print(r("levels(df$g)"), r("attr(df$t, 'tzone')"))
print(type(r["df"]).__name__, r["df"].equals(df))
```

Declaring structure (never guessed silently):

```python
import numpy as np, pandas as pd, rpython as rp
panel = rp.panel(pd.DataFrame({"id": ["a", "a", "b", "b"], "year": [1, 2, 1, 2], "y": [1., 2., 3., 4.]}), id="id", time="year")
ts = rp.timeseries(pd.DataFrame({"date": pd.date_range("2020-01-01", periods=6, freq="MS"), "y": range(6)}), time="date", freq="MS")
lab = rp.labelled(pd.DataFrame({"sex": [1, 2]}), value_labels={"sex": {1: "male", 2: "female"}}, variable_labels={"sex": "Sex"})
sv = rp.survival(pd.DataFrame({"t": [1., 2.], "d": [1, 0]}), time="t", event="d")
for obj in (panel, ts, lab, sv):
    print(obj.describe_structure().splitlines()[0])
```

## D. Code execution

```python
import rpython as rp
r = rp.R()
print(r("1 + 1"))                          # single expression -> value
res = r.eval("""
x <- 1:10
cat("sum:", sum(x), "\n")
mean(x)
""")                                       # multi-line block -> Result
print(res.stdout, res.value)
print(r.call("paste", "a", "b", sep="-"))  # call a function with positional and keyword args
```

* `r.source("script.R")` runs a file; `r.function("name")` binds a function.
* **Mistake:** forgetting that R code runs in the worker's own environment — variables set with `r["x"]` are visible, Python variables are not (send them first).

## E. Results

```python
import rpython as rp
r = rp.R()
fit = r("lm(mpg ~ wt, data = mtcars)")     # rich object -> RObjectProxy (stays in R)
print(fit.rclass, fit.package)             # ['lm'] stats
print(fit.coef())                          # pandas Series
print(fit.summary().r_squared > 0.7)       # nested proxies; fields with dots use underscores
print(fit.fields()[:3], fit.methods()[:3])
plain = fit.to_python()                    # forced conversion to a dict (structure kept, class recorded)
print(type(plain).__name__)
try:
    r("stop('boom')")
except rp.RError as e:
    print(str(e).splitlines()[0])          # R error: boom
```

## F. Notebook / Colab

```text
%load_ext rpython     # or rp.setup()
%r summary(mtcars$mpg)
%%r -i df -o fit
fit <- lm(y ~ x, data = df)
```

`-i` sends notebook variables, `-o` brings R variables back, `-s` silent, `-v` prints Explain Mode after the cell.
Plots display automatically. Colab: `!pip install rpython` then `rp.setup()`; `rpython lock` / `rp.restore()` for fresh runtimes.

## G. Save / load

```python
import pandas as pd, rpython as rp
df = pd.DataFrame({"c": pd.Categorical(["a", "b"], ordered=True)})
rp.save(df, "d.parquet")                   # lossless
rp.save(df, "d.csv")                       # warns + sidecar d.csv.rpx.json
print(rp.load("d.csv")["c"].cat.ordered)   # True
b = rp.save(df, "d.rpx")                   # universal bundle (manifest + portable + native)
print(rp.load(b).equals(df))
```

Models: `fit.save("fit.rds")`, `rp.load("fit.rds", session=r)`; plots: `res.plot.save("p.png")`, `g.save("g.svg")`.

## H. Diagnostics

```python
import rpython as rp
r = rp.R()
r["x"] = [1, 2, 3]
rp.explain_last()                          # plan, transfer path, fidelity for the last transfer
rep = rp.validate_roundtrip([1.0, None, 3.0], r)
print(rep.summary().splitlines()[-1])      # Overall: lossless
```

`rp.doctor()`, `rp.check()`, `rp.self_test(full=True)`, `rp.fix()`, `rp.restore("rpython.lock")`; CLI: `rpython doctor`, `rpython self-test --full`, `rpython env`, `rpython catalog`.
'''

docs["installation.md"] = r'''# Installation

## Python package

```bash
pip install rpython                 # core: numpy, pandas
pip install "rpython[all]"          # all optional families
pip install "rpython[arrow,database,spatial]"
```

| Extra | Adds | Enables |
|---|---|---|
| `arrow` | pyarrow | Arrow IPC transfer, Arrow datasets, Parquet |
| `polars` | polars | Polars DataFrame/LazyFrame |
| `sparse` | scipy | sparse matrices, DTMs, spatial weights |
| `spatial` | shapely, pyproj, geopandas | sf ↔ GeoDataFrame, CRS objects |
| `network` | networkx | igraph ↔ networkx |
| `database` | sqlalchemy, duckdb | SQL dialects, DuckDB, Parquet lakes |
| `scientific` | xarray, netCDF4 | xarray ↔ stars / labelled arrays |
| `survey` | pyreadstat | Stata / SPSS / SAS files with labels |
| `survival` | lifelines | survival helpers |
| `ml` | torch | tensors |
| `notebook` | ipython | magics |

## R side

Driving R from Python needs only R (≥ 4.2) and `jsonlite`; the companion code is bundled and sourced into the worker.
Recommended: `install.packages(c("arrow", "data.table", "Matrix", "xts", "zoo", "haven", "survival", "sf", "igraph", "plm", "duckdb", "RSQLite", "dbplyr"))` or `rp.fix()`.

Driving Python from R needs the R package:

```r
remotes::install_github("merwanroudane/rpython", subdir = "r-package")
```

## Verify

```bash
rpython doctor
rpython self-test --full
```
'''

docs["quickstart.md"] = r'''# Quickstart

```python
import pandas as pd, rpython as rp
r = rp.R()
df = pd.DataFrame({"x": [1., 2., 3.], "g": pd.Categorical(["a", "b", "a"])})
r["df"] = df
fit = r("lm(x ~ g, data = df)")
print(fit.coef())
back = r["df"]
assert back.equals(df)
rp.explain_last()
```

From R:

```r
library(rpython)
py <- python()
pd <- py$package("pandas")
df <- pd$DataFrame(list(x = c(1, 2, 3)))
py_to_r(df)
```

Next: [beginner catalog](beginner-catalog.md), [data conversion](data-conversion.md), [catalog of data structures](data-structures-catalog.md).
'''

docs["data-conversion.md"] = r'''# Data conversion

## The rules

1. **Detection → classification → negotiation → best path → fidelity → proxy fallback.** See `rp.explain_last()`.
2. **Never silently lossy.** `rp.config(lossy="warn"|"error"|"allow")` decides what happens when a target cannot hold a semantic; the default warns and records the loss in the fidelity report.
3. **Missing values are explicit.** `None`/`pd.NA` ↔ `NA`; `nan` ↔ `NaN` for scalars/arrays; pandas float64 `NaN` ↔ `NA` (pandas semantics) unless `rp.config(missing="nan")`.
4. **Unknown ≠ unsupported.** Anything without an adapter becomes a proxy; `rp.register_converter()` adds an exact adapter without touching the core.

## Choosing the transfer path

`rp.config(transfer="auto"|"arrow"|"json")`; `arrow_threshold_rows` (default 5 000). Arrow needs `pyarrow` in Python and `arrow` in R; otherwise JSON is used and reported.

## Per-family details

See [data-structures-catalog.md](data-structures-catalog.md).

## Extending

```python
import rpython as rp

class Money:
    def __init__(self, amount, ccy): self.amount, self.ccy = amount, ccy

rp.register_converter(family="money", kind="money", detect=lambda o: isinstance(o, Money),
                      encode=lambda o, ctx: {"amount": o.amount, "ccy": o.ccy},
                      decode=lambda env, ctx: Money(env["amount"], env["ccy"]))
back, ctx = rp.roundtrip(Money(5, "EUR"))
print(back.ccy, ctx.plan.family)
```

R side: `rpx_register_decoder("money", function(env) structure(list(amount = env$amount, ccy = env$ccy), class = "money"))` and `rpx_register_encoder(function(x) inherits(x, "money"), function(x) list(rpx = 1L, kind = "money", amount = x$amount, ccy = x$ccy))`.
'''

docs["time-series.md"] = r'''# Time series

| Python | R | When |
|---|---|---|
| `Series`/`DataFrame` with `DatetimeIndex` (freq 1/4/12/52/7/24/365) or `PeriodIndex` | `ts` / `mts` | regular, no tz, no duplicates |
| irregular, tz-aware, duplicates | `xts` (or `zoo`) | |
| `rp.timeseries(df, time=, ids=[...])` | `tsibble` | keyed / grouped |

```python
import numpy as np, pandas as pd, rpython as rp
r = rp.R()
y = pd.Series(np.arange(12.), index=pd.date_range("2021-01-01", periods=12, freq="MS"))
r["y"] = y
print(r("frequency(y)"), r("start(y)"))
fc = r.package("stats").arima(y, order=[1, 0, 0])   # any R time-series function
print(fc.rclass)
print(rp.timeseries(y).describe_structure())
```

Preserved: values, index, frequency, timezone, missing periods, duplicate timestamps, series names, seasonal period.
R `ts` objects with unusual frequencies decode to a numeric time index (documented limitation).
'''

docs["panel-data.md"] = r'''# Panel data

```python
import numpy as np, pandas as pd, rpython as rp
r = rp.R()
pdf = pd.DataFrame({"country": np.repeat(["FR", "DE"], 3), "year": [2000, 2001, 2002] * 2, "y": np.arange(6.), "x": np.arange(6.) ** 2})
p = rp.panel(pdf, id="country", time="year")
print(p.describe_structure())
r["p"] = p
if r.capabilities["packages"].get("plm"):
    fit = r("plm::plm(y ~ x, data = p, model = 'within')")
    print(fit.coef())
back = r["p"]
print(back.index.names)
```

* `rp.cross_section(df, id=, weight=, strata=, cluster=)`, `rp.repeated_cross_section(df, wave=)` (never treated as a panel), `rp.hierarchical(df, levels=[...])`.
* Duplicated `(id, time)` keys cannot become a `pdata.frame`: the data.frame + `rpython.panel` attribute is used and the duplicates are counted.
* A DataFrame that *looks* like a panel is only ever *suggested* in Explain Mode.
'''

docs["databases.md"] = r'''# Databases

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
'''

docs["large-data.md"] = r'''# Large data

* Tables ≥ 5 000 rows and arrays ≥ 50 000 elements use Arrow IPC files in the session work directory (one copy, no JSON).
* `pyarrow.dataset` / `arrow::open_dataset` share the **file list** — nothing is copied.
* Rasters (`rp.raster(path)`), NetCDF (`rp.netcdf(path)`), media files: lazy references.
* Databases: shared connections and query pushdown; `to_arrow_batches()` for streaming.
* Lazy objects (`rp.lazy(obj)`, generators, Dask, Polars LazyFrame above the threshold) stay in Python behind a proxy.
* Memory guard: `rp.config(memory_threshold_bytes=512*1024**2)`; override per call with `allow_materialize=True`.

```python
import numpy as np, pandas as pd, rpython as rp
r = rp.R()
r["big"] = pd.DataFrame({"a": np.arange(100000), "b": np.random.rand(100000)})
print("arrow-ipc" in rp.explain_last(print_it=False))
print(r("nrow(big)"))
```
'''

docs["functions.md"] = r'''# Functions across the boundary

```python
import rpython as rp
r = rp.R()
r("sq <- function(x, k = 2) x^k")
sq = r.function("sq")
print(sq(3), sq(3, k=3))                      # 9.0 27.0
print(r.signature("sq"))                      # arguments and defaults
r["pyf"] = lambda a, b=1: a + b               # Python callable usable from R
print(r("pyf(2, b = 40)"))                    # 42.0
r["df_fn"] = lambda df: df.assign(z=df["x"] * 2)
print(r("df_fn(data.frame(x = 1:2))$z"))      # [2 4]
```

Warnings, messages and errors raised inside the callee are captured and re-raised on the caller's side with context.
'''

docs["models-and-proxies.md"] = r'''# Models and proxies

```python
import pandas as pd, rpython as rp
r = rp.R()
fit = r("glm(am ~ wt, data = mtcars, family = binomial)")
print(fit.rclass)                                   # ['glm', 'lm']
print(fit.predict(newdata=pd.DataFrame({"wt": [2.5]}), type="response"))
print(fit.aic, fit.summary().coefficients.shape)    # fields and nested proxies
fit.save("model.rds")
again = rp.load("model.rds", session=r, convert=False)
print(again.rclass)
```

Python objects in R: `r["model"] = sklearn_model` then `model$predict(X)` in R. Objects always return as the same Python object.
'''

docs["plotting.md"] = r'''# Plotting

```python
import rpython as rp
r = rp.R()
res = r.eval("plot(mtcars$wt, mtcars$mpg)")
res.plot.save("scatter.png")
g = r("ggplot2::ggplot(mtcars, ggplot2::aes(wt, mpg)) + ggplot2::geom_point()")
g.save("scatter.svg")                       # png / svg / pdf (ggsave); html for htmlwidgets
print(r.last.plot is not None)
```

Base graphics, ggplot2, lattice go to PNG automatically; in Jupyter they display inline. Python matplotlib figures created inside a Python worker driven by R are captured the same way.
'''

docs["saving-loading.md"] = r'''# Saving and loading

| Extension | Writer | Lossless? |
|---|---|---|
| `.parquet` / `.feather` / `.arrow` | pandas/pyarrow (GeoParquet for GeoDataFrames) | ✓ (+attrs via sidecar) |
| `.csv` / `.tsv` / `.xlsx` / `.json` | pandas | ⚠ warns, writes `.rpx.json` sidecar restoring dtypes, categories, tz, index, semantic blocks |
| `.rds` / `.RData` | R worker | ✓ (R objects and anything convertible) |
| `.dta` / `.sav` / `.xpt` | pyreadstat with labels | ✓ labels |
| `.nc` / `.zarr` | xarray | ✓ |
| `.gpkg` / `.geojson` / `.shp` / `.fgb` | geopandas | ✓ (shapefile limitations warned) |
| `.tif` | rasterio | ✓ |
| `.graphml` / `.gexf` | networkx | ✓ |
| `.npy` / `.npz` | numpy | ✓ |
| `.pkl` | pickle | warned (code execution on load) |
| `.rpx` | universal bundle | ✓ everything |

```python
import pandas as pd, rpython as rp
b = rp.save(pd.DataFrame({"a": [1]}), "x.rpx")
from rpython.persistence.io import bundle_info
print(bundle_info(b)["family"])
```
'''

docs["jupyter-colab.md"] = r'''# Jupyter and Google Colab

```text
%load_ext rpython
%r 1 + 1
%%r -i df -o model -v
model <- lm(y ~ x, data = df)
%%py
import polars as pl
```

Colab (fresh runtime):

```text
!pip install "rpython[arrow]"
import rpython as rp
r = rp.setup()          # R is preinstalled on Colab; rp.doctor() otherwise explains how to add it
r.install("plm")
```

Restore after a runtime reset: `rp.restore("rpython.lock")` (create it with `rpython lock`).
The notebook `notebooks/colab_quickstart.ipynb` walks through install → setup → R package → data transfer → plot → magics → diagnostics.
'''

docs["diagnostics.md"] = r'''# Diagnostics

| Call | Purpose |
|---|---|
| `rp.doctor()` | platform, Python, every R installation found and which one is used, key packages on both sides, worker readiness, round-trip and plot checks, issues + fixes |
| `rp.check()` | one-second readiness |
| `rp.self_test(full=True)` | 25+ interoperability checks across families |
| `rp.fix()` | installs pyarrow / core R packages (never touches system settings) |
| `rp.restore(lock)` | reinstalls what `rpython.lock` lists |
| `rpython env --json` | machine-readable runtime report |

Errors are human-readable and actionable (`RError`, `ConversionError`, `MemoryGuardError`) with the raw traceback attached.
'''

docs["explain-mode.md"] = r'''# Explain Mode

Every transfer records a plan: source, target, detected family, transfer backend and tier, payload size, copies, per-step notes, risks and a fidelity report.

```python
import pandas as pd, rpython as rp
plan = rp.explain_plan(pd.DataFrame({"country": ["FR", "FR", "DE", "DE"], "year": [2000, 2001, 2000, 2001], "v": [1., 2., 3., 4.]}), print_it=False)
print(plan.family, [n for n in plan.notes if "suggestion" in n][:1])
```

`rp.explain_last()`, `rp.explain(n)` (history), `rp.explain_plan(obj)` (dry run). R side: `rpx_explain(x)`.
'''

docs["compatibility.md"] = r'''# Compatibility policy

* **Capability detection** over version pinning; the R worker reports installed packages, Python probes optional imports.
* **Fallback chains** per family: Arrow → JSON → proxy; plm → data.frame + attribute; geopandas → pandas + shapely; xts → zoo → data.frame.
* **Registry** (`compatibility/*.yaml`): tested versions, preferred paths, known issues. Not a whitelist.
* Tested: Python 3.11 / pandas 3.0 / numpy 2.4 / pyarrow 25 / polars 1.44; R 4.5.2 with arrow, sf, igraph, Matrix, xts, haven, survival, plm, duckdb. CI covers Python 3.11–3.13 on Linux, macOS, Windows.
* Upstream changes are caught by the scheduled compatibility workflow (`compat.yml`) which installs the latest pandas/pyarrow/R packages and reruns the round-trip matrix.
'''

docs["troubleshooting.md"] = r'''# Troubleshooting

See the table in the README first. Additional cases:

* **`TimeoutError: R call exceeded N s`** — pass `timeout=None` to `rp.R()` or the call; long installations use `r.install(..., timeout=3600)`.
* **R worker dies during a package call** — the Python process is intact; `r.restart()`; report the package with `rp.doctor()` output. The crash is isolated by design.
* **Unicode garbled on Windows consoles** — set `PYTHONIOENCODING=utf-8`; data itself is UTF-8 end to end.
* **`ConversionError: optional dependency missing`** — the message names the extra to install (`pip install "rpython[spatial]"`).
* **`MemoryGuardError`** — use pushdown/lazy paths or `allow_materialize=True`.
* **Proxy used after `r.close()`** — proxies belong to a session; reopen and recreate.
'''

docs["architecture.md"] = r'''# Architecture

```text
Public API (rp.*, RSession, proxies, rp.panel/...)      R package (python(), rpx_*)
            │                                                    │
Semantic data layer: registry of adapters (tiers A→E), Context/TransferPlan, fidelity
            │
Portable envelope (RPX v1): JSON + Arrow IPC + WKB + handles + shared paths
            │
Transport: newline-delimited JSON over stdio (Python→R worker) or TCP (R→Python worker); "@RPX@" framing
            │
Workers: Rscript running rpython_worker()  |  python -m rpython.worker
```

* `data/semantic.py` model, `data/registry.py`, `data/context.py`, `data/convert.py`, one module per family.
* `database/` base (ConnectionRef, SecretVault, adapters), `relation.py` (lazy Relation + envelope), `registry.py`, `api.py`.
* `runtime/r_session.py` process lifecycle, protocol, callbacks (R calling Python proxies while Python waits).
* `proxy/` RObjectProxy / RPackage / RFunction. `results/` Result, Plot, RError. `persistence/` save/load/bundle.
* `diagnostics/`, `env/` (detection, lock), `notebook/magics.py`, `cli.py`, `worker.py`.
* `r-package/R/`: `aaa_state.R`, `rpx_encode.R`, `rpx_decode.R`, `worker.R`, `python.R`, `pyproxy.R`, `db.R`.

Design principles: R and Python are equal citizens; native code stays native; no silent semantic corruption; large data is not copied blindly; hide backend complexity, never backend limitations.
'''

docs["faq.md"] = r'''# FAQ

**Is RPython a replacement for rpy2 / reticulate?** It is a higher-level, symmetric alternative built on process isolation and a semantic envelope. If you need in-process embedding for micro-latency, rpy2/reticulate remain excellent choices.

**Does it copy my data twice?** Small objects go through JSON once; tables use Arrow IPC (one file write/read); datasets, rasters and databases are shared, not copied.

**What happens with an object it has never seen?** It becomes a proxy; you can still call its methods and force a (documented) conversion with `.to_python()` / `py_to_r()`.

**Are RNG streams equivalent?** No. Data crosses faithfully; random number generators differ. `rp.simulation()` says so explicitly.

**Why does `NaN` in a pandas column become `NA` in R?** Because pandas uses `NaN` as its missing marker in float64 columns. `rp.config(missing="nan")` keeps `NaN`.

**Can I use it without Jupyter?** Yes — scripts, VS Code, the CLI and plain R sessions all use the same API.
'''

docs["environments.md"] = r'''# Environments

RPython detects: system Python, venv, uv, conda, Poetry, Jupyter kernels, VS Code, Colab, Docker; multiple R installations (registry, PATH, `R_HOME`, standard locations). It never picks an R at random: explicit configuration wins, then environment variables, then PATH, then the highest version — and `rp.doctor()` lists every candidate.

```bash
rpython env            # what will be used
rpython lock           # write rpython.lock (Python + R packages, platform, runtime settings)
rpython restore        # reinstall from it
```

`rpython.lock` orchestrates native lock files (`uv.lock`, `requirements.txt`, `renv.lock`) rather than replacing them.
'''

docs["packages.md"] = r'''# Packages

| | Python side | R side |
|---|---|---|
| install R packages | `r.install("plm", "fixest")`, `r.install("user/repo")`, `source="bioc"` | `install.packages()` |
| install Python packages | `pip install ...` | `py$install("polars", source = "pip")` (or `"uv"`, `"conda"`) |
| load | `r.package("plm")` | `py$package("sklearn.linear_model")` |
| list what the bridge sees | `rpython packages` | `py$capabilities` |

Unknown packages are used through the generic path: load → call → inspect result → convert or proxy. Compilation, system libraries, CUDA etc. are reported with the R/pip output rather than pretended away.
'''

if __name__ == "__main__":
    os.makedirs(ROOT, exist_ok=True)
    for name, text in docs.items():
        with open(os.path.join(ROOT, name), "w", encoding="utf-8") as f:
            f.write(text.lstrip("\n"))
    print("wrote", ", ".join(sorted(docs)))
