# Large data

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
