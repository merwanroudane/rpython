"""Global, user-facing configuration.

    >>> import rpython as rp
    >>> rp.config(missing="preserve", lossy="error")
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Literal

MissingPolicy = Literal["preserve", "na", "nan"]
LossyPolicy = Literal["error", "warn", "allow"]
TransferPolicy = Literal["auto", "arrow", "json", "file"]


@dataclass
class Config:
    #: preserve = keep NA/NaN/None distinctions where the target can express them.
    missing: MissingPolicy = "preserve"
    #: what to do when a conversion cannot be lossless and no proxy is possible.
    lossy: LossyPolicy = "warn"
    #: transfer backend preference; "auto" lets the planner choose.
    transfer: TransferPolicy = "auto"
    #: rows above which tabular data always goes through Arrow IPC (when available).
    arrow_threshold_rows: int = 5_000
    #: bytes above which a sparse -> dense, lazy -> eager, raster -> array
    #: materialisation requires an explicit override.
    memory_threshold_bytes: int = 512 * 1024**2
    #: never assume a CRS; leave None when unknown.
    assume_crs: str | None = None
    #: explicit R executable (None = autodetect)
    r_home: str | None = None
    #: record explain-mode information for every transfer
    explain: bool = True
    #: extra, namespaced user options
    extra: dict[str, Any] = field(default_factory=dict)


_CONFIG = Config()


def get_config() -> Config:
    return _CONFIG


def config(**kwargs: Any) -> Config:
    """Update global options and return the resulting configuration."""
    global _CONFIG
    known = {k: v for k, v in kwargs.items() if hasattr(Config, k)}
    unknown = {k: v for k, v in kwargs.items() if not hasattr(Config, k)}
    _CONFIG = replace(_CONFIG, **known)
    if unknown:
        _CONFIG.extra.update(unknown)
    return _CONFIG


def reset_config() -> Config:
    global _CONFIG
    _CONFIG = Config()
    return _CONFIG
