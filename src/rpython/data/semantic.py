"""Universal semantic data model.

Every object crossing the R <-> Python boundary is described by a
:class:`SemanticObject`.  The object is intentionally light: it is a
container of *meaning* (identity, logical family, schema, axes, roles,
missingness, storage, fidelity, fallback) that wraps a *portable
envelope* -- a plain JSON-serialisable ``dict`` understood by both the
Python package and the R companion package.

Users never construct this by hand; the conversion layer builds it
lazily and Explain Mode renders it.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable

RPX_VERSION = 1


class Runtime(str, Enum):
    PYTHON = "python"
    R = "r"


class Confidence(str, Enum):
    """How sure the detector is about a semantic classification."""

    CONFIRMED = "confirmed"          # from object metadata / explicit user declaration
    INFERRED = "strongly inferred"   # strong structural evidence
    AMBIGUOUS = "ambiguous"          # suggestion only; never acted on silently
    UNKNOWN = "unknown"


class Fidelity(str, Enum):
    """Status of one fidelity dimension after a conversion."""

    LOSSLESS = "lossless"
    REBUILT = "rebuilt"        # e.g. spatial index rebuilt on target
    CHANGED = "changed"        # e.g. storage backend changed, values intact
    LOSSY = "lossy"            # information dropped, reported
    PROXY = "proxy-preserved"  # kept alive in source runtime
    NA = "not applicable"

    @property
    def symbol(self) -> str:
        return {
            Fidelity.LOSSLESS: "✓",
            Fidelity.REBUILT: "ℹ",
            Fidelity.CHANGED: "ℹ",
            Fidelity.LOSSY: "⚠",
            Fidelity.PROXY: "↻",
            Fidelity.NA: "-",
        }[self]


class ConversionPath(str, Enum):
    """Section 2 / 57 of the specification: the conversion priority hierarchy."""

    NATIVE = "A. lossless native conversion"
    STANDARD = "B. lossless standard interchange representation"
    ADAPTER = "C. metadata-preserving adapter"
    LAZY = "D. lazy/shared representation"
    PROXY = "E. native object proxy"
    LOSSY = "F. explicitly documented lossy conversion"


# Fidelity dimensions the report can distinguish (section 59).
FIDELITY_DIMENSIONS: tuple[str, ...] = (
    "values", "types", "shape", "names", "index", "metadata", "semantics",
    "storage", "laziness", "topology", "crs", "temporal",
)


class SemanticRole(str, Enum):
    """Optional column roles (section 53)."""

    ID = "id"
    ENTITY = "entity"
    TIME = "time"
    TREATMENT = "treatment"
    OUTCOME = "outcome"
    WEIGHT = "weight"
    CLUSTER = "cluster"
    STRATA = "strata"
    LATITUDE = "latitude"
    LONGITUDE = "longitude"
    GEOMETRY = "geometry"
    SOURCE_NODE = "source"
    TARGET_NODE = "target"
    EDGE_WEIGHT = "edge_weight"
    EVENT = "event"
    DURATION = "duration"
    TEXT = "text"
    LABEL = "label"
    FEATURE = "feature"
    GROUP = "group"
    COHORT = "cohort"
    WAVE = "wave"


@dataclass
class Identity:
    source_runtime: Runtime
    source_class: str
    source_package: str | None = None
    object_id: str | None = None   # proxy handle when object stays in source runtime

    def to_dict(self) -> dict[str, Any]:
        return {
            "runtime": self.source_runtime.value,
            "class": self.source_class,
            "package": self.source_package,
            "object_id": self.object_id,
        }


@dataclass
class Detection:
    family: str
    confidence: Confidence
    evidence: str = ""

    def describe(self) -> str:
        if self.confidence is Confidence.CONFIRMED:
            return f"Detected: {self.family} — confirmed ({self.evidence})."
        if self.confidence is Confidence.INFERRED:
            return f"Detected: {self.family} — strongly inferred ({self.evidence})."
        if self.confidence is Confidence.AMBIGUOUS:
            return f"Possible {self.family}: {self.evidence} — suggestion only."
        return f"Unknown structure ({self.evidence})."


@dataclass
class FidelityDimension:
    name: str
    status: Fidelity
    note: str = ""


@dataclass
class FidelityReport:
    dimensions: list[FidelityDimension] = field(default_factory=list)
    validated: bool = False   # only True when a real round-trip check ran

    def set(self, name: str, status: Fidelity, note: str = "") -> "FidelityReport":
        for d in self.dimensions:
            if d.name == name:
                d.status, d.note = status, note
                return self
        self.dimensions.append(FidelityDimension(name, status, note))
        return self

    def get(self, name: str) -> FidelityDimension | None:
        return next((d for d in self.dimensions if d.name == name), None)

    @property
    def lossless(self) -> bool:
        return all(d.status in (Fidelity.LOSSLESS, Fidelity.NA) for d in self.dimensions)

    @property
    def lossy(self) -> bool:
        return any(d.status is Fidelity.LOSSY for d in self.dimensions)

    def summary(self) -> str:
        width = max((len(d.name) for d in self.dimensions), default=8) + 2
        lines = []
        for d in self.dimensions:
            label = (d.name.capitalize() + ":").ljust(width)
            note = f"  ({d.note})" if d.note else ""
            lines.append(f"{label} {d.status.value} {d.status.symbol}{note}")
        lines.append("Overall:".ljust(width) + " " + ("lossless ✓" if self.lossless else
                     "lossy ⚠" if self.lossy else "preserved with changes ℹ"))
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "validated": self.validated,
            "dimensions": [{"name": d.name, "status": d.status.value, "note": d.note}
                           for d in self.dimensions],
        }


@dataclass
class ConversionRecord:
    step: str
    path: ConversionPath
    backend: str
    note: str = ""
    at: str = field(default_factory=lambda: _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"))

    def to_dict(self) -> dict[str, Any]:
        return {"step": self.step, "path": self.path.value, "backend": self.backend,
                "note": self.note, "at": self.at}


@dataclass
class SemanticObject:
    """Internal description of an object crossing the boundary (section 3)."""

    identity: Identity
    logical_type: str                       # family name: "table", "network", ...
    physical_type: str = ""                 # e.g. "pandas.DataFrame", "dgCMatrix"
    schema: dict[str, Any] | None = None
    shape: tuple[int, ...] | None = None
    axes: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    roles: dict[str, str] = field(default_factory=dict)
    missingness: dict[str, Any] = field(default_factory=dict)
    encoding: str = "utf-8"
    storage: str = "memory"                 # memory | arrow-ipc | file | database | lazy | proxy
    domain: dict[str, Any] = field(default_factory=dict)
    detection: Detection | None = None
    history: list[ConversionRecord] = field(default_factory=list)
    fidelity: FidelityReport = field(default_factory=FidelityReport)
    fallback: ConversionPath | None = None
    envelope: dict[str, Any] | None = None  # the portable payload

    def record(self, step: str, path: ConversionPath, backend: str, note: str = "") -> None:
        self.history.append(ConversionRecord(step, path, backend, note))

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity.to_dict(),
            "logical_type": self.logical_type,
            "physical_type": self.physical_type,
            "schema": self.schema,
            "shape": list(self.shape) if self.shape is not None else None,
            "axes": self.axes,
            "metadata": self.metadata,
            "roles": self.roles,
            "missingness": self.missingness,
            "encoding": self.encoding,
            "storage": self.storage,
            "domain": self.domain,
            "detection": None if self.detection is None else {
                "family": self.detection.family,
                "confidence": self.detection.confidence.value,
                "evidence": self.detection.evidence,
            },
            "history": [h.to_dict() for h in self.history],
            "fidelity": self.fidelity.to_dict(),
            "fallback": None if self.fallback is None else self.fallback.value,
        }


def sanitize_metadata(meta: dict[str, Any], forbidden: Iterable[str] = ()) -> dict[str, Any]:
    """Strip credential-like keys (section 65) before anything is serialised."""
    bad = {"password", "passwd", "pwd", "secret", "token", "api_key", "apikey",
           "access_key", "private_key", "credential", "credentials", *forbidden}
    out: dict[str, Any] = {}
    for k, v in meta.items():
        if any(b in str(k).lower() for b in bad):
            out[k] = "<redacted>"
        elif isinstance(v, dict):
            out[k] = sanitize_metadata(v, forbidden)
        else:
            out[k] = v
    return out
