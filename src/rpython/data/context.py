"""Conversion context shared by all adapters during one transfer."""
from __future__ import annotations

import os
import tempfile
import uuid
from dataclasses import dataclass, field
from typing import Any

from ..config import Config, get_config
from .semantic import ConversionPath, ConversionRecord, FidelityReport, Runtime


class ConversionError(Exception):
    """Human-readable conversion failure with a suggested fix."""

    def __init__(self, what: str, *, runtime: str = "python", cause: str = "",
                 fix: str = "", fallback_attempted: bool = False, raw: BaseException | None = None):
        self.what, self.runtime, self.cause, self.fix = what, runtime, cause, fix
        self.fallback_attempted, self.raw = fallback_attempted, raw
        super().__init__(self.render())

    def render(self) -> str:
        lines = [self.what, f"Runtime: {self.runtime}"]
        if self.cause:
            lines.append(f"Likely cause: {self.cause}")
        if self.fix:
            lines.append(f"Recommended action:\n  {self.fix}")
        lines.append(f"Fallback attempted: {'yes' if self.fallback_attempted else 'no'}")
        if self.raw is not None:
            lines.append(f"Technical details: {type(self.raw).__name__}: {self.raw}")
        return "\n".join(lines)


class MemoryGuardError(ConversionError):
    """Raised when a materialisation would exceed the configured memory threshold."""


@dataclass
class TransferPlan:
    """Inspectable plan produced by type negotiation (section 50)."""

    source: str = ""
    target: str = ""
    family: str = ""
    logical_type: str = ""
    physical_type: str = ""
    backend: str = "json"            # json | arrow-ipc | file | lazy | proxy
    path: ConversionPath = ConversionPath.NATIVE
    estimated_bytes: int = 0
    copies: int | None = None
    notes: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    lossless_candidates: list[str] = field(default_factory=list)
    detection: str = ""
    fidelity: FidelityReport = field(default_factory=FidelityReport)
    history: list[ConversionRecord] = field(default_factory=list)
    shape: tuple[int, ...] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def note(self, msg: str) -> None:
        self.notes.append(msg)

    def risk(self, msg: str) -> None:
        self.risks.append(msg)

    def render(self) -> str:
        lines = [f"Source: {self.source}", f"Target: {self.target}"]
        if self.shape is not None:
            lines.append("Shape: " + " x ".join(f"{n:,}" for n in self.shape))
        if self.detection:
            lines.append(self.detection)
        lines.append(f"Semantic family: {self.family}")
        lines.append(f"Transfer: {self.backend}  [{self.path.value}]")
        if self.estimated_bytes:
            lines.append(f"Estimated payload: {_fmt_bytes(self.estimated_bytes)}")
        if self.copies is not None:
            lines.append(f"Copies: {self.copies}")
        for k, v in self.extra.items():
            lines.append(f"{k}: {v}")
        if self.history:
            lines.append("Steps:")
            lines.extend(f"  {h.step}: {h.note}" if h.note else f"  {h.step}" for h in self.history[-6:])
        for n in self.notes:
            lines.append(f"Note: {n}")
        for r in self.risks:
            lines.append(f"Risk: {r}")
        if self.fidelity.dimensions:
            lines.append("Fidelity:")
            lines.extend("  " + l for l in self.fidelity.summary().splitlines())
        return "\n".join(lines)


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n} B"


@dataclass
class Context:
    """State for one conversion (encode or decode) pass."""

    direction: str = "py->r"          # "py->r" | "r->py" | "py->py" (round-trip check)
    target_runtime: Runtime = Runtime.R
    config: Config = field(default_factory=get_config)
    workdir: str | None = None
    session: Any = None               # RSession when proxies must be materialised
    plan: TransferPlan = field(default_factory=TransferPlan)
    depth: int = 0
    max_depth: int = 200
    _seen: dict[int, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    allow_materialize: bool = False   # explicit override for memory guard
    #: R-side capability flags received from the worker (e.g. {"arrow": True})
    capabilities: dict[str, bool] = field(default_factory=dict)

    # ------------------------------------------------------------------ files
    def ensure_workdir(self) -> str:
        if self.workdir is None:
            self.workdir = tempfile.mkdtemp(prefix="rpython-")
        return self.workdir

    def new_file(self, suffix: str) -> str:
        return os.path.join(self.ensure_workdir(), f"{uuid.uuid4().hex}{suffix}")

    # ------------------------------------------------------------ recursion
    def enter(self, obj: Any) -> str | None:
        """Cycle detection. Returns a reference token if ``obj`` was already seen."""
        key = id(obj)
        if key in self._seen:
            return self._seen[key]
        if self.depth >= self.max_depth:
            raise ConversionError("Nested structure too deep", cause="depth > max_depth",
                                  fix="flatten the object or convert it as a proxy")
        self._seen[key] = f"ref:{len(self._seen)}"
        self.depth += 1
        return None

    def leave(self, obj: Any) -> None:
        self.depth -= 1

    # -------------------------------------------------------------- policy
    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
        self.plan.risk(msg)

    def lossy(self, what: str, reason: str) -> None:
        """Apply the configured lossy policy."""
        msg = f"Lossy conversion of {what}: {reason}"
        if self.config.lossy == "error":
            raise ConversionError(msg, cause=reason,
                                  fix="rp.config(lossy='allow') or keep the object as a proxy")
        if self.config.lossy == "warn":
            import warnings
            warnings.warn(msg, stacklevel=3)
        self.warn(msg)

    def memory_guard(self, what: str, estimated_bytes: int, alternative: str) -> None:
        self.plan.estimated_bytes = max(self.plan.estimated_bytes, estimated_bytes)
        if estimated_bytes > self.config.memory_threshold_bytes and not self.allow_materialize:
            raise MemoryGuardError(
                f"Refusing to materialise {what}: estimated {_fmt_bytes(estimated_bytes)} exceeds "
                f"the memory threshold ({_fmt_bytes(self.config.memory_threshold_bytes)})",
                cause="materialisation could exhaust memory",
                fix=f"{alternative}; or pass allow_materialize=True / rp.config(memory_threshold_bytes=...)",
            )

    def use_arrow(self, nrows: int) -> bool:
        """Transfer negotiation for tabular payloads."""
        pref = self.config.transfer
        if pref == "json":
            return False
        try:
            import pyarrow  # noqa: F401
        except Exception:
            return False
        if self.target_runtime is Runtime.R and not self.capabilities.get("arrow", True):
            return False
        if pref in ("arrow", "file"):
            return True
        return nrows >= self.config.arrow_threshold_rows

    def record(self, step: str, path: ConversionPath, backend: str, note: str = "") -> None:
        self.plan.history.append(ConversionRecord(step, path, backend, note))
        self.plan.path = path
        self.plan.backend = backend
