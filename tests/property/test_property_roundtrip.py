"""Property-based / fuzz tests (sections 48, 62): random structures must round
trip without silent corruption.  Seeds are recorded by Hypothesis' database;
``--hypothesis-seed`` reproduces failures."""
import math

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings, strategies as st, HealthCheck

from rpython.data.convert import roundtrip
from rpython.fidelity import compare

names = st.text(alphabet=st.characters(blacklist_categories=("Cs",), min_codepoint=32), min_size=1, max_size=12)
scalars = st.one_of(st.none(), st.booleans(), st.integers(-2**62, 2**62), st.floats(allow_nan=True, allow_infinity=True),
                    st.text(max_size=20), st.binary(max_size=10))


def _eq(a, b) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        return (math.isnan(a) and math.isnan(b)) or a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_eq(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_eq(x, y) for x, y in zip(a, b))
    return a == b


nested = st.recursive(scalars, lambda inner: st.one_of(st.lists(inner, max_size=5), st.dictionaries(names, inner, max_size=5),
                                                       st.tuples(inner, inner)), max_leaves=25)


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(nested)
def test_nested_structures(value):
    back, _ = roundtrip(value)
    assert _eq(back, value)


@settings(max_examples=100, deadline=None)
@given(st.lists(st.floats(allow_nan=True, allow_infinity=True, width=64), max_size=50),
       st.lists(st.integers(-2**31 + 1, 2**31 - 1), max_size=50), st.lists(st.one_of(st.none(), st.text(max_size=8)), max_size=50))
def test_typed_columns(fl, ints, strs):
    n = max(len(fl), len(ints), len(strs))
    df = pd.DataFrame({"f": (fl + [np.nan] * n)[:n], "i": (ints + [0] * n)[:n], "s": (strs + [None] * n)[:n]})
    back, _ = roundtrip(df)
    rep = compare(df, back)
    assert rep.lossless, rep.summary()


@settings(max_examples=60, deadline=None)
@given(st.lists(names, min_size=1, max_size=6, unique=True), st.integers(0, 20), st.sampled_from(["json", "arrow"]))
def test_unicode_and_duplicate_columns(cols, n, transfer):
    import rpython as rp
    rp.config(transfer=transfer, arrow_threshold_rows=0)
    try:
        df = pd.DataFrame({c: np.arange(n, dtype=float) for c in cols})
        df.columns = list(cols) + []
        dup = pd.concat([df, df.iloc[:, :1]], axis=1)   # duplicate first column name
        back, _ = roundtrip(dup)
        assert back.columns.tolist() == dup.columns.tolist() and back.shape == dup.shape
    finally:
        rp.reset_config()


@settings(max_examples=60, deadline=None)
@given(st.lists(st.sampled_from(["a", "b", "c", None]), min_size=1, max_size=30), st.booleans(), st.lists(st.sampled_from(["a", "b", "c", "d"]), min_size=1, max_size=4, unique=True))
def test_categorical_levels_and_order(values, ordered, levels):
    cat = pd.Series(pd.Categorical(values, categories=levels, ordered=ordered))
    back, _ = roundtrip(cat)
    assert list(back.cat.categories) == levels and back.cat.ordered == ordered
    assert back.isna().tolist() == cat.isna().tolist() and back.astype(object).where(back.notna(), None).tolist() == cat.astype(object).where(cat.notna(), None).tolist()


@settings(max_examples=40, deadline=None)
@given(st.integers(1, 200), st.sampled_from(["D", "h", "MS", "QS", "YS", "W", "min"]), st.sampled_from([None, "UTC", "Europe/Paris", "Asia/Tokyo"]),
       st.lists(st.integers(1, 199), max_size=5, unique=True))
def test_time_series_with_gaps_and_tz(n, freq, tz, drop):
    idx = pd.date_range("2020-01-01", periods=n, freq=freq, tz=tz)
    s = pd.Series(np.arange(n, dtype=float), index=idx)
    s = s.drop(idx[[d for d in drop if d < n]])
    back, ctx = roundtrip(s)
    assert back.index.equals(s.index) and np.array_equal(back.to_numpy(), s.to_numpy())
    assert str(back.index.tz) == str(s.index.tz)


@settings(max_examples=40, deadline=None)
@given(st.integers(1, 6), st.integers(1, 6), st.integers(0, 3), st.sampled_from(["C", "F"]))
def test_arrays_random_shape_order(a, b, c, order):
    shape = (a, b, c) if c else (a, b)
    arr = np.asarray(np.random.rand(*shape), order=order)
    back, _ = roundtrip(arr)
    assert back.shape == arr.shape and np.array_equal(back, arr)


@settings(max_examples=30, deadline=None)
@given(st.integers(2, 15), st.floats(0.0, 0.6), st.booleans())
def test_random_graphs(n, p, directed):
    nx = pytest.importorskip("networkx")
    g = nx.gnp_random_graph(n, p, seed=int(p * 1000) + n, directed=directed)
    for i, (u, v) in enumerate(g.edges()):
        g.edges[u, v]["w"] = float(i)
    back, _ = roundtrip(g)
    assert compare(g, back).lossless


@settings(max_examples=30, deadline=None)
@given(st.integers(1, 30), st.integers(1, 30), st.floats(0.0, 0.5), st.sampled_from(["csr", "csc", "coo"]))
def test_random_sparse(m, n, density, fmt):
    sp = pytest.importorskip("scipy.sparse")
    mat = sp.random(m, n, density=density, format=fmt, random_state=m * 31 + n)
    back, _ = roundtrip(mat)
    assert (back.tocsr() != mat.tocsr()).nnz == 0 and back.format == fmt


@settings(max_examples=30, deadline=None)
@given(st.integers(2, 6), st.integers(2, 8), st.integers(0, 5), st.integers(0, 3))
def test_random_panels(n_ent, n_per, gaps, dups):
    import rpython as rp
    rows = [(f"e{i}", 2000 + t) for i in range(n_ent) for t in range(n_per)]
    rows = rows[gaps:] + (rows[-dups:] if dups else [])
    if not rows:
        return
    df = pd.DataFrame(rows, columns=["id", "year"])
    df["v"] = np.arange(len(df), dtype=float)
    p = rp.panel(df, id="id", time="year")
    st_ = p.structure()
    exp_dups = len(df) - len(df.drop_duplicates(["id", "year"]))
    per_entity = df.drop_duplicates(["id", "year"]).groupby("id")["year"].nunique()
    exp_balanced = bool(per_entity.nunique() == 1 and per_entity.iloc[0] == df["year"].nunique())
    assert st_["duplicates"] == exp_dups
    assert st_["balanced"] == exp_balanced
    back, _ = roundtrip(p)
    assert back.attrs["rpython"]["panel"]["duplicates"] == exp_dups
