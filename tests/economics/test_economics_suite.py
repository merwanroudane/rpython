"""Economics end-to-end suite (section 60): each dataset family goes
Python -> R -> Python with its structural semantics validated on both sides."""
import numpy as np
import pandas as pd
import pytest

import rpython as rp
from rpython.data.convert import roundtrip
from tests.conftest import has

pytestmark = pytest.mark.r


def macro_ts():
    idx = pd.period_range("2000Q1", periods=40, freq="Q")
    return pd.DataFrame({"gdp": np.cumsum(np.random.default_rng(0).normal(0.5, 1, 40)), "cpi": 100 + np.arange(40) * 0.5}, index=idx)


def test_macro_time_series(r):
    df = macro_ts()
    r["macro"] = df
    assert r("inherits(macro, 'mts') && frequency(macro) == 4 && start(macro)[1] == 2000 && ncol(macro) == 2")
    back = r["macro"]
    assert isinstance(back.index, pd.PeriodIndex) and back.index.freqstr.startswith("Q") and back.shape == (40, 2)
    assert np.allclose(back["gdp"].to_numpy(), df["gdp"].to_numpy())


def test_panel_regression_data(r):
    rng = np.random.default_rng(1)
    pdf = pd.DataFrame({"country": np.repeat([f"C{i}" for i in range(6)], 10), "year": list(range(2010, 2020)) * 6})
    pdf["x"] = rng.normal(size=60)
    pdf["y"] = 2 * pdf["x"] + rng.normal(size=60)
    p = rp.panel(pdf, id="country", time="year")
    r["p"] = p
    if r.capabilities["packages"].get("plm"):
        assert r("inherits(p, 'pdata.frame')")
        fit = r("plm::plm(y ~ x, data = p, model = 'within')")
        coef = fit.coef()
        assert abs(coef.iloc[0] - 2) < 0.3
    back = r["p"]
    assert back.index.names == ["country", "year"] and back.attrs["rpython"]["panel"]["balanced"]


def test_repeated_cross_sections_are_not_panels(r):
    df = pd.DataFrame({"wave": np.repeat([2010, 2015, 2020], 5), "hh": range(15), "income": np.arange(15.), "w": 1.0})
    rcs = rp.repeated_cross_section(df, wave="wave", weight="w")
    r["rcs"] = rcs
    assert r("!inherits(rcs, 'pdata.frame') && attr(rcs, 'rpython.panel')$kind == 'repeated_cross_section'")
    back = r["rcs"]
    assert not isinstance(back.index, pd.MultiIndex) and back.attrs["rpython"]["panel"]["kind"] == "repeated_cross_section"


def test_survey_microdata_labels_weights(r):
    lf = rp.labelled(pd.DataFrame({"sex": [1, 2, 2, 1], "region": [10, 20, 10, 30], "inc": [1000., 2000., None, 4000.], "w": [1.5, 0.7, 1.1, 0.9]}),
                     variable_labels={"sex": "Sex", "inc": "Monthly income", "w": "Survey weight"},
                     value_labels={"sex": {1: "male", 2: "female"}, "region": {10: "North", 20: "South", 30: "East"}},
                     missing_values={"inc": [-9]}, weight="w", strata="region")
    r["svy"] = lf
    assert r("inherits(svy$sex, 'haven_labelled') && names(attr(svy$sex, 'labels'))[2] == 'female' && attr(svy$inc, 'label') == 'Monthly income'")
    assert r("attr(svy, 'rpython.survey')$weight") == "w"
    back = r["svy"]
    assert back.value_labels["region"] == {10: "North", 20: "South", 30: "East"} and back.weight == "w" and back.strata == "region"


@pytest.mark.skipif(not has("shapely"), reason="shapely")
def test_spatial_panel(r):
    if not r.capabilities["packages"].get("sf"):
        pytest.skip("sf not installed")
    base = pd.DataFrame({"region": np.repeat(["A", "B"], 3), "year": [2000, 2001, 2002] * 2, "x": [1., 1., 1., 2., 2., 2.], "y": [1.] * 6, "gdp": np.arange(6.)})
    st = rp.spatiotemporal(rp.spatial(base, lon="x", lat="y", crs="EPSG:4326"), time="year", id="region", kind="spatial_panel")
    r["sp"] = st
    assert r("inherits(sp, 'sf') && sf::st_crs(sp)$epsg == 4326 && !is.null(attr(sp, 'rpython.spatiotemporal'))")
    back = r["sp"]
    assert back.kind == "spatial_panel" and back.id == "region" and len(back.data) == 6


@pytest.mark.skipif(not has("scipy"), reason="scipy")
def test_spatial_weights_matrix(r):
    import scipy.sparse as sp
    W = rp.spatial_weights(sp.csr_matrix(np.array([[0, 1, 1, 0], [1, 0, 0, 0], [1, 0, 0, 0], [0, 0, 0, 0]], dtype=float)), ids=["r1", "r2", "r3", "r4"], style="B", kind="queen")
    r["W"] = W
    if r.capabilities["packages"].get("spdep"):
        assert r("inherits(W, 'listw') && W$style == 'B'")
    else:
        assert r("Matrix::nnzero(W) == 4 && rownames(W)[4] == 'r4'")
    back = r["W"]
    assert back.islands() == ["r4"] and back.style == "B"


def test_bilateral_trade_dyadic(r):
    df = pd.DataFrame({"exporter": ["FR", "FR", "DE", "DE"], "importer": ["DE", "IT", "FR", "IT"], "year": [2020] * 4, "trade": [10., 5., 8., 3.]})
    dy = rp.dyadic(df, source="exporter", target="importer", time="year", value="trade", relation="exports")
    r["dy"] = dy
    assert r("is.data.frame(dy) && attr(dy, 'rpython.dyadic')$directed && attr(dy, 'rpython.roles')$trade == 'edge_weight'")
    back = r["dy"]
    assert back.source == "exporter" and back.value == "trade"
    if has("networkx") and r.capabilities["packages"].get("igraph"):
        g = dy.to_network()
        r["g"] = g
        assert r("igraph::ecount(g) == 4 && igraph::is_weighted(g) && igraph::is_directed(g)")


def test_input_output_matrix(r):
    Z = np.array([[10., 20., 5.], [5., 15., 10.], [2., 8., 30.]])
    io = rp.io_table(Z, sectors=["agri", "manuf", "serv"], year=2019, units="bn USD")
    r["Z"] = io
    assert r("identical(rownames(Z), c('agri', 'manuf', 'serv')) && attr(Z, 'rpython.economic')$year == 2019 && Z['agri', 'manuf'] == 20")
    back = r["Z"]
    assert back.rows == ["agri", "manuf", "serv"] and back.cols == back.rows and np.array_equal(np.asarray(back.values), Z)
    leontief = r("local({ x <- colSums(Z) + 10; A <- t(t(Z) / x); solve(diag(3) - A) })")
    assert leontief.shape == (3, 3)


def test_financial_high_frequency(r):
    idx = pd.date_range("2024-01-02 09:30:00", periods=500, freq="s", tz="America/New_York")
    ticks = pd.DataFrame({"price": 100 + np.cumsum(np.random.default_rng(2).normal(0, 0.01, 500)), "volume": np.random.default_rng(3).integers(1, 100, 500)}, index=idx)
    r["ticks"] = ticks
    assert r("inherits(ticks, 'xts') && nrow(ticks) == 500 && attr(zoo::index(ticks), 'tzone') == 'America/New_York'")
    back = r["ticks"]
    assert str(back.index.tz) == "America/New_York" and back.shape == (500, 2) and np.allclose(back["price"], ticks["price"])


@pytest.mark.skipif(not has("networkx"), reason="networkx")
def test_network_economics_graph(r):
    import networkx as nx
    g = nx.DiGraph()
    g.add_edge("bankA", "bankB", exposure=120.0)
    g.add_edge("bankB", "bankC", exposure=80.0)
    g.add_edge("bankC", "bankA", exposure=40.0)
    for n in g.nodes:
        g.nodes[n]["assets"] = 1000.0
    r["fin"] = g
    assert r("igraph::vcount(fin) == 3 && igraph::edge_attr(fin, 'exposure')[1] == 120 && igraph::vertex_attr(fin, 'assets')[1] == 1000")
    pr = r("igraph::page_rank(fin)$vector")
    assert abs(pr.sum() - 1) < 1e-9
    back = r["fin"]
    assert back["bankA"]["bankB"]["exposure"] == 120.0


def test_mixed_frequency_macro(r):
    mf = rp.mixed_frequency({"gdp": pd.Series(np.arange(8.), index=pd.period_range("2020Q1", periods=8, freq="Q")),
                             "cpi": pd.Series(np.arange(24.), index=pd.date_range("2020-01-01", periods=24, freq="MS"))}, target="gdp")
    r["mf"] = mf
    assert r("inherits(mf, 'list') && frequency(mf$gdp) == 4 && frequency(mf$cpi) == 12")
    back = r["mf"]
    assert isinstance(back.series["gdp"].index, pd.PeriodIndex) and back.series["cpi"].index.freqstr == "MS"


def test_staggered_did(r):
    df = pd.DataFrame({"unit": np.repeat([1, 2, 3], 4), "t": [1, 2, 3, 4] * 3, "cohort": np.repeat([2, 3, 0], 4)})
    df["d"] = ((df["cohort"] > 0) & (df["t"] >= df["cohort"])).astype(int)
    df["y"] = df["t"] + 2 * df["d"]
    ex = rp.experiment(df, treatment="d", outcome="y", unit="unit", time="t", cohort="cohort", design="staggered_did")
    r["ex"] = ex
    assert r("attr(ex, 'rpython.experiment')$design == 'staggered_did' && attr(ex, 'rpython.roles')$cohort == 'cohort'")
    back = r["ex"]
    assert back.design == "staggered_did" and back.cohort == "cohort"
