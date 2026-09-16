"""Python -> envelope -> Python round trips for every object family, with
family-specific equality (section 58: no single == rule)."""
import numpy as np
import pandas as pd
import pytest

import rpython as rp
from rpython.data.convert import roundtrip
from rpython.fidelity import compare
from tests.conftest import has, needs


def frame():
    return pd.DataFrame({
        "x": [1.5, np.nan, 3.0], "s": ["a", "b", None], "i": pd.array([1, None, 3], dtype="Int64"),
        "c": pd.Categorical(["lo", "hi", "lo"], categories=["lo", "hi"], ordered=True),
        "t": pd.to_datetime(["2024-01-01", "2024-06-01", "2024-12-31"]).tz_localize("Europe/Paris"),
        "d": pd.to_datetime(["2024-01-01", "2024-06-01", None]), "b": [True, False, True], "big": [2**40, 1, 2],
        "f32": np.array([1, 2, 3], dtype="float32"), "lst": [[1, 2], [3], []], "ville é": [1, 2, 3], "مدينة": ["a", "b", "c"],
        "st": pd.array(["a", None, "c"], dtype="string"), "dur": pd.to_timedelta([1, 2, 3], unit="h"),
        "per": pd.period_range("2020Q1", periods=3, freq="Q"), "date": [pd.Timestamp("2024-01-01").date()] * 3,
    })


@pytest.mark.parametrize("transfer", ["json", "arrow"])
def test_dataframe_all_dtypes(transfer):
    rp.config(transfer=transfer)
    try:
        df = frame()
        back, ctx = roundtrip(df)
        rep = compare(df, back)
        assert rep.lossless, rep.summary()
        assert back.equals(df)
        assert ctx.plan.backend == ("arrow-ipc" if transfer == "arrow" else "json")
    finally:
        rp.reset_config()


def test_index_variants():
    df = pd.DataFrame({"v": [1, 2, 3]}, index=pd.Index(["a", "b", "c"], name="id"))
    assert roundtrip(df)[0].equals(df)
    mi = pd.DataFrame({"v": [1, 2, 3, 4]}, index=pd.MultiIndex.from_product([["x", "y"], [1, 2]], names=["g", "t"]))
    assert roundtrip(mi)[0].equals(mi)
    dti = pd.DataFrame({"v": [1, 2]}, index=pd.date_range("2020", periods=2, freq="D"))
    back = roundtrip(dti)[0]
    assert back.equals(dti) and back.index.freq == dti.index.freq


def test_edge_frames():
    assert roundtrip(pd.DataFrame())[0].shape == (0, 0)
    assert roundtrip(pd.DataFrame({"a": []}))[0].shape == (0, 1)
    one = pd.DataFrame({"a": [1]})
    assert roundtrip(one)[0].equals(one)
    dup = pd.DataFrame([[1, 2]], columns=["a", "a"])
    assert roundtrip(dup)[0].columns.tolist() == ["a", "a"]
    wide = pd.DataFrame(np.zeros((2, 500)))
    assert roundtrip(wide)[0].shape == (2, 500)
    long_names = pd.DataFrame({"x" * 300: [1]})
    assert roundtrip(long_names)[0].columns[0] == "x" * 300
    spaces = pd.DataFrame({"a b-c.d": [1], "e (f)": [2]})
    assert roundtrip(spaces)[0].columns.tolist() == ["a b-c.d", "e (f)"]


def test_series_variants():
    s = pd.Series([1.0, None], index=["a", "b"], name="v")
    back, _ = roundtrip(s)
    assert back.equals(s) and back.name == "v"
    cat = pd.Series(pd.Categorical(["x", "y"], ordered=True))
    assert roundtrip(cat)[0].cat.ordered


@needs("polars")
def test_polars_frame():
    import polars as pl
    df = pl.DataFrame({"a": [1, 2], "b": ["x", None], "c": [1.5, None]})
    back, _ = roundtrip(df)
    assert isinstance(back, pl.DataFrame) and back.shape == df.shape and back["a"].to_list() == [1, 2]


@needs("pyarrow")
def test_arrow_table_and_dataset(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    import pyarrow.dataset as ds
    t = pa.table({"a": [1, 2], "b": ["x", "y"]})
    assert isinstance(roundtrip(t)[0], pa.Table)
    pq.write_table(t, str(tmp_path / "p.parquet"))
    d = ds.dataset(str(tmp_path), format="parquet")
    back, ctx = roundtrip(d)
    assert ctx.plan.copies == 0 and back.to_table().num_rows == 2


def test_timeseries_regular_irregular_tz():
    ts = pd.Series(np.arange(24.), index=pd.date_range("2020-01-01", periods=24, freq="MS"), name="y")
    back, ctx = roundtrip(ts)
    assert back.equals(ts) and back.index.freq == ts.index.freq
    assert ctx.plan.history[-1].note.startswith("R ts")
    irr = pd.DataFrame({"v": [1, 2, 3]}, index=pd.DatetimeIndex(["2020-01-01", "2020-01-05", "2020-02-01"], tz="UTC"))
    back, ctx = roundtrip(irr)
    assert back.equals(irr)
    gaps = pd.Series([1, 2, 3], index=pd.DatetimeIndex(["2020-01-01", "2020-02-01", "2020-04-01"]))
    sem = rp.timeseries(gaps, freq="MS").describe_structure()
    assert "Missing periods: 1" in sem
    dup = pd.Series([1, 2], index=pd.DatetimeIndex(["2020-01-01", "2020-01-01"]))
    assert "Duplicate timestamps: 1" in rp.timeseries(dup).describe_structure()


def test_panel_balanced_unbalanced_duplicates():
    pdf = pd.DataFrame({"country": np.repeat(["FR", "DE", "IT"], 4), "year": list(range(2000, 2004)) * 3, "gdp": np.arange(12.)})
    p = rp.panel(pdf, id="country", time="year")
    st = p.structure()
    assert st["balanced"] and st["n_entities"] == 3 and st["n_periods"] == 4 and st["gaps"] == 0
    back, ctx = roundtrip(p)
    assert isinstance(back.index, pd.MultiIndex) and back.index.names == ["country", "year"]
    assert back.attrs["rpython"]["panel"]["balanced"] is True
    unb = rp.panel(pdf.drop(index=5), id="country", time="year")
    assert not unb.structure()["balanced"] and unb.structure()["gaps"] == 1
    dup = rp.panel(pd.concat([pdf, pdf.iloc[[0]]]), id="country", time="year")
    assert dup.structure()["duplicates"] == 1 and dup.structure()["r_class"] == "data.frame"
    with pytest.raises(ValueError):
        rp.panel(pdf)   # never guessed silently


def test_repeated_cross_section_and_hierarchical():
    df = pd.DataFrame({"wave": [1, 1, 2, 2], "id": [1, 2, 3, 4], "y": [1., 2., 3., 4.], "w": [1., 1., 2., 2.]})
    rcs = rp.repeated_cross_section(df, wave="wave", weight="w")
    back, _ = roundtrip(rcs)
    assert back.attrs["rpython"]["panel"]["kind"] == "repeated_cross_section" and not isinstance(back.index, pd.MultiIndex)
    h = rp.hierarchical(pd.DataFrame({"school": [1, 1, 2], "class": [1, 2, 3], "score": [1., 2., 3.]}), levels=["school", "class"])
    assert roundtrip(h)[0].attrs["rpython"]["panel"]["levels"] == ["school", "class"]


def test_labelled_survey():
    lf = rp.labelled(pd.DataFrame({"sex": [1, 2, 1, -9], "inc": [10., 20., None, 30.]}),
                     variable_labels={"inc": "Income", "sex": "Sex"}, value_labels={"sex": {1: "male", 2: "female", -9: "refused"}},
                     missing_values={"sex": [-9]}, weight="inc", strata="sex")
    back, ctx = roundtrip(lf)
    assert back.value_labels == lf.value_labels and back.variable_labels == lf.variable_labels
    assert back.missing_values == {"sex": [-9]} and back.weight == "inc" and back.strata == "sex"


def test_survival():
    sv = rp.survival(pd.DataFrame({"t": [1., 2., 3.], "d": [1, 0, 1], "age": [50, 60, 70]}), time="t", event="d")
    back, _ = roundtrip(sv)
    assert back.type == "right" and back.data["d"].tolist() == [1., 0., 1.] and back.data["age"].tolist() == [50, 60, 70]
    cr = rp.survival(pd.DataFrame({"t": [1., 2.], "e": ["censored", "death"]}), time="t", event="e", type="mstate", event_levels=["censored", "death", "relapse"])
    back, _ = roundtrip(cr)
    assert back.event_levels == ["censored", "death", "relapse"]


@needs("shapely")
def test_spatial_geometry_crs():
    import shapely
    gdf = rp.spatial(pd.DataFrame({"n": ["a", "b"], "x": [1., 2.], "y": [3., 4.]}), lon="x", lat="y", crs="EPSG:4326")
    back, ctx = roundtrip(gdf)
    blk = back.attrs["rpython"]["spatial"] if not hasattr(back, "crs") else None
    if blk is not None:
        assert blk["crs"]["epsg"] == 4326
    else:
        assert back.crs.to_epsg() == 4326
    assert back["geometry"][0].equals(shapely.Point(1, 3))
    assert ctx.plan.fidelity.get("crs").status.value == "lossless"
    poly = shapely.Polygon([(0, 0), (1, 0), (1, 1)])
    assert roundtrip(poly)[0].equals(poly)
    nocrs = rp.spatial(pd.DataFrame({"x": [1.], "y": [2.]}), lon="x", lat="y")
    back, ctx = roundtrip(nocrs)
    assert any("no CRS" in w for w in ctx.warnings)   # never assumed


@needs("shapely")
def test_spatiotemporal_keeps_both():
    import shapely
    base = rp.spatial(pd.DataFrame({"id": ["a", "a"], "t": pd.to_datetime(["2020-01-01", "2020-01-02"]), "x": [1., 2.], "y": [1., 1.]}), lon="x", lat="y", crs="EPSG:4326")
    st = rp.spatiotemporal(base, time="t", id="id", kind="trajectory")
    back, ctx = roundtrip(st)
    assert back.kind == "trajectory" and back.data["geometry"][1].equals(shapely.Point(2, 1))
    assert ctx.plan.fidelity.get("crs").status.value == "lossless" and ctx.plan.fidelity.get("temporal").status.value == "lossless"


def test_raster_in_memory_and_ref(tmp_path):
    r = rp.Raster(np.arange(12.).reshape(3, 4), (0, 1, 0, 3, 0, -1), crs="EPSG:3857", nodata=-9999)
    back, _ = roundtrip(r)
    assert np.array_equal(back.array, r.array) and back.nodata == -9999 and back.extent == r.extent
    p = tmp_path / "x.tif"
    p.write_bytes(b"not really a tiff")
    ref = rp.raster(str(p))
    back, ctx = roundtrip(ref)
    assert isinstance(back, rp.RasterRef) and ctx.plan.copies == 0


@needs("networkx")
def test_network_topology():
    import networkx as nx
    g = nx.MultiDiGraph()
    g.add_edge("a", "b", weight=1.0, key=0)
    g.add_edge("a", "b", weight=2.0, key=1)
    g.add_edge("b", "b", weight=3.0)
    g.nodes["a"]["type"] = "x"
    g.graph["name"] = "test"
    back, ctx = roundtrip(g)
    rep = compare(g, back)
    assert rep.lossless, rep.summary()
    assert back.number_of_edges() == 3 and back.is_directed() and back.is_multigraph()
    assert roundtrip(nx.path_graph(5))[0].nodes == nx.path_graph(5).nodes
    g3 = nx.Graph()
    g3.add_edge((1, 2), (3, 4))
    assert set(roundtrip(g3)[0].nodes) == {(1, 2), (3, 4)}
    bip = nx.Graph()
    bip.add_nodes_from([1, 2], bipartite=0)
    bip.add_nodes_from(["a"], bipartite=1)
    bip.add_edges_from([(1, "a"), (2, "a")])
    assert roundtrip(bip)[0].nodes[1]["bipartite"] == 0
    tri = rp.triples_to_network(pd.DataFrame({"subject": ["s1"], "predicate": ["p"], "object": ["o1"]}))
    assert tri.multigraph and tri.directed


@needs("scipy")
def test_sparse_formats():
    import scipy.sparse as sp
    for fmt in ("csc", "csr", "coo", "dia", "lil"):
        m = sp.random(30, 20, density=0.2, format=fmt, random_state=0)
        back, ctx = roundtrip(m)
        assert (back.tocsr() != m.tocsr()).nnz == 0
        assert back.format == ("csc" if fmt in ("dia", "lil") else fmt)
    from rpython.data.context import MemoryGuardError
    with pytest.raises(MemoryGuardError):
        rp.to_dense(sp.csr_matrix((100_000, 100_000)))


@needs("scipy")
def test_text_dtm_and_corpus():
    import scipy.sparse as sp
    m = sp.csr_matrix(np.array([[1, 0, 2], [0, 3, 0]]))
    d = rp.dtm(m, docs=["d1", "d2"], terms=["a", "b", "c"], weighting="tfidf")
    back, _ = roundtrip(d)
    assert (back.matrix.toarray() == m.toarray()).all() and back.terms == ["a", "b", "c"] and back.weighting == "tfidf"
    c = rp.corpus(pd.DataFrame({"id": ["1"], "text": ["bonjour"], "lang": ["fr"]}), text="text", doc_id="id", language="fr")
    back, _ = roundtrip(c)
    assert back.language == "fr" and back.data["text"][0] == "bonjour"


def test_media():
    im = rp.Image(np.zeros((4, 5, 3), dtype=np.uint8), channel_order="BGR")
    back, _ = roundtrip(im)
    assert back.channel_order == "BGR" and back.array.dtype == np.uint8 and back.array.shape == (4, 5, 3)
    au = rp.audio(np.zeros(100), sample_rate=8000)
    assert roundtrip(au)[0].sample_rate == 8000
    with pytest.raises(ValueError):
        rp.audio(np.zeros(10))
    v = rp.video("no_such_file.mp4")
    back, ctx = roundtrip(v)
    assert isinstance(back, rp.MediaRef) and ctx.plan.copies == 0


@needs("xarray")
def test_xarray():
    import xarray as xr
    da = xr.DataArray(np.arange(6.).reshape(2, 3), dims=("lat", "lon"), coords={"lat": [10., 20.], "lon": [1., 2., 3.]}, attrs={"units": "K"}, name="temp")
    assert roundtrip(da)[0].identical(da)
    ds = xr.Dataset({"t": da, "p": da * 2}, attrs={"title": "x"})
    assert roundtrip(ds)[0].identical(ds)
    tds = xr.DataArray(np.arange(3.), dims=("time",), coords={"time": pd.date_range("2020", periods=3)})
    assert roundtrip(tds)[0].identical(tds)


@needs("scipy")
def test_economics():
    import scipy.sparse as sp
    io = rp.io_table(np.eye(3), sectors=["agr", "man", "srv"], year=2020, units="MEUR")
    back, _ = roundtrip(io)
    assert back.rows == ["agr", "man", "srv"] and back.year == 2020 and back.units == "MEUR" and back.kind == "input_output"
    W = rp.spatial_weights(sp.csr_matrix(np.array([[0, 1, 0], [1, 0, 0], [0, 0, 0]])), ids=["r1", "r2", "r3"], style="W", kind="rook")
    back, _ = roundtrip(W)
    assert back.islands() == ["r3"] and back.style == "W" and back.kind == "rook"
    dy = rp.dyadic(pd.DataFrame({"exp": ["FR", "DE"], "imp": ["DE", "FR"], "year": [2020, 2020], "v": [1., 2.]}), source="exp", target="imp", time="year", value="v")
    back, _ = roundtrip(dy)
    assert back.source == "exp" and back.value == "v" and back.to_network().multigraph
    mf = rp.mixed_frequency({"q": pd.Series(range(8), index=pd.period_range("2020Q1", periods=8, freq="Q")),
                             "m": pd.Series(range(6), index=pd.date_range("2020-01-01", periods=6, freq="MS"))}, target="q")
    back, _ = roundtrip(mf)
    assert isinstance(back.series["q"].index, pd.PeriodIndex) and back.target == "q"
    ex = rp.experiment(pd.DataFrame({"i": [1, 1, 2, 2], "t": [1, 2, 1, 2], "d": [0, 1, 0, 0], "y": [1., 2., 1., 1.]}), treatment="d", outcome="y", unit="i", time="t", design="did")
    back, _ = roundtrip(ex)
    assert back.design == "did" and back.roles()["d"] == "treatment"
    sim = rp.simulation(pd.DataFrame({"rep": [1, 2], "est": [0.1, 0.2]}), replication="rep", seed=1, rng="numpy PCG64")
    back, ctx = roundtrip(sim)
    assert back.seed == 1 and any("RNG" in n for n in ctx.plan.notes)


def test_unknown_object_becomes_proxy_and_returns_same_object():
    class Weird:
        def hello(self):
            return "hi"
    w = Weird()
    back, ctx = roundtrip(w)
    assert back is w and ctx.plan.path.name == "PROXY"


def test_lazy_objects_never_materialised():
    gen = (i for i in range(10**9))
    back, ctx = roundtrip(gen)
    assert back is gen and ctx.plan.copies == 0


def test_autodetection_is_suggestion_only():
    df = pd.DataFrame({"country": ["FR"] * 3 + ["DE"] * 3, "year": [2000, 2001, 2002] * 2, "v": range(6)})
    plan = rp.explain_plan(df, print_it=False)
    assert plan.family == "table" and any("suggestion only" in n for n in plan.notes)
