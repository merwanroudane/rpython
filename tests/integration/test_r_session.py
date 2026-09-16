"""Live R worker: execution, results, proxies, packages, plots, errors, callbacks."""
import math

import numpy as np
import pandas as pd
import pytest

import rpython as rp

pytestmark = pytest.mark.r


def test_scalars_both_directions(r):
    assert r("1 + 1") == 2.0
    assert r("'héllo عربي'") == "héllo عربي"
    assert r("TRUE") is True and r("NULL") is None
    assert r("NA") is None or pd.isna(r("NA"))
    r["x"] = 41
    assert r("x + 1") == 42
    r["s"] = "ça va"
    assert r("nchar(s)") == 5 and r("s") == "ça va"


def test_vectors_and_missing(r):
    r["v"] = [1.0, None, float("nan")]
    assert r("c(is.na(v)[2] && !is.nan(v)[2], is.nan(v)[3])").tolist() == [True, True]
    out = r("c(a=1, b=NA, c=NaN)")
    assert out.index.tolist() == ["a", "b", "c"] and out.iloc[0] == 1 and out.iloc[1] is pd.NA and math.isnan(out.iloc[2])
    assert np.isnan(r("c(NA, 1)")[0])            # NA-only -> NaN
    assert r("1:3").tolist() == [1, 2, 3] and r("1:3").dtype == np.int64
    assert r("c(TRUE, NA)")[1] is pd.NA
    assert r("as.raw(c(1,2,255))") == b"\x01\x02\xff"
    assert r("c(1+2i)") == 1 + 2j
    assert r("list(1, 'a', TRUE, NULL)") == [1.0, "a", True, None]
    assert r("list(a=1, b=list(c='x'))") == {"a": 1.0, "b": {"c": "x"}}


def test_result_model(r):
    res = r.eval("cat('out\\n'); message('msg'); warning('careful'); 42")
    assert res.value == 42 and res.stdout == "out" and res.messages == ["msg"] and res.warnings == ["careful"]
    assert res.plots == []
    res = r.eval("invisible(7)")
    assert res.value == 7 and not res.visible
    res = r.eval("x <- 3")
    assert res.value == 3 and not res.visible


def test_errors_are_actionable(r):
    with pytest.raises(rp.RError) as e:
        r("stop('boom')")
    assert "boom" in str(e.value)
    with pytest.raises(rp.RError) as e:
        r("library(notapkg)")
    assert "r.install('notapkg')" in str(e.value)
    with pytest.raises(rp.RError) as e:
        r("undefined_fn(1)")
    assert "load the package" in str(e.value)
    assert r.alive  # the session survives errors


def test_dataframe_roundtrip(r):
    df = pd.DataFrame({"x": [1.5, np.nan, 3.0], "s": ["a", "b", None], "i": pd.array([1, None, 3], dtype="Int64"),
                       "c": pd.Categorical(["lo", "hi", "lo"], categories=["lo", "hi"], ordered=True),
                       "t": pd.to_datetime(["2024-01-01", "2024-06-01", "2024-12-31"]).tz_localize("Europe/Paris"),
                       "d": pd.to_datetime(["2024-01-01", "2024-06-01", None]), "b": [True, False, True], "big": [2**40, 1, 2],
                       "ville é": [1, 2, 3], "مدينة": ["a", "b", "c"]})
    r["df"] = df
    assert r("is.ordered(df$c) && levels(df$c)[1] == 'lo'")
    assert r("format(df$t[1], tz = 'Europe/Paris', '%H')") == "00"
    assert r("attr(df$d, 'tzone')") == "UTC" and r("isTRUE(attr(df$d, 'rpython_naive'))")
    assert r("class(df$big)[1]") == "integer64"
    assert r("names(df)[9:10]").tolist() == ["ville é", "مدينة"]
    back = r["df"]
    assert back.equals(df), back.compare(df) if back.shape == df.shape else back
    assert rp.validate_roundtrip(df, r).lossless


def test_r_native_frames(r):
    head = r("head(mtcars, 3)")
    assert head.index.tolist() == ["Mazda RX4", "Mazda RX4 Wag", "Datsun 710"] and head.shape == (3, 11)
    iris = r("iris")
    assert isinstance(iris["Species"].dtype, pd.CategoricalDtype) and iris.shape == (150, 5)
    tib = r("tibble::tibble(a = 1:2, b = c('x', NA))")
    assert tib.attrs["rpython"]["class_hint"] == "tibble" and tib["b"].isna().tolist() == [False, True]
    dt = r("data.table::data.table(a = 1:3)")
    assert dt.attrs["rpython"]["class_hint"] == "data.table"
    r["tib"] = tib
    assert r("tibble::is_tibble(tib)")


def test_matrices_and_arrays(r):
    r["m"] = np.arange(6.).reshape(2, 3)
    assert r("dim(m)").tolist() == [2, 3] and r("m[1, 2]") == 1 and r("m[2, 1]") == 3
    assert np.array_equal(r("matrix(1:6, 2, 3)"), np.array([[1, 3, 5], [2, 4, 6]]))
    a = r("array(1:24, c(2, 3, 4))")
    assert a.shape == (2, 3, 4) and a[1, 2, 3] == 24 and a[0, 0, 0] == 1
    named = r("matrix(1:4, 2, dimnames = list(c('r1', 'r2'), c('c1', 'c2')))")
    assert named.dimnames == [["r1", "r2"], ["c1", "c2"]]
    r["f"] = np.asfortranarray(np.arange(6.).reshape(2, 3))
    assert r("m[2, 3] == f[2, 3]")
    r["mask"] = np.ma.masked_array([1., 2., 3.], mask=[0, 1, 0])
    assert r("is.na(mask)[2]")


def test_proxy_methods_fields(r):
    fit = r("lm(mpg ~ wt, data = mtcars)")
    assert isinstance(fit, rp.RObjectProxy) and fit.rclass == ["lm"] and fit.package == "stats"
    assert abs(fit.coef().iloc[1] + 5.344) < 0.01
    s = fit.summary()
    assert s.rclass == ["summary.lm"] and 0.75 < s.r_squared < 0.76
    pred = fit.predict(newdata=pd.DataFrame({"wt": [2.5, 3.0]}))
    assert len(pred) == 2 and abs(pred.iloc[0] - 23.92) < 0.01
    assert "coefficients" in fit.fields() and len(fit.residuals) == 32
    assert "predict" in fit.methods()
    p = fit.plot()
    assert isinstance(p, rp.Plot)
    assert isinstance(fit.to_python(), dict)
    r6 = r("R6::R6Class('Counter', public = list(n = 0, add = function(k = 1) { self$n <- self$n + k; invisible(self) }))$new()")
    r6.add(5)
    assert r6.n == 5


def test_packages_and_functions(r):
    stats = r.package("stats")
    assert stats.median([1, 2, 3, 10]) == 2.5
    if r.installed("forecast")["forecast"]:
        assert "auto.arima" in dir(r.package("forecast"))   # dotted names are listed as R spells them
    fn = r.function("paste")
    assert fn("a", "b", sep="-") == "a-b"
    sig = r.signature("stats::lm")
    assert "formula" in sig["args"] and sig["doc"]
    assert r.installed("stats", "notapkg") == {"stats": True, "notapkg": False}
    base = r.package("base")
    assert base.nchar("héllo") == 5
    assert base["sum"]([1, 2, 3]) == 6


def test_plots(r, tmp_path):
    res = r.eval("plot(1:10); hist(rnorm(20))")
    assert len(res.plots) == 2 and res.plot.path.endswith(".png")
    out = res.plot.save(str(tmp_path / "h.png"))
    assert (tmp_path / "h.png").stat().st_size > 1000
    if r.capabilities["packages"].get("ggplot2"):
        g = r("ggplot2::ggplot(mtcars, ggplot2::aes(wt, mpg)) + ggplot2::geom_point()")
        assert isinstance(g, rp.RObjectProxy) and "ggplot" in g.rclass
        assert r.last.plot is not None
        if r("nzchar(system.file(package = 'svglite')) || isTRUE(capabilities('cairo'))"):
            g.save(str(tmp_path / "g.svg"))
            assert (tmp_path / "g.svg").stat().st_size > 1000
        else:
            with pytest.raises(rp.RError, match="svglite"):
                g.save(str(tmp_path / "g.svg"))
        g.save(str(tmp_path / "g.pdf"))
        assert (tmp_path / "g.pdf").stat().st_size > 1000


def test_python_callables_and_objects_in_r(r):
    r["f"] = lambda a, b=1: a + b
    assert r("f(2, b = 3)") == 5
    import math as m
    r["pymath"] = m
    assert r("pymath$pi") == m.pi and r("pymath$sqrt(16)") == 4

    class Acc:
        def __init__(self):
            self.total = 0

        def add(self, x):
            self.total += x
            return self.total
    acc = Acc()
    r["acc"] = acc
    assert r("acc$add(5); acc$add(2)") == 7 and acc.total == 7
    assert r["acc"] is acc
    r["df_fn"] = lambda df: df.assign(z=df["x"] * 2)
    assert r("df_fn(data.frame(x = 1:2))$z").tolist() == [2, 4]


def test_time_series_panel(r):
    ts = pd.Series(np.arange(24.), index=pd.date_range("2020-01-01", periods=24, freq="MS"), name="y")
    r["y"] = ts
    assert r("is.ts(y) && frequency(y) == 12 && start(y)[1] == 2020")
    back = r["y"]
    assert back.equals(ts) and back.index.freq == ts.index.freq
    q = r("ts(1:8, start = c(2020, 1), frequency = 4)")
    assert isinstance(q.index, pd.PeriodIndex) and str(q.index[0]) == "2020Q1"
    irr = pd.DataFrame({"v": [1., 2., 3.]}, index=pd.DatetimeIndex(["2020-01-01", "2020-01-05", "2020-02-01"], tz="UTC"))
    r["irr"] = irr
    assert r("inherits(irr, 'xts')") and r["irr"].equals(irr)
    pdf = pd.DataFrame({"country": np.repeat(["FR", "DE"], 3), "year": [2000, 2001, 2002] * 2, "gdp": np.arange(6.)})
    r["p"] = rp.panel(pdf, id="country", time="year")
    if r.capabilities["packages"].get("plm"):
        assert r("inherits(p, 'pdata.frame')")
    assert r("attr(p, 'rpython.panel')$balanced")
    back = r["p"]
    assert isinstance(back.index, pd.MultiIndex) and back.index.names == ["country", "year"]


def test_labelled_survival_sparse_network_spatial(r):
    from tests.conftest import has
    lf = rp.labelled(pd.DataFrame({"sex": [1, 2, -9]}), value_labels={"sex": {1: "male", 2: "female"}}, variable_labels={"sex": "Sex"},
                     missing_values={"sex": [-9]})
    r["lf"] = lf
    assert r("inherits(lf$sex, 'haven_labelled') && attr(lf$sex, 'label') == 'Sex' && -9 %in% attr(lf$sex, 'na_values')")
    back = r["lf"]
    assert back.value_labels["sex"] == {1: "male", 2: "female"} and back.missing_values == {"sex": [-9]}
    sv = rp.survival(pd.DataFrame({"t": [1., 2., 3.], "d": [1, 0, 1], "age": [50, 60, 70]}), time="t", event="d")
    r["sv"] = sv
    assert r("inherits(sv, 'Surv') && nrow(attr(sv, 'rpython.covariates')) == 3")
    assert r["sv"].data["d"].tolist() == [1., 0., 1.]
    if has("scipy"):
        import scipy.sparse as sp
        m = sp.random(50, 40, density=0.1, format="csc", random_state=1)
        r["sm"] = m
        assert r("inherits(sm, 'dgCMatrix')") and (r["sm"] != m).nnz == 0
        coo = m.tocoo()
        r["coo"] = coo
        assert r("inherits(coo, 'dgTMatrix')") and r["coo"].format == "coo"
        sym = r("Matrix::forceSymmetric(Matrix::Matrix(c(1,2,2,3), 2, sparse = TRUE))")
        assert (sym.toarray() == np.array([[1, 2], [2, 3]])).all()
    if has("networkx"):
        import networkx as nx
        g = nx.MultiDiGraph([("a", "b"), ("a", "b"), ("b", "c"), ("c", "c")])
        g.nodes["a"]["kind"] = "root"
        r["g"] = g
        assert r("igraph::ecount(g) == 4 && igraph::is_directed(g) && igraph::any_multiple(g) && any(igraph::which_loop(g))")
        back = r["g"]
        assert back.number_of_edges() == 4 and back.is_multigraph() and back.nodes["a"]["kind"] == "root"
        undirected = r("igraph::make_ring(5)")
        assert not undirected.is_directed() and undirected.number_of_edges() == 5
    if has("shapely") and r.capabilities["packages"].get("sf"):
        import shapely
        gdf = rp.spatial(pd.DataFrame({"n": ["a", "b"], "x": [2.0, 3.0], "y": [48.0, 49.0]}), lon="x", lat="y", crs="EPSG:4326")
        r["g2"] = gdf
        assert r("inherits(g2, 'sf') && sf::st_crs(g2)$epsg == 4326 && as.character(sf::st_geometry_type(g2)[1]) == 'POINT'")
        back = r["g2"]
        assert back["geometry"][1].equals(shapely.Point(3, 49))
        poly = r("sf::st_sf(id = 1, geometry = sf::st_sfc(sf::st_polygon(list(rbind(c(0,0), c(1,0), c(1,1), c(0,0)))), crs = 3857))")
        blk = poly.attrs.get("rpython", {}).get("spatial") if not hasattr(poly, "crs") else None
        crs_epsg = poly.crs.to_epsg() if hasattr(poly, "crs") else blk["crs"]["epsg"]
        assert crs_epsg == 3857 and poly["geometry"][0].area == 0.5


def test_xarray_and_dimnames(r):
    from tests.conftest import has
    if not has("xarray"):
        pytest.skip("xarray")
    import xarray as xr
    da = xr.DataArray(np.arange(6.).reshape(2, 3), dims=("lat", "lon"), coords={"lat": [10., 20.], "lon": [1., 2., 3.]}, attrs={"units": "K"}, name="temp")
    r["da"] = da
    assert r("identical(dim(da), c(2L, 3L)) && dimnames(da)[[1]][2] == '20.0' && attr(da, 'rpython.attrs')$units == 'K'")
    back = r["da"]
    assert isinstance(back, xr.DataArray) and back.dims == ("lat", "lon") and back.attrs["units"] == "K"
    assert np.array_equal(back.values, da.values)


def test_arrow_and_large(r):
    big = pd.DataFrame({"a": np.arange(20000), "b": np.random.rand(20000), "c": pd.Categorical(np.random.choice(["x", "y"], 20000)),
                        "t": pd.date_range("2020-01-01", periods=20000, freq="h")})
    r["big"] = big
    assert rp.explain_last(print_it=False).count("arrow-ipc") == 1
    back = r["big"]
    assert back.equals(big)
    r["arr"] = np.arange(100_000.)
    assert r("length(arr) == 1e5 && arr[100000] == 99999")
    assert np.array_equal(r["arr"], np.arange(100_000.))


def test_save_load_rds_and_bundle(r, tmp_path):
    fit = r("lm(mpg ~ wt, data = mtcars)")
    p = fit.save(str(tmp_path / "fit.rds"))
    back = r.load_rds(p, convert=False)
    assert back.rclass == ["lm"]
    df = pd.DataFrame({"a": [1, 2], "c": pd.Categorical(["x", "y"], ordered=True)})
    rp.save(df, str(tmp_path / "df.rds"), session=r)
    assert rp.load(str(tmp_path / "df.rds"), session=r).equals(df)
    b = rp.save(fit, str(tmp_path / "fit.rpx"), session=r)
    assert rp.load(b, session=r).rclass == ["lm"]


def test_explain_mode(r):
    r["df"] = pd.DataFrame({"a": [1, 2]})
    txt = rp.explain_last(print_it=False)
    assert "Source: pandas.DataFrame" in txt and "Target: R" in txt and "lossless" in txt
    plan = rp.explain_plan(pd.DataFrame({"x": [1.0]}), print_it=False)
    assert plan.family == "table"


def test_session_lifecycle():
    s = rp.RSession(timeout=120)
    assert s.ping() and s.alive
    s.close()
    assert not s.alive
    s.restart()
    assert s("1") == 1
    s.close()
    with rp.RSession(timeout=120) as s2:
        assert s2("2") == 2
    assert not s2.alive
