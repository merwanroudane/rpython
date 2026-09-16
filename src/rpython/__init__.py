"""RPython -- R and Python, one seamless research workspace.

    >>> import rpython as rp
    >>> r = rp.R()
    >>> r("1 + 1")
    2.0
    >>> r["df"] = pandas_frame            # semantic conversion, Arrow when large
    >>> fit = r("lm(y ~ x, data = df)")   # rich R object stays in R (proxy)
    >>> fit.coef()
    >>> rp.explain_last()
"""
from __future__ import annotations

from .config import config, get_config, reset_config
from .data.context import Context, ConversionError, MemoryGuardError, TransferPlan
from .data.convert import to_envelope, from_envelope, roundtrip
from .data.registry import REGISTRY, register_converter, register_semantic_adapter, register_proxy_adapter
from .data.semantic import Fidelity, FidelityReport, SemanticObject, SemanticRole, Confidence, ConversionPath
from .data.temporal import timeseries, TimeSeries
from .data.panel import panel, cross_section, repeated_cross_section, hierarchical, Panel
from .data.survey import labelled, LabelledFrame
from .data.survival import survival, SurvivalData
from .data.spatial import spatial
from .data.raster import raster, Raster, RasterRef
from .data.spatiotemporal import spatiotemporal, SpatioTemporal
from .data.network import network, Network, triples_to_network
from .data.text import dtm, corpus, DocumentTermMatrix, Corpus
from .data.media import image, audio, video, Image, Audio, MediaRef
from .data.scientific import netcdf, NetCDFRef
from .data.economics import (io_table, trade_matrix, spatial_weights, dyadic, mixed_frequency, vintages, experiment,
                             simulation, EconomicMatrix, SpatialWeights, Dyadic, MixedFrequency, Vintages, Experiment, Simulation)
from .data.sparse import to_dense
from .data.custom import introspect
from .explain import explain_last, explain, explain_plan
from .fidelity import validate_roundtrip, fidelity_report
from .results.result import Result, RError, Plot
from .proxy.r_object import RObjectProxy
from .runtime.r_session import RSession, default_session
from .persistence.io import save, load
from .database.api import connect, relation, Relation, ConnectionRef
from .diagnostics.doctor import doctor, check, self_test, fix, restore

__version__ = "0.1.1"
__author__ = "Merwan Roudane"


def R(**kwargs):  # noqa: N802 - public constructor name from the specification
    """Start (or reuse) an R session: ``r = rp.R()``."""
    if kwargs:
        return RSession(**kwargs)
    return default_session()


def setup(**kwargs):
    """One-call setup for notebooks / Colab: detect R, start the session, load magics."""
    r = R(**kwargs)
    try:
        from .notebook.magics import load_ipython_extension
        from IPython import get_ipython  # type: ignore
        ip = get_ipython()
        if ip is not None:
            load_ipython_extension(ip)
    except Exception:
        pass
    return r


def to_r(obj, session=None, name=None):
    """Send a Python object to R.  Returns the R-side name (assigned) so R code can use it."""
    s = session or default_session()
    name = name or f".rp_obj_{abs(hash(id(obj))) % 10_000_000}"
    s.assign(name, obj)
    return name


def to_python(obj, session=None):
    """Bring an R object (proxy or variable name) into Python."""
    s = session or default_session()
    if isinstance(obj, RObjectProxy):
        return obj.to_python()
    if isinstance(obj, str):
        return s.get(obj)
    return obj


def lazy(obj):
    """Mark a lazy object (polars LazyFrame, Dask, Arrow dataset) to be kept lazy: never materialised for transfer."""
    from .data.lazy import Lazy
    return Lazy(obj)


def load_ipython_extension(ipython):
    """``%load_ext rpython``"""
    from .notebook.magics import load_ipython_extension as _load
    _load(ipython)


__all__ = [n for n in dir() if not n.startswith("_")]
