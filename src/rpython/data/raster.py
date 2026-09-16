"""Raster / grid / earth-observation data (section 18) with lazy behaviour.

Two envelope forms:

* ``kind: "raster_ref"`` -- a **shared file reference** (GeoTIFF, NetCDF,
  ...) opened lazily on the other side (``terra::rast(path)`` /
  ``stars::read_stars(path, proxy = TRUE)`` in R, ``rasterio.open`` /
  ``rioxarray.open_rasterio`` in Python).  Nothing is copied.
* ``kind: "raster"`` -- an in-memory grid: an ``array`` envelope plus
  ``geotransform``, ``crs``, ``nodata``, ``bands``, ``units``.  Subject to
  the memory guard; large rasters must go through a file reference.

Preserved either way: extent, resolution, dimensions, bands, CRS,
geotransform, nodata, masks (via nodata), units, band/time coordinates.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .context import Context
from .registry import Adapter, REGISTRY
from .semantic import Confidence, ConversionPath, Detection, Fidelity
from .spatial import crs_block, crs_from_block

RASTER_EXTS = (".tif", ".tiff", ".gtiff", ".nc", ".img", ".vrt", ".asc", ".grd", ".jp2", ".hdf", ".h5", ".zarr")


@dataclass
class RasterRef:
    """Lazy reference to a raster file: ``rp.raster("dem.tif")``."""

    path: str
    driver: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def describe(self) -> dict[str, Any]:
        if self.metadata:
            return self.metadata
        meta = _read_raster_header(self.path)
        self.metadata = meta
        return meta

    def open(self) -> Any:
        try:
            import rasterio
            return rasterio.open(self.path)
        except ImportError:
            try:
                import rioxarray
                return rioxarray.open_rasterio(self.path, chunks="auto")
            except ImportError as e:
                raise ImportError("open a raster with rasterio or rioxarray: pip install 'rpython[spatial]' rasterio") from e

    def describe_structure(self) -> str:
        m = self.describe()
        lines = ["Type: Raster (lazy file reference)", f"Path: {self.path}", f"Driver: {m.get('driver') or self.driver or 'unknown'}"]
        for k in ("width", "height", "bands", "dtype", "crs", "resolution", "extent", "nodata", "units"):
            if m.get(k) is not None:
                v = m[k]
                if k == "crs" and isinstance(v, dict):
                    v = v.get("input") or v.get("epsg")
                lines.append(f"{k.capitalize()}: {v}")
        lines.append("Loaded in memory: no")
        return "\n".join(lines)


@dataclass
class Raster:
    """In-memory raster: ``rp.raster(array, transform=(x0, dx, 0, y0, 0, -dy), crs=..., nodata=...)``.

    ``array`` is (bands, rows, cols) or (rows, cols); ``transform`` is a GDAL
    6-tuple geotransform ``(x_origin, pixel_w, row_rot, y_origin, col_rot, pixel_h)``.
    """

    array: np.ndarray
    transform: tuple[float, float, float, float, float, float]
    crs: Any = None
    nodata: float | None = None
    bands: list[str] | None = None
    units: str | None = None
    time: list[str] | None = None

    @property
    def extent(self) -> tuple[float, float, float, float]:
        rows, cols = self.array.shape[-2], self.array.shape[-1]
        x0, dx, _, y0, _, dy = self.transform
        return (x0, y0 + dy * rows, x0 + dx * cols, y0) if dy < 0 else (x0, y0, x0 + dx * cols, y0 + dy * rows)

    def describe_structure(self) -> str:
        c = crs_block(self.crs)
        return "\n".join(["Type: Raster (in memory)",
                          f"Dimensions: {self.array.shape[-2]} rows x {self.array.shape[-1]} cols x {self.array.shape[0] if self.array.ndim == 3 else 1} band(s)",
                          f"Resolution: {abs(self.transform[1])}, {abs(self.transform[5])}",
                          f"Extent: {self.extent}",
                          f"CRS: {(c or {}).get('input') or 'undefined'}",
                          f"Nodata: {self.nodata}", f"dtype: {self.array.dtype}"])


def raster(source: Any, **kw: Any) -> RasterRef | Raster:
    if isinstance(source, (str, os.PathLike)):
        return RasterRef(str(source), **kw)
    return Raster(np.asarray(source), **kw)


def _read_raster_header(path: str) -> dict[str, Any]:
    try:
        import rasterio
        with rasterio.open(path) as ds:
            return {"driver": ds.driver, "width": ds.width, "height": ds.height, "bands": ds.count,
                    "dtype": str(ds.dtypes[0]), "crs": crs_block(ds.crs.to_wkt() if ds.crs else None),
                    "transform": list(ds.transform.to_gdal()), "resolution": list(ds.res),
                    "extent": list(ds.bounds), "nodata": ds.nodata, "units": list(ds.units) if ds.units else None,
                    "band_names": list(ds.descriptions) if ds.descriptions else None}
    except ImportError:
        pass
    except Exception as e:  # unreadable file: report, do not guess
        return {"error": str(e)}
    try:
        import rioxarray
        da = rioxarray.open_rasterio(path, chunks="auto")
        return {"driver": None, "width": int(da.rio.width), "height": int(da.rio.height), "bands": int(da.sizes.get("band", 1)),
                "dtype": str(da.dtype), "crs": crs_block(da.rio.crs.to_wkt() if da.rio.crs else None),
                "transform": list(da.rio.transform().to_gdal()), "resolution": list(da.rio.resolution()),
                "extent": list(da.rio.bounds()), "nodata": da.rio.nodata}
    except Exception:
        return {"driver": None, "note": "install rasterio to read raster headers in Python; R side (terra) reports them"}


def _is_rasterio_dataset(obj: Any) -> bool:
    return type(obj).__module__.startswith("rasterio") and hasattr(obj, "name") and hasattr(obj, "transform")


class RasterAdapter(Adapter):
    family = "raster"
    kinds = ("raster", "raster_ref")
    tier = ConversionPath.LAZY
    priority = 11
    r_requires = ("terra",)

    def detect(self, obj: Any) -> Detection | None:
        if isinstance(obj, RasterRef):
            return Detection("raster (file reference)", Confidence.CONFIRMED, obj.path)
        if isinstance(obj, Raster):
            return Detection("raster (in memory)", Confidence.CONFIRMED, str(obj.array.shape))
        if _is_rasterio_dataset(obj):
            return Detection("raster (open dataset)", Confidence.CONFIRMED, "rasterio")
        if isinstance(obj, str) and obj.lower().endswith(RASTER_EXTS) and os.path.exists(obj):
            return Detection("raster file path", Confidence.AMBIGUOUS, "use rp.raster(path) to share it lazily")
        return None

    def encode(self, obj: Any, ctx: Context) -> dict[str, Any]:
        if _is_rasterio_dataset(obj):
            obj = RasterRef(obj.name, driver=obj.driver)
        if isinstance(obj, RasterRef):
            meta = obj.describe()
            env = {"rpx": 1, "kind": "raster_ref", "path": os.path.abspath(obj.path), "driver": meta.get("driver") or obj.driver,
                   "header": {k: v for k, v in meta.items() if k != "error"}, "lazy": True,
                   "meta": {"source_class": "rpython.RasterRef"}}
            ctx.record("raster", ConversionPath.LAZY, "shared-file",
                       f"{obj.path} opened lazily on target (terra::rast); nothing materialised")
            ctx.plan.copies = 0
            ctx.plan.fidelity.set("laziness", Fidelity.LOSSLESS, "on-disk on both sides")
            ctx.plan.fidelity.set("crs", Fidelity.LOSSLESS if meta.get("crs") else Fidelity.NA, "read from file by both runtimes")
            ctx.plan.fidelity.set("values", Fidelity.LOSSLESS)
            return env
        r: Raster = obj
        est = int(r.array.nbytes)
        ctx.memory_guard(f"in-memory raster {r.array.shape}", est, "write it to GeoTIFF and pass rp.raster(path)")
        from .arrays import ArrayAdapter
        arr_env = ArrayAdapter().encode(r.array, ctx)
        env = {"rpx": 1, "kind": "raster", "array": arr_env, "geotransform": list(r.transform),
               "crs": crs_block(r.crs), "nodata": r.nodata, "bands": r.bands, "units": r.units, "time": r.time,
               "extent": list(r.extent), "resolution": [abs(r.transform[1]), abs(r.transform[5])],
               "layout": "bands,rows,cols" if r.array.ndim == 3 else "rows,cols",
               "meta": {"source_class": "rpython.Raster"}}
        ctx.record("raster", ConversionPath.ADAPTER, ctx.plan.backend,
                   f"in-memory raster {r.array.shape} + geotransform/CRS/nodata -> terra::rast")
        if r.crs is None:
            ctx.warn("raster has no CRS: kept undefined (never assumed)")
        ctx.plan.fidelity.set("crs", Fidelity.LOSSLESS if r.crs is not None else Fidelity.NA)
        ctx.plan.fidelity.set("values", Fidelity.LOSSLESS)
        ctx.plan.fidelity.set("shape", Fidelity.LOSSLESS)
        return env

    def decode(self, env: dict[str, Any], ctx: Context) -> Any:
        if env["kind"] == "raster_ref":
            ref = RasterRef(env["path"], driver=env.get("driver"), metadata=env.get("header") or {})
            ctx.record("raster", ConversionPath.LAZY, "shared-file", "terra/stars object -> RasterRef (lazy)")
            ctx.plan.fidelity.set("laziness", Fidelity.LOSSLESS)
            return ref
        from .arrays import ArrayAdapter
        arr = np.asarray(ArrayAdapter().decode(env["array"], ctx))
        r = Raster(arr, tuple(env["geotransform"]), crs=crs_from_block(env.get("crs")), nodata=env.get("nodata"),
                   bands=env.get("bands"), units=env.get("units"), time=env.get("time"))
        ctx.record("raster", ConversionPath.ADAPTER, ctx.plan.backend, "terra::rast (in memory) -> Raster")
        return r


REGISTRY.register(RasterAdapter(), tested=True,
                  limitations=("Reading raster headers in Python needs rasterio or rioxarray; R uses terra",
                               "In-memory rasters above the memory threshold must be shared as files"))
