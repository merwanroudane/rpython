# Saving and loading

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
