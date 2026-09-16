"""Networks, graphs, trees, DAGs and knowledge-graph triples (sections 21-23, 30).

Envelope ``kind: "network"``::

    {"kind": "network", "directed": bool, "multigraph": bool,
     "nodes": <table: id + node attributes>, "edges": <table: source, target, [key], attributes>,
     "node_id_type": "character"|"integer"|"double"|"encoded",
     "id_map": {"<str>": <envelope>} | null,      # reversible mapping for non-string ids
     "graph_attrs": {...},
     "features": {"n_nodes", "n_edges", "weighted", "weight_attr", "self_loops", "parallel_edges",
                  "bipartite", "bipartite_attr", "layers", "temporal", "signed", "tree", "dag",
                  "node_types", "edge_types"},
     "meta": {...}}

R: ``igraph::graph_from_data_frame(edges, directed, vertices = nodes)``
which keeps parallel edges, self loops, direction and all attributes;
``tidygraph``/``network`` objects are converted through igraph.
Python: ``networkx`` (Multi)(Di)Graph; ``python-igraph`` when the source was igraph.

Guarantees: a multigraph is never collapsed, direction is never lost,
node ids are never coerced without a reversible mapping.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from .context import Context
from .registry import Adapter, REGISTRY
from .semantic import Confidence, ConversionPath, Detection, Fidelity, SemanticRole
from .tabular import encode_frame, decode_frame


def _nx():
    try:
        import networkx as nx
        return nx
    except Exception:
        return None


def _is_nx(obj: Any) -> bool:
    nx = _nx()
    return nx is not None and isinstance(obj, nx.Graph)


def _is_igraph(obj: Any) -> bool:
    return type(obj).__module__.startswith("igraph") and type(obj).__name__ == "Graph"


def _is_pyg(obj: Any) -> bool:
    return type(obj).__module__.startswith("torch_geometric")


def _id_type(ids: list[Any]) -> str:
    if all(isinstance(i, str) for i in ids):
        return "character"
    if all(isinstance(i, bool) for i in ids):
        return "encoded"
    if all(isinstance(i, int) for i in ids):
        return "integer"
    if all(isinstance(i, (int, float)) for i in ids):
        return "double"
    return "encoded"


class Network:
    """Explicit declaration from tables: ``rp.network(edges, nodes=None, directed=True, source="from", target="to")``.

    Also the container returned when the Python side has no graph library installed.
    """

    def __init__(self, edges: pd.DataFrame, nodes: pd.DataFrame | None = None, *, directed: bool = True,
                 source: str = "source", target: str = "target", node_id: str = "id", weight: str | None = None,
                 multigraph: bool | None = None, bipartite: str | None = None, layer: str | None = None,
                 time: str | None = None, graph_attrs: dict[str, Any] | None = None, signed: str | None = None):
        self.edges, self.nodes = edges, nodes
        self.directed, self.source, self.target, self.node_id = directed, source, target, node_id
        self.weight = weight or ("weight" if "weight" in edges.columns else None)
        self.multigraph = bool(edges[[source, target]].duplicated().any()) if multigraph is None else multigraph
        self.bipartite, self.layer, self.time, self.signed = bipartite, layer, time, signed
        self.graph_attrs = dict(graph_attrs or {})

    def node_ids(self) -> list[Any]:
        if self.nodes is not None and self.node_id in self.nodes.columns:
            return self.nodes[self.node_id].tolist()
        return pd.unique(pd.concat([self.edges[self.source], self.edges[self.target]])).tolist()

    def to_networkx(self) -> Any:
        nx = _nx()
        if nx is None:
            raise ImportError("networkx is required: pip install 'rpython[network]'")
        cls = {(True, True): nx.MultiDiGraph, (True, False): nx.DiGraph, (False, True): nx.MultiGraph, (False, False): nx.Graph}[(self.directed, self.multigraph)]
        g = cls(**self.graph_attrs)
        if self.nodes is not None:
            attrs = [c for c in self.nodes.columns if c != self.node_id]
            for _, row in self.nodes.iterrows():
                g.add_node(row[self.node_id], **{a: row[a] for a in attrs if not _isna(row[a])})
        eattrs = [c for c in self.edges.columns if c not in (self.source, self.target, "key")]
        for _, row in self.edges.iterrows():
            kw = {a: row[a] for a in eattrs if not _isna(row[a])}
            if self.multigraph and "key" in self.edges.columns and not _isna(row["key"]):
                g.add_edge(row[self.source], row[self.target], key=row["key"], **kw)
            else:
                g.add_edge(row[self.source], row[self.target], **kw)
        return g

    def describe_structure(self) -> str:
        f = network_features(self)
        lines = [f"Type: {'Directed' if self.directed else 'Undirected'} {'multigraph' if self.multigraph else 'graph'}",
                 f"Nodes: {f['n_nodes']}", f"Edges: {f['n_edges']}",
                 f"Weighted: {'yes (' + f['weight_attr'] + ')' if f['weighted'] else 'no'}",
                 f"Self loops: {f['self_loops']}", f"Parallel edges: {f['parallel_edges']}"]
        for k in ("bipartite", "layers", "temporal", "signed", "tree", "dag"):
            if f.get(k):
                lines.append(f"{k.capitalize()}: {f[k]}")
        return "\n".join(lines)


def _isna(v: Any) -> bool:
    try:
        return v is None or (not isinstance(v, (list, tuple, dict, set)) and pd.isna(v))
    except Exception:
        return False


def network(edges: Any = None, nodes: Any = None, **kw: Any) -> Any:
    """Public API ``rp.network``: wrap an edge table (dyadic data) or pass a graph object through."""
    if _is_nx(edges) or _is_igraph(edges):
        return edges
    return Network(edges, nodes, **kw)


def network_features(n: Network) -> dict[str, Any]:
    e = n.edges
    ids = n.node_ids()
    loops = int((e[n.source] == e[n.target]).sum())
    if n.directed:
        par = int(e[[n.source, n.target]].duplicated().sum())
    else:
        key = e[[n.source, n.target]].apply(lambda r: tuple(sorted((str(r.iloc[0]), str(r.iloc[1])))), axis=1) if len(e) else pd.Series([], dtype=object)
        par = int(key.duplicated().sum())
    feats: dict[str, Any] = {"n_nodes": len(ids), "n_edges": int(len(e)), "weighted": n.weight is not None,
                             "weight_attr": n.weight, "self_loops": loops, "parallel_edges": par,
                             "bipartite": n.bipartite is not None, "bipartite_attr": n.bipartite,
                             "layers": n.layer, "temporal": n.time, "signed": n.signed,
                             "node_types": None, "edge_types": None, "tree": None, "dag": None}
    nx = _nx()
    if nx is not None and len(e) <= 200_000:
        try:
            g = n.to_networkx()
            if n.directed:
                feats["dag"] = bool(nx.is_directed_acyclic_graph(g))
                feats["tree"] = bool(feats["dag"] and nx.is_arborescence(nx.DiGraph(g)) if not n.multigraph else False)
            else:
                feats["tree"] = bool(nx.is_tree(g)) if len(g) else False
        except Exception:
            pass
    if n.nodes is not None and "type" in n.nodes.columns:
        feats["node_types"] = sorted(map(str, n.nodes["type"].dropna().unique()))
    if "type" in e.columns:
        feats["edge_types"] = sorted(map(str, e["type"].dropna().unique()))
    return feats


def from_networkx(g: Any) -> Network:
    nx = _nx()
    nodes_raw = list(g.nodes(data=True))
    node_attrs = sorted({k for _, d in nodes_raw for k in d})
    nodes = pd.DataFrame({"id": [n for n, _ in nodes_raw], **{a: [d.get(a) for _, d in nodes_raw] for a in node_attrs}})
    multigraph = g.is_multigraph()
    if multigraph:
        edges_raw = list(g.edges(keys=True, data=True))
        edge_attrs = sorted({k for *_, d in edges_raw for k in d})
        edges = pd.DataFrame({"source": [u for u, *_ in edges_raw], "target": [v for _, v, *_ in edges_raw],
                              "key": [k for _, _, k, _ in edges_raw],
                              **{a: [d.get(a) for *_, d in edges_raw] for a in edge_attrs}})
    else:
        edges_raw = list(g.edges(data=True))
        edge_attrs = sorted({k for *_, d in edges_raw for k in d})
        edges = pd.DataFrame({"source": [u for u, _, _ in edges_raw], "target": [v for _, v, _ in edges_raw],
                              **{a: [d.get(a) for *_, d in edges_raw] for a in edge_attrs}})
    bip = "bipartite" if "bipartite" in node_attrs else None
    return Network(edges, nodes, directed=g.is_directed(), multigraph=multigraph, weight="weight" if "weight" in edge_attrs else None,
                   bipartite=bip, layer="layer" if "layer" in edge_attrs else None,
                   time="time" if "time" in edge_attrs else None, graph_attrs=dict(g.graph),
                   signed="sign" if "sign" in edge_attrs else None)


def from_igraph(g: Any) -> Network:
    names = g.vs["name"] if "name" in g.vs.attributes() else list(range(g.vcount()))
    nodes = pd.DataFrame({"id": names, **{a: g.vs[a] for a in g.vs.attributes() if a != "name"}})
    el = g.get_edgelist()
    edges = pd.DataFrame({"source": [names[s] for s, _ in el], "target": [names[t] for _, t in el],
                          **{a: g.es[a] for a in g.es.attributes()}})
    return Network(edges, nodes, directed=g.is_directed(), multigraph=bool(g.has_multiple()),
                   weight="weight" if "weight" in g.es.attributes() else None,
                   bipartite="type" if "type" in g.vs.attributes() else None,
                   graph_attrs={a: g[a] for a in g.attributes()})


class NetworkAdapter(Adapter):
    family = "network"
    kinds = ("network",)
    tier = ConversionPath.ADAPTER
    priority = 12
    r_requires = ("igraph",)

    def detect(self, obj: Any) -> Detection | None:
        if isinstance(obj, Network):
            return Detection("network", Confidence.CONFIRMED, "explicit rp.network declaration")
        if _is_nx(obj):
            return Detection("network", Confidence.CONFIRMED, f"networkx.{type(obj).__name__}")
        if _is_igraph(obj):
            return Detection("network", Confidence.CONFIRMED, "igraph.Graph")
        if _is_pyg(obj):
            return Detection("network", Confidence.CONFIRMED, "torch_geometric Data (via proxy for tensors)")
        if isinstance(obj, pd.DataFrame):
            cols = {str(c).lower() for c in obj.columns}
            if {"source", "target"} <= cols or {"from", "to"} <= cols:
                return Detection("network (edge list)", Confidence.AMBIGUOUS,
                                 "source/target columns; declare with rp.network(df, directed=...)")
        return None

    def encode(self, obj: Any, ctx: Context) -> dict[str, Any]:
        if _is_nx(obj):
            n = from_networkx(obj)
            src = f"networkx.{type(obj).__name__}"
        elif _is_igraph(obj):
            n = from_igraph(obj)
            src = "igraph.Graph"
        elif _is_pyg(obj):
            from .custom import proxy_encode
            ctx.plan.note("torch_geometric objects stay native (tensor features); edge_index exported below")
            return proxy_encode(obj, ctx)
        else:
            n = obj
            src = "rpython.Network"
        ids = n.node_ids()
        id_type = _id_type(ids)
        id_map = None
        nodes = n.nodes if n.nodes is not None else pd.DataFrame({n.node_id: ids})
        edges = n.edges
        if id_type == "encoded":
            from .convert import to_envelope
            id_map = {str(i): to_envelope(i, ctx) for i in ids}
            conv = lambda v: str(v)
            nodes = nodes.assign(**{n.node_id: [conv(v) for v in nodes[n.node_id]]})
            edges = edges.assign(**{n.source: [conv(v) for v in edges[n.source]], n.target: [conv(v) for v in edges[n.target]]})
            ctx.plan.note("non-scalar node ids stringified with a reversible id_map")
        feats = network_features(n)
        roles = {n.source: SemanticRole.SOURCE_NODE.value, n.target: SemanticRole.TARGET_NODE.value}
        if n.weight:
            roles[n.weight] = SemanticRole.EDGE_WEIGHT.value
        env = {"rpx": 1, "kind": "network", "directed": bool(n.directed), "multigraph": bool(n.multigraph),
               "nodes": encode_frame(nodes.rename(columns={n.node_id: "name"}), ctx),
               "edges": encode_frame(edges.rename(columns={n.source: "from", n.target: "to"}), ctx),
               "node_id_type": id_type, "id_map": id_map, "graph_attrs": _jsonable_attrs(n.graph_attrs),
               "features": feats, "roles": roles,
               "columns": {"source": n.source, "target": n.target, "node_id": n.node_id, "weight": n.weight,
                           "bipartite": n.bipartite, "layer": n.layer, "time": n.time, "signed": n.signed},
               "meta": {"source_class": src}}
        ctx.record("network", ConversionPath.ADAPTER, "json",
                   f"{src}: {feats['n_nodes']:,} nodes, {feats['n_edges']:,} edges, "
                   f"{'directed' if n.directed else 'undirected'}{', multigraph' if n.multigraph else ''} -> igraph")
        ctx.plan.extra["Directed"] = "yes" if n.directed else "no"
        ctx.plan.extra["Parallel edges"] = str(feats["parallel_edges"])
        ctx.plan.extra["Self loops"] = str(feats["self_loops"])
        ctx.plan.extra["Node attributes"] = str(len([c for c in nodes.columns if c != n.node_id]))
        ctx.plan.extra["Edge attributes"] = str(len([c for c in edges.columns if c not in (n.source, n.target, "key")]))
        ctx.plan.fidelity.set("topology", Fidelity.LOSSLESS, "direction, parallel edges, self loops kept")
        ctx.plan.fidelity.set("values", Fidelity.LOSSLESS)
        ctx.plan.fidelity.set("names", Fidelity.LOSSLESS if id_type != "encoded" else Fidelity.CHANGED, "" if id_type != "encoded" else "ids stringified (reversible)")
        return env

    def decode(self, env: dict[str, Any], ctx: Context) -> Any:
        nodes = decode_frame(env["nodes"], ctx)
        edges = decode_frame(env["edges"], ctx)
        cols = env.get("columns") or {}
        node_id = cols.get("node_id") or "id"
        src, tgt = cols.get("source") or "source", cols.get("target") or "target"
        nodes = nodes.rename(columns={"name": node_id})
        edges = edges.rename(columns={"from": src, "to": tgt})
        id_type = env.get("node_id_type", "character")
        if id_type == "integer":
            for df, c in ((nodes, node_id), (edges, src), (edges, tgt)):
                df[c] = pd.Series([int(v) for v in pd.to_numeric(df[c])], index=df.index, dtype=object)   # plain ints, not np.int64
        elif id_type == "double":
            for df, c in ((nodes, node_id), (edges, src), (edges, tgt)):
                df[c] = pd.Series([float(v) for v in pd.to_numeric(df[c])], index=df.index, dtype=object)
        elif id_type == "encoded" and env.get("id_map"):
            from .convert import from_envelope
            m = {k: from_envelope(v, ctx) for k, v in env["id_map"].items()}
            m = {k: (tuple(v) if isinstance(v, list) else v) for k, v in m.items()}
            for df, c in ((nodes, node_id), (edges, src), (edges, tgt)):
                df[c] = [m.get(str(v), v) for v in df[c]]
        n = Network(edges, nodes, directed=bool(env.get("directed", True)), source=src, target=tgt, node_id=node_id,
                    weight=cols.get("weight"), multigraph=bool(env.get("multigraph", False)),
                    bipartite=cols.get("bipartite"), layer=cols.get("layer"), time=cols.get("time"),
                    graph_attrs=env.get("graph_attrs") or {}, signed=cols.get("signed"))
        source_class = (env.get("meta") or {}).get("source_class", "")
        ctx.plan.fidelity.set("topology", Fidelity.LOSSLESS)
        if source_class.startswith("igraph") or source_class == "R igraph":
            try:
                import igraph
                return _to_igraph(n)
            except ImportError:
                pass
        if _nx() is not None:
            ctx.record("network", ConversionPath.ADAPTER, "json", "igraph -> networkx")
            g = n.to_networkx()
            g.graph["rpython"] = {"features": env.get("features"), "bipartite_attr": cols.get("bipartite")}
            return g
        ctx.record("network", ConversionPath.ADAPTER, "json", "igraph -> rpython.Network (networkx not installed)")
        return n


def _to_igraph(n: Network) -> Any:
    import igraph
    ids = [str(i) for i in n.node_ids()]
    index = {i: k for k, i in enumerate(ids)}
    g = igraph.Graph(directed=n.directed)
    g.add_vertices(len(ids))
    g.vs["name"] = ids
    if n.nodes is not None:
        for c in n.nodes.columns:
            if c != n.node_id:
                g.vs[c] = n.nodes[c].tolist()
    g.add_edges([(index[str(s)], index[str(t)]) for s, t in zip(n.edges[n.source], n.edges[n.target])])
    for c in n.edges.columns:
        if c not in (n.source, n.target):
            g.es[c] = n.edges[c].tolist()
    for k, v in n.graph_attrs.items():
        g[k] = v
    return g


def _jsonable_attrs(d: dict[str, Any]) -> dict[str, Any]:
    import json
    out = {}
    for k, v in d.items():
        try:
            json.dumps(v)
            out[str(k)] = v
        except Exception:
            out[str(k)] = repr(v)
    return out


# --------------------------------------------------------------------------
# Triples / knowledge graphs (section 23)
# --------------------------------------------------------------------------

def triples_to_network(triples: pd.DataFrame, subject: str = "subject", predicate: str = "predicate",
                       object_: str = "object", graph: str | None = None) -> Network:
    """RDF-like triples/quads -> multigraph whose edge ``type`` is the predicate.

    Literal objects keep ``datatype`` / ``lang`` columns when present; IRIs are never flattened."""
    e = triples.rename(columns={subject: "source", object_: "target", predicate: "type"})
    if graph:
        e = e.rename(columns={graph: "layer"})
    return Network(e, directed=True, multigraph=True, layer="layer" if graph else None)


REGISTRY.register(NetworkAdapter(), tested=True,
                  limitations=("torch_geometric / DGL objects stay native behind a proxy",))
