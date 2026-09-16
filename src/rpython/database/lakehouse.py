"""Data lakes / lakehouses and spatial SQL (sections 47.8, 47.11).

* Parquet / Arrow datasets: shared files opened lazily by both runtimes
  (``pyarrow.dataset`` <-> ``arrow::open_dataset``), queried through DuckDB.
* Delta Lake (``deltalake``) and Iceberg (``pyiceberg``): the current
  snapshot's file list is shared; R reads the same Parquet files.
* PostGIS / SpatiaLite / DuckDB-spatial: geometry columns come back as
  WKB with the SRID -> GeoDataFrame / sf, never as opaque strings.
"""
from __future__ import annotations

import os
from typing import Any

import pandas as pd

from .base import ConnectionRef, DatabaseAdapter
from .embedded import DuckDBAdapter
from .sql import SQLAlchemyAdapter, SQLiteAdapter


class ParquetLakeAdapter(DatabaseAdapter):
    """A directory / glob of Parquet (or Arrow/CSV) files treated as a lazy dataset."""

    backend = "parquet"
    category = "lakehouse"
    requires = ("pyarrow", "duckdb")
    r_package = "arrow"
    r_supported = True
    tested_live = True

    def connect(self, ref: ConnectionRef) -> Any:
        import duckdb
        con = duckdb.connect(":memory:")
        path = ref.database or "."
        self._register(con, "dataset", path)
        return con

    def _register(self, con: Any, name: str, path: str) -> None:
        p = path.replace("\\", "/")
        if os.path.isdir(p):
            p = p.rstrip("/") + "/**/*.parquet"
        lit = "'" + p.replace("'", "''") + "'"    # DDL cannot take bound params; quote as a SQL literal
        con.execute(f'CREATE OR REPLACE VIEW "{name}" AS SELECT * FROM read_parquet({lit})')

    def files(self, ref: ConnectionRef) -> list[str]:
        import glob
        p = ref.database or "."
        return sorted(glob.glob(os.path.join(p, "**", "*.parquet"), recursive=True)) if os.path.isdir(p) else sorted(glob.glob(p))

    def dataset(self, ref: ConnectionRef) -> Any:
        import pyarrow.dataset as ds
        return ds.dataset(self.files(ref), format="parquet")

    tables = DuckDBAdapter.tables
    schema = DuckDBAdapter.schema
    query_arrow = DuckDBAdapter.query_arrow
    query_pandas = DuckDBAdapter.query_pandas
    count = DuckDBAdapter.count

    def write(self, conn: Any, table: str, df: Any, mode: str = "fail") -> None:
        raise NotImplementedError("write Parquet with rp.save(df, 'path.parquet'); lake views are read-only")


class DeltaAdapter(DatabaseAdapter):
    backend = "delta"
    category = "lakehouse"
    requires = ("deltalake", "duckdb")
    r_package = "arrow"
    r_supported = True

    def connect(self, ref: ConnectionRef) -> Any:
        from deltalake import DeltaTable
        import duckdb
        dt = DeltaTable(ref.database, version=ref.options.get("version"))
        con = duckdb.connect(":memory:")
        con.register("dataset", dt.to_pyarrow_dataset())
        con._rp_delta = dt  # type: ignore[attr-defined]
        return con

    def files(self, conn: Any) -> list[str]:
        return list(conn._rp_delta.file_uris())

    def snapshot(self, conn: Any) -> dict[str, Any]:
        dt = conn._rp_delta
        return {"version": dt.version(), "files": len(dt.files()), "partitions": dt.metadata().partition_columns}

    tables = DuckDBAdapter.tables
    schema = DuckDBAdapter.schema
    query_arrow = DuckDBAdapter.query_arrow
    query_pandas = DuckDBAdapter.query_pandas
    count = DuckDBAdapter.count


class IcebergAdapter(DatabaseAdapter):
    backend = "iceberg"
    category = "lakehouse"
    requires = ("pyiceberg", "duckdb")
    r_package = "arrow"
    r_supported = True

    def connect(self, ref: ConnectionRef) -> Any:
        from pyiceberg.catalog import load_catalog
        import duckdb
        cat = load_catalog(ref.options.get("catalog", "default"), **{k: v for k, v in ref.options.items() if k != "catalog"})
        tbl = cat.load_table(ref.database)
        con = duckdb.connect(":memory:")
        con.register("dataset", tbl.scan().to_arrow())
        con._rp_iceberg = tbl  # type: ignore[attr-defined]
        return con

    tables = DuckDBAdapter.tables
    schema = DuckDBAdapter.schema
    query_arrow = DuckDBAdapter.query_arrow
    query_pandas = DuckDBAdapter.query_pandas
    count = DuckDBAdapter.count


# --------------------------------------------------------------------------- spatial SQL

def _wkb_to_geo(df: pd.DataFrame, geom_cols: list[str], crs: Any) -> Any:
    try:
        from shapely import wkb
    except ImportError:
        return df
    for c in geom_cols:
        df[c] = [wkb.loads(bytes(v)) if v is not None and not isinstance(v, float) else None for v in df[c]]
    try:
        import geopandas as gpd
        return gpd.GeoDataFrame(df, geometry=geom_cols[0], crs=crs)
    except Exception:
        from ..data.spatial import crs_block
        df.attrs["rpython"] = {"spatial": {"geometry_column": geom_cols[0], "geometry_columns": geom_cols, "crs": crs_block(crs)}}
        return df


class PostGISAdapter(SQLAlchemyAdapter):
    backend = "postgis"
    category = "spatial"
    r_package = "RPostgres"

    def __init__(self) -> None:
        super().__init__("postgresql")
        self.backend = "postgis"
        self.tested_live = False

    def geometry_columns(self, conn: Any, table: str) -> list[dict[str, Any]]:
        df = self.query_pandas(conn, "SELECT f_geometry_column, srid, type FROM geometry_columns WHERE f_table_name = :t", {"t": table})
        return df.rename(columns={"f_geometry_column": "column"}).to_dict("records")

    def read_spatial(self, conn: Any, table: str, limit: int | None = None) -> Any:
        gc = self.geometry_columns(conn, table)
        if not gc:
            return self.query_pandas(conn, f"SELECT * FROM {self.quote(table)}", limit=limit)
        cols = ", ".join(f"ST_AsBinary({self.quote(g['column'])}) AS {self.quote(g['column'])}" for g in gc)
        sql = f"SELECT *, {cols} FROM {self.quote(table)}"
        df = self.query_pandas(conn, sql, limit=limit)
        df = df.loc[:, ~df.columns.duplicated(keep="last")]
        return _wkb_to_geo(df, [g["column"] for g in gc], f"EPSG:{gc[0]['srid']}" if gc[0].get("srid") else None)


class SpatiaLiteAdapter(SQLiteAdapter):
    backend = "spatialite"
    category = "spatial"
    tested_live = False   # needs the mod_spatialite extension

    def connect(self, ref: ConnectionRef) -> Any:
        ref.options["spatialite"] = True
        return super().connect(ref)

    def read_spatial(self, conn: Any, table: str, geometry: str = "geometry", limit: int | None = None) -> Any:
        srid = conn.execute("SELECT srid FROM geometry_columns WHERE f_table_name = ?", [table]).fetchone()
        df = self.query_pandas(conn, f"SELECT *, AsBinary({self.quote(geometry)}) AS __wkb FROM {self.quote(table)}", limit=limit)
        df[geometry] = df.pop("__wkb")
        return _wkb_to_geo(df, [geometry], f"EPSG:{srid[0]}" if srid else None)


class DuckDBSpatialAdapter(DuckDBAdapter):
    backend = "duckdb-spatial"
    category = "spatial"
    tested_live = False

    def connect(self, ref: ConnectionRef) -> Any:
        ref.options["spatial"] = True
        return super().connect(ref)

    def read_spatial(self, conn: Any, table: str, geometry: str = "geom", crs: Any = None, limit: int | None = None) -> Any:
        df = self.query_pandas(conn, f"SELECT *, ST_AsWKB({self.quote(geometry)}) AS __wkb FROM {self.quote(table)}", limit=limit)
        df[geometry] = df.pop("__wkb")
        return _wkb_to_geo(df, [geometry], crs)
