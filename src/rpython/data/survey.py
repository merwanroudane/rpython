"""Survey and labelled data (section 15): variable labels, value labels,
user-defined / tagged missing values and sampling-design metadata.

Envelope: ``table`` + ``semantics.labels``::

    {"variables": {"inc": "Household income"},
     "values": {"sex": {"1": "male", "2": "female"}},
     "missing": {"inc": [-9, -8]}, "missing_ranges": {"inc": [[-99, -90]]},
     "tagged": {"inc": {"a": "refused"}},
     "design": {"weight": "w", "strata": "s", "psu": "cluster", "fpc": null,
                "replicate_weights": [], "method": null},
     "source_format": "stata"|"spss"|"sas"|null}

R side: ``haven::labelled`` / ``haven::labelled_spss`` columns and the
design block as the ``rpython.survey`` attribute (ready for
``survey::svydesign``).  Labelled numeric codes are **never** turned into
plain numbers without their labels travelling next to them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from .context import Context
from .registry import Adapter, REGISTRY
from .semantic import Confidence, ConversionPath, Detection, Fidelity, SemanticRole
from .tabular import encode_frame, decode_frame


@dataclass
class LabelledFrame:
    """``rp.labelled(df, variable_labels=..., value_labels=..., weight=...)``."""

    data: pd.DataFrame
    variable_labels: dict[str, str] = field(default_factory=dict)
    value_labels: dict[str, dict[Any, str]] = field(default_factory=dict)
    missing_values: dict[str, list[Any]] = field(default_factory=dict)
    missing_ranges: dict[str, list[list[float]]] = field(default_factory=dict)
    tagged_missing: dict[str, dict[str, str]] = field(default_factory=dict)
    weight: str | None = None
    strata: str | None = None
    psu: str | None = None
    fpc: str | None = None
    replicate_weights: list[str] = field(default_factory=list)
    method: str | None = None
    source_format: str | None = None

    def describe_structure(self) -> str:
        lines = ["Type: Labelled / Survey Data",
                 f"Observations: {len(self.data)}",
                 f"Variables: {self.data.shape[1]}",
                 f"Variable labels: {len(self.variable_labels)}",
                 f"Value-labelled variables: {len(self.value_labels)}",
                 f"User-defined missing: {len(self.missing_values) + len(self.missing_ranges)} variable(s)"]
        for k in ("weight", "strata", "psu", "fpc", "method", "source_format"):
            if getattr(self, k):
                lines.append(f"{k.upper() if k == 'psu' else k.capitalize()}: {getattr(self, k)}")
        if self.replicate_weights:
            lines.append(f"Replicate weights: {len(self.replicate_weights)}")
        return "\n".join(lines)

    def labels_block(self) -> dict[str, Any]:
        return {
            "variables": dict(self.variable_labels),
            "values": {c: {str(k): v for k, v in m.items()} for c, m in self.value_labels.items()},
            "value_code_type": {c: ("character" if all(isinstance(k, str) for k in m) else "double")
                                for c, m in self.value_labels.items()},
            "missing": {c: list(v) for c, v in self.missing_values.items()},
            "missing_ranges": {c: [list(r) for r in v] for c, v in self.missing_ranges.items()},
            "tagged": dict(self.tagged_missing),
            "design": {"weight": self.weight, "strata": self.strata, "psu": self.psu, "fpc": self.fpc,
                       "replicate_weights": list(self.replicate_weights), "method": self.method},
            "source_format": self.source_format,
        }

    @classmethod
    def from_block(cls, df: pd.DataFrame, block: dict[str, Any]) -> "LabelledFrame":
        d = block.get("design") or {}
        code_types = block.get("value_code_type") or {}
        values: dict[str, dict[Any, str]] = {}
        for c, m in (block.get("values") or {}).items():
            conv = (lambda k: k) if code_types.get(c) == "character" else _num
            values[c] = {conv(k): v for k, v in m.items()}
        return cls(df, variable_labels=dict(block.get("variables") or {}), value_labels=values,
                   missing_values={c: list(v) for c, v in (block.get("missing") or {}).items()},
                   missing_ranges={c: [list(r) for r in v] for c, v in (block.get("missing_ranges") or {}).items()},
                   tagged_missing=dict(block.get("tagged") or {}),
                   weight=d.get("weight"), strata=d.get("strata"), psu=d.get("psu"), fpc=d.get("fpc"),
                   replicate_weights=list(d.get("replicate_weights") or []), method=d.get("method"),
                   source_format=block.get("source_format"))

    @classmethod
    def from_pyreadstat(cls, df: pd.DataFrame, meta: Any) -> "LabelledFrame":
        """Build from ``pyreadstat.read_dta/read_sav/read_sas7bdat`` output."""
        var_labels = dict(zip(meta.column_names, meta.column_labels)) if getattr(meta, "column_labels", None) else {}
        var_labels = {k: v for k, v in var_labels.items() if v}
        value_labels = dict(getattr(meta, "variable_value_labels", {}) or {})
        missing = {k: list(v) for k, v in (getattr(meta, "missing_user_values", {}) or {}).items()}
        ranges = {k: [[r["lo"], r["hi"]] for r in v] for k, v in (getattr(meta, "missing_ranges", {}) or {}).items()} if getattr(meta, "missing_ranges", None) else {}
        fmt = (getattr(meta, "file_format", None) or "").lower() or None
        return cls(df, variable_labels=var_labels, value_labels=value_labels, missing_values=missing,
                   missing_ranges=ranges, source_format=fmt)


def _num(k: str) -> Any:
    try:
        f = float(k)
        return int(f) if f.is_integer() else f
    except Exception:
        return k


def labelled(data: pd.DataFrame, **kw: Any) -> LabelledFrame:
    return LabelledFrame(data, **kw)


class SurveyAdapter(Adapter):
    family = "survey"
    kinds = ("labelled",)
    tier = ConversionPath.ADAPTER
    priority = 7

    def detect(self, obj: Any) -> Detection | None:
        if isinstance(obj, LabelledFrame):
            return Detection("labelled / survey data", Confidence.CONFIRMED, "explicit declaration")
        if isinstance(obj, pd.DataFrame) and isinstance((obj.attrs or {}).get("rpython"), dict) \
                and obj.attrs["rpython"].get("labels"):
            return Detection("labelled / survey data", Confidence.CONFIRMED, "labels metadata in df.attrs")
        return None

    def encode(self, obj: Any, ctx: Context) -> dict[str, Any]:
        lf = obj if isinstance(obj, LabelledFrame) else LabelledFrame.from_block(obj, obj.attrs["rpython"]["labels"])
        block = lf.labels_block()
        roles = {k: v for k, v in {lf.weight: SemanticRole.WEIGHT.value, lf.strata: SemanticRole.STRATA.value,
                                   lf.psu: SemanticRole.CLUSTER.value}.items() if k}
        env = encode_frame(lf.data, ctx, semantics={"labels": block, "roles": roles})
        env["kind"] = "labelled"
        ctx.record("labelled", ConversionPath.ADAPTER, ctx.plan.backend,
                   f"{len(block['variables'])} variable labels, {len(block['values'])} value-label sets -> haven::labelled")
        ctx.plan.fidelity.set("metadata", Fidelity.LOSSLESS, "labels, missing codes and design in sidecar")
        ctx.plan.fidelity.set("semantics", Fidelity.LOSSLESS)
        return env

    def decode(self, env: dict[str, Any], ctx: Context) -> Any:
        block = (env.get("semantics") or {}).get("labels") or {}
        df = decode_frame(env, ctx)
        lf = LabelledFrame.from_block(df, block)
        df.attrs["rpython"] = {**df.attrs.get("rpython", {}), "labels": block}
        ctx.record("labelled", ConversionPath.ADAPTER, ctx.plan.backend, "haven::labelled -> LabelledFrame")
        ctx.plan.fidelity.set("metadata", Fidelity.LOSSLESS)
        return lf


REGISTRY.register(SurveyAdapter(), tested=True)
