# Installation

## Python package

Releases: https://pypi.org/project/rpython-bridge/

```bash
pip install rpython-bridge                 # core: numpy, pandas
pip install "rpython-bridge[all]"          # all optional families
pip install "rpython-bridge[arrow,database,spatial]"
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
