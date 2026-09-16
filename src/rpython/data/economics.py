"""Economic / econometric special structures (sections 29-32, 40, 43).

Everything here is a *semantic wrapper* over the universal families
(matrix, sparse, table, network) so the economics domain lives inside the
general system rather than beside it.

* :class:`EconomicMatrix` -- input-output tables, Leontief / SAM,
  bilateral trade, transition, covariance/correlation, adjacency
  matrices.  Row and column entities are named and orientation is
  explicit; rows and columns are never reordered independently.
* :class:`SpatialWeights` -- spatial econometric weights (contiguity,
  distance, kNN), with region ids, standardisation and zero-neighbour
  handling; sparse by default.  R: ``spdep::mat2listw`` when available.
* :class:`Dyadic` -- pairwise / origin-destination data with explicit
  direction semantics; converts safely to/from :class:`Network`.
* :class:`MixedFrequency` -- several series at different frequencies
  (MIDAS-style), each kept with its own frequency.
* :class:`Vintages` -- real-time / vintage datasets keyed by release date.
* :class:`Experiment` -- treatment/control/event-time roles for causal
  datasets (staggered DiD, RCTs).
* :class:`Simulation` -- Monte-Carlo draws with scenario / replication
  ids; RNG equivalence is explicitly **not** claimed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .context import Context
from .registry import Adapter, REGISTRY
from .semantic import Confidence, ConversionPath, Detection, Fidelity, SemanticRole
from .tabular import encode_frame, decode_frame


@dataclass
class EconomicMatrix:
    """``rp.io_table(Z, sectors=[...])`` / ``rp.trade_matrix(M, countries=[...])``."""

    values: Any                                   # ndarray or scipy sparse
    rows: list[str]
    cols: list[str]
    kind: str = "input_output"                    # input_output | sam | trade | transition | covariance | correlation | adjacency | leontief
    orientation: str = "rows=from, cols=to"       # semantic orientation, e.g. "rows=supplying sector, cols=using sector"
    units: str | None = None
    year: int | str | None = None
    row_entity: str = "sector"
    col_entity: str = "sector"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_frame(self) -> pd.DataFrame:
        v = self.values.toarray() if hasattr(self.values, "toarray") else np.asarray(self.values)
        return pd.DataFrame(v, index=pd.Index(self.rows, name=self.row_entity), columns=pd.Index(self.cols, name=self.col_entity))

    def describe_structure(self) -> str:
        return "\n".join([f"Type: Economic matrix ({self.kind})", f"Rows: {len(self.rows)} {self.row_entity}(s)",
                          f"Columns: {len(self.cols)} {self.col_entity}(s)", f"Orientation: {self.orientation}",
                          f"Units: {self.units or 'unspecified'}", f"Year: {self.year or 'unspecified'}",
                          f"Sparse: {'yes' if hasattr(self.values, 'nnz') else 'no'}"])


@dataclass
class SpatialWeights:
    """``rp.spatial_weights(W, ids=[...], style="W", kind="queen")``."""

    matrix: Any                    # scipy sparse or ndarray, n x n
    ids: list[str]
    style: str = "B"               # B (binary) | W (row-standardised) | C | U | S | minmax
    kind: str = "contiguity"       # contiguity | queen | rook | distance | knn | kernel | custom
    k: int | None = None
    bandwidth: float | None = None
    directed: bool = False
    zero_policy: bool = True       # allow islands (regions with no neighbours)

    def islands(self) -> list[str]:
        m = self.matrix
        rowsum = np.asarray(m.sum(axis=1)).ravel()
        return [i for i, s in zip(self.ids, rowsum) if s == 0]

    def describe_structure(self) -> str:
        nnz = self.matrix.nnz if hasattr(self.matrix, "nnz") else int(np.count_nonzero(self.matrix))
        n = len(self.ids)
        return "\n".join(["Type: Spatial weights matrix", f"Regions: {n}", f"Kind: {self.kind}" + (f" (k={self.k})" if self.k else ""),
                          f"Style: {self.style}", f"Non-zero links: {nnz:,} (avg {nnz / max(n, 1):.2f} neighbours)",
                          f"Islands: {len(self.islands())}", f"Directed: {'yes' if self.directed else 'no'}",
                          f"Sparse: {'yes' if hasattr(self.matrix, 'nnz') else 'no'}"])


@dataclass
class Dyadic:
    """``rp.dyadic(df, source="exporter", target="importer", time="year", value="trade")``."""

    data: pd.DataFrame
    source: str
    target: str
    time: str | None = None
    value: str | None = None
    directed: bool = True
    relation: str | None = None

    def to_network(self) -> Any:
        from .network import Network
        return Network(self.data, directed=self.directed, source=self.source, target=self.target,
                       weight=self.value, time=self.time, multigraph=self.time is not None)

    def describe_structure(self) -> str:
        pairs = self.data[[self.source, self.target]].drop_duplicates()
        return "\n".join([f"Type: Dyadic data ({'directed' if self.directed else 'undirected'})",
                          f"Source: {self.source} ({self.data[self.source].nunique()})",
                          f"Target: {self.target} ({self.data[self.target].nunique()})",
                          f"Dyads: {len(pairs):,}", f"Observations: {len(self.data):,}",
                          f"Time: {self.time or 'none'}", f"Value: {self.value or 'none'}",
                          f"Relation: {self.relation or 'unspecified'}"])


@dataclass
class MixedFrequency:
    """``rp.mixed_frequency({"gdp": quarterly, "cpi": monthly, "spread": daily})``."""

    series: dict[str, Any]         # name -> pandas Series/DataFrame with DatetimeIndex/PeriodIndex
    target: str | None = None      # low-frequency target series

    def describe_structure(self) -> str:
        from .temporal import TimeSeries, timeseries_semantics
        lines = ["Type: Mixed-frequency dataset"]
        for k, v in self.series.items():
            sem = timeseries_semantics(TimeSeries(v))
            lines.append(f"  {k}: {sem['frequency'] or 'irregular'} ({sem['n_periods']} periods)" + ("  [target]" if k == self.target else ""))
        return "\n".join(lines)


@dataclass
class Vintages:
    """Real-time dataset: ``rp.vintages(df, vintage="release_date", time="period")``."""

    data: pd.DataFrame
    vintage: str
    time: str
    value: str | None = None

    def describe_structure(self) -> str:
        return "\n".join(["Type: Real-time / vintage dataset", f"Vintages: {self.data[self.vintage].nunique()}",
                          f"Periods: {self.data[self.time].nunique()}", f"Observations: {len(self.data):,}"])


@dataclass
class Experiment:
    """Causal / experimental roles: ``rp.experiment(df, treatment="d", outcome="y", time="t", unit="i", event_time="rel")``."""

    data: pd.DataFrame
    treatment: str
    outcome: str
    unit: str | None = None
    time: str | None = None
    event_time: str | None = None
    cohort: str | None = None
    cluster: str | None = None
    strata: str | None = None
    weight: str | None = None
    propensity: str | None = None
    design: str | None = None     # rct | did | staggered_did | event_study | rdd | iv | matching

    def roles(self) -> dict[str, str]:
        r = {self.treatment: SemanticRole.TREATMENT.value, self.outcome: SemanticRole.OUTCOME.value}
        for attr, role in (("unit", SemanticRole.ENTITY), ("time", SemanticRole.TIME), ("cohort", SemanticRole.COHORT),
                           ("cluster", SemanticRole.CLUSTER), ("strata", SemanticRole.STRATA), ("weight", SemanticRole.WEIGHT)):
            if getattr(self, attr):
                r[getattr(self, attr)] = role.value
        if self.event_time:
            r[self.event_time] = "event_time"
        if self.propensity:
            r[self.propensity] = "propensity"
        return r

    def describe_structure(self) -> str:
        d = self.data
        lines = [f"Type: Experimental / causal data ({self.design or 'design unspecified'})",
                 f"Treatment: {self.treatment} (treated share {d[self.treatment].astype(float).mean():.1%})",
                 f"Outcome: {self.outcome}"]
        for k in ("unit", "time", "event_time", "cohort", "cluster", "strata", "weight", "propensity"):
            if getattr(self, k):
                lines.append(f"{k.replace('_', ' ').capitalize()}: {getattr(self, k)}")
        return "\n".join(lines)


@dataclass
class Simulation:
    """Monte-Carlo results: ``rp.simulation(df, replication="rep", scenario="scn", seed=123, rng="numpy PCG64")``."""

    data: pd.DataFrame
    replication: str
    scenario: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    seed: int | None = None
    rng: str | None = None

    def describe_structure(self) -> str:
        return "\n".join(["Type: Simulation / Monte-Carlo results", f"Replications: {self.data[self.replication].nunique()}",
                          f"Scenarios: {self.data[self.scenario].nunique() if self.scenario else 1}",
                          f"Seed: {self.seed} ({self.rng or 'RNG unspecified'})",
                          "Note: data are transferred; RNG streams are NOT equivalent across R and Python."])


# ------------------------------------------------------------------ constructors

def io_table(values: Any, sectors: list[str], cols: list[str] | None = None, **kw: Any) -> EconomicMatrix:
    return EconomicMatrix(values, list(sectors), list(cols or sectors), kind=kw.pop("kind", "input_output"),
                          orientation=kw.pop("orientation", "rows=supplying sector, cols=using sector"), **kw)


def trade_matrix(values: Any, countries: list[str], **kw: Any) -> EconomicMatrix:
    return EconomicMatrix(values, list(countries), list(countries), kind="trade", orientation="rows=exporter, cols=importer",
                          row_entity="exporter", col_entity="importer", **kw)


def spatial_weights(matrix: Any, ids: list[str], **kw: Any) -> SpatialWeights:
    return SpatialWeights(matrix, [str(i) for i in ids], **kw)


def dyadic(data: pd.DataFrame, source: str, target: str, **kw: Any) -> Dyadic:
    return Dyadic(data, source, target, **kw)


def mixed_frequency(series: dict[str, Any], target: str | None = None) -> MixedFrequency:
    return MixedFrequency(dict(series), target)


def vintages(data: pd.DataFrame, vintage: str, time: str, value: str | None = None) -> Vintages:
    return Vintages(data, vintage, time, value)


def experiment(data: pd.DataFrame, treatment: str, outcome: str, **kw: Any) -> Experiment:
    return Experiment(data, treatment, outcome, **kw)


def simulation(data: pd.DataFrame, replication: str, **kw: Any) -> Simulation:
    return Simulation(data, replication, **kw)


# ------------------------------------------------------------------ adapter

class EconomicsAdapter(Adapter):
    family = "economics"
    kinds = ("economic_matrix", "spatial_weights", "dyadic", "mixed_frequency", "vintages", "experiment", "simulation")
    tier = ConversionPath.ADAPTER
    priority = 16

    def detect(self, obj: Any) -> Detection | None:
        for cls, name in ((EconomicMatrix, "economic matrix"), (SpatialWeights, "spatial weights"), (Dyadic, "dyadic data"),
                          (MixedFrequency, "mixed-frequency data"), (Vintages, "vintage data"), (Experiment, "experimental data"),
                          (Simulation, "simulation data")):
            if isinstance(obj, cls):
                return Detection(name, Confidence.CONFIRMED, "explicit declaration")
        return None

    def encode(self, obj: Any, ctx: Context) -> dict[str, Any]:
        from .convert import to_envelope
        if isinstance(obj, EconomicMatrix):
            m_env = to_envelope(obj.values, ctx)
            m_env["dimnames"] = [list(obj.rows), list(obj.cols)]
            env = {"rpx": 1, "kind": "economic_matrix", "matrix": m_env, "rows": list(obj.rows), "cols": list(obj.cols),
                   "matrix_kind": obj.kind, "orientation": obj.orientation, "units": obj.units, "year": obj.year,
                   "row_entity": obj.row_entity, "col_entity": obj.col_entity, "metadata": obj.metadata,
                   "meta": {"source_class": "rpython.EconomicMatrix"}}
            ctx.record("economics", ConversionPath.ADAPTER, ctx.plan.backend,
                       f"{obj.kind} matrix {len(obj.rows)}x{len(obj.cols)} with named entities -> R matrix + attributes")
            ctx.plan.fidelity.set("names", Fidelity.LOSSLESS, "row/column entities and orientation kept")
            ctx.plan.fidelity.set("values", Fidelity.LOSSLESS)
            return env
        if isinstance(obj, SpatialWeights):
            m_env = to_envelope(obj.matrix, ctx)
            m_env["dimnames"] = [list(obj.ids), list(obj.ids)]
            env = {"rpx": 1, "kind": "spatial_weights", "matrix": m_env, "ids": list(obj.ids), "style": obj.style,
                   "weights_kind": obj.kind, "k": obj.k, "bandwidth": obj.bandwidth, "directed": obj.directed,
                   "zero_policy": obj.zero_policy, "islands": obj.islands(), "meta": {"source_class": "rpython.SpatialWeights"}}
            ctx.record("economics", ConversionPath.ADAPTER, ctx.plan.backend,
                       f"spatial weights ({obj.kind}, style {obj.style}, {len(obj.ids)} regions, {len(env['islands'])} islands) -> spdep listw / Matrix")
            ctx.plan.fidelity.set("values", Fidelity.LOSSLESS)
            ctx.plan.fidelity.set("semantics", Fidelity.LOSSLESS, "style, islands and region ids kept")
            return env
        if isinstance(obj, Dyadic):
            roles = {obj.source: SemanticRole.SOURCE_NODE.value, obj.target: SemanticRole.TARGET_NODE.value}
            if obj.time:
                roles[obj.time] = SemanticRole.TIME.value
            if obj.value:
                roles[obj.value] = SemanticRole.EDGE_WEIGHT.value
            sem = {"source": obj.source, "target": obj.target, "time": obj.time, "value": obj.value,
                   "directed": obj.directed, "relation": obj.relation}
            env = encode_frame(obj.data, ctx, semantics={"dyadic": sem, "roles": roles})
            env["kind"] = "dyadic"
            ctx.record("economics", ConversionPath.ADAPTER, ctx.plan.backend, f"dyadic {obj.source}->{obj.target} table -> data.frame + rpython.dyadic")
            return env
        if isinstance(obj, MixedFrequency):
            from .temporal import TimeSeries
            env = {"rpx": 1, "kind": "mixed_frequency", "series": {k: to_envelope(TimeSeries(v), ctx) for k, v in obj.series.items()},
                   "target": obj.target, "meta": {"source_class": "rpython.MixedFrequency"}}
            ctx.record("economics", ConversionPath.ADAPTER, ctx.plan.backend, f"{len(obj.series)} series at their own frequencies -> named list of ts/xts")
            ctx.plan.fidelity.set("temporal", Fidelity.LOSSLESS, "each frequency preserved separately")
            return env
        if isinstance(obj, Vintages):
            env = encode_frame(obj.data, ctx, semantics={"vintages": {"vintage": obj.vintage, "time": obj.time, "value": obj.value},
                                                          "roles": {obj.vintage: "vintage", obj.time: SemanticRole.TIME.value}})
            env["kind"] = "vintages"
            ctx.record("economics", ConversionPath.ADAPTER, ctx.plan.backend, "vintage dataset -> data.frame + rpython.vintages")
            return env
        if isinstance(obj, Experiment):
            sem = {k: getattr(obj, k) for k in ("treatment", "outcome", "unit", "time", "event_time", "cohort", "cluster",
                                                  "strata", "weight", "propensity", "design")}
            env = encode_frame(obj.data, ctx, semantics={"experiment": sem, "roles": obj.roles()})
            env["kind"] = "experiment"
            ctx.record("economics", ConversionPath.ADAPTER, ctx.plan.backend, f"{obj.design or 'causal'} dataset with declared roles -> data.frame + rpython.experiment")
            ctx.plan.fidelity.set("semantics", Fidelity.LOSSLESS, "roles declared explicitly, none inferred")
            return env
        s: Simulation = obj
        env = encode_frame(s.data, ctx, semantics={"simulation": {"replication": s.replication, "scenario": s.scenario,
                                                                   "parameters": s.parameters, "seed": s.seed, "rng": s.rng,
                                                                   "rng_equivalence": False}})
        env["kind"] = "simulation"
        ctx.record("economics", ConversionPath.ADAPTER, ctx.plan.backend, "simulation results -> data.frame + rpython.simulation")
        ctx.plan.note("RNG streams differ between R and Python: data interoperability != RNG equivalence")
        return env

    def decode(self, env: dict[str, Any], ctx: Context) -> Any:
        from .convert import from_envelope
        k = env["kind"]
        if k == "economic_matrix":
            m = from_envelope({**env["matrix"], "dimnames": None}, ctx)
            return EconomicMatrix(m, env["rows"], env["cols"], kind=env.get("matrix_kind", "input_output"),
                                  orientation=env.get("orientation", ""), units=env.get("units"), year=env.get("year"),
                                  row_entity=env.get("row_entity", "sector"), col_entity=env.get("col_entity", "sector"),
                                  metadata=env.get("metadata") or {})
        if k == "spatial_weights":
            m = from_envelope({**env["matrix"], "dimnames": None}, ctx)
            return SpatialWeights(m, env["ids"], style=env.get("style", "B"), kind=env.get("weights_kind", "custom"),
                                  k=env.get("k"), bandwidth=env.get("bandwidth"), directed=bool(env.get("directed")),
                                  zero_policy=bool(env.get("zero_policy", True)))
        if k == "mixed_frequency":
            return MixedFrequency({n: from_envelope(e, ctx) for n, e in env["series"].items()}, env.get("target"))
        df = decode_frame(env, ctx)
        sem = env.get("semantics") or {}
        if k == "dyadic":
            d = sem.get("dyadic") or {}
            return Dyadic(df, d.get("source", "source"), d.get("target", "target"), time=d.get("time"), value=d.get("value"),
                          directed=bool(d.get("directed", True)), relation=d.get("relation"))
        if k == "vintages":
            v = sem.get("vintages") or {}
            return Vintages(df, v.get("vintage", "vintage"), v.get("time", "time"), v.get("value"))
        if k == "experiment":
            e = sem.get("experiment") or {}
            return Experiment(df, e.get("treatment", "treatment"), e.get("outcome", "outcome"),
                              **{x: e.get(x) for x in ("unit", "time", "event_time", "cohort", "cluster", "strata", "weight", "propensity", "design")})
        s = sem.get("simulation") or {}
        return Simulation(df, s.get("replication", "replication"), scenario=s.get("scenario"),
                          parameters=s.get("parameters") or {}, seed=s.get("seed"), rng=s.get("rng"))


REGISTRY.register(EconomicsAdapter(), tested=True)
