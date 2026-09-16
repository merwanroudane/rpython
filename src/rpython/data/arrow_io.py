"""Arrow IPC helpers: the standard language-neutral transfer path (sections 9, 51, 52).

Files are written as Arrow IPC *file* format (a.k.a. Feather v2) into the
per-session work directory; the R companion reads them with
``arrow::read_ipc_file`` / ``arrow::read_feather``.
"""
from __future__ import annotations

import json
from typing import Any

import numpy as np

from .context import Context


def available() -> bool:
    try:
        import pyarrow  # noqa: F401
        return True
    except Exception:
        return False


def write_flat_arrow(flat: np.ndarray, ctx: Context, mask: list[bool] | None = None) -> str:
    import pyarrow as pa
    import pyarrow.feather as feather
    path = ctx.new_file(".arrow")
    arr = pa.array(flat, mask=np.asarray(mask, dtype=bool) if mask is not None else None)
    tbl = pa.table({"values": arr})
    feather.write_feather(tbl, path, compression="uncompressed")
    return path


def read_flat_arrow(path: str) -> np.ndarray:
    import pyarrow.feather as feather
    tbl = feather.read_table(path)
    col = tbl.column("values")
    if col.null_count:
        return col.to_pandas(types_mapper=None).to_numpy(dtype=float, na_value=np.nan)
    return col.to_numpy()


def write_table_arrow(table: Any, ctx: Context, metadata: dict[str, Any] | None = None) -> str:
    """Write a pyarrow.Table (or anything with __arrow_c_stream__) to IPC."""
    import pyarrow as pa
    import pyarrow.feather as feather
    if not isinstance(table, pa.Table):
        table = pa.table(table)
    if metadata:
        md = dict(table.schema.metadata or {})
        md[b"rpython"] = json.dumps(metadata, default=str).encode("utf-8")
        table = table.replace_schema_metadata(md)
    path = ctx.new_file(".arrow")
    feather.write_feather(table, path, compression="uncompressed")
    return path


def read_table_arrow(path: str) -> Any:
    import pyarrow.feather as feather
    return feather.read_table(path)


def table_nbytes(table: Any) -> int:
    try:
        return int(table.nbytes)
    except Exception:
        return 0
