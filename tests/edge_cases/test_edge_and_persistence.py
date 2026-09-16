"""Edge cases (section 47), persistence (31/66/67), explain mode, lock file, CLI."""
import json
import os
import subprocess
import sys
import warnings

import numpy as np
import pandas as pd
import pytest

import rpython as rp
from rpython.data.convert import roundtrip
from rpython.data.context import ConversionError
from tests.conftest import has


def test_dst_transition_and_ambiguous_times():
    idx = pd.date_range("2024-03-31 00:30", periods=4, freq="h", tz="Europe/Paris")   # DST jump 02:00 -> 03:00
    s = pd.Series(range(4), index=idx)
    back, _ = roundtrip(s)
    assert back.index.equals(idx) and [t.utcoffset().total_seconds() for t in back.index] == [3600, 3600, 7200, 7200]


def test_inf_nan_na_null_none_matrix():
    df = pd.DataFrame({"f": [np.inf, -np.inf, np.nan, 1.0], "i": pd.array([None, 1, 2, 3], dtype="Int64"),
                       "b": pd.array([True, None, False, True], dtype="boolean"), "s": ["x", None, "z", ""]})
    back, _ = roundtrip(df)
    assert back.equals(df)


def test_high_cardinality_factor_and_unused_levels():
    cat = pd.Categorical([f"c{i}" for i in range(5000)], categories=[f"c{i}" for i in range(6000)])
    back, _ = roundtrip(pd.Series(cat))
    assert len(back.cat.categories) == 6000 and back.iloc[-1] == "c4999"


def test_numeric_precision_edge_values():
    vals = [0.1 + 0.2, 1e-320, 1.7976931348623157e308, -2**53 - 1.0, 123456789.123456789]
    back, _ = roundtrip(vals)
    assert back == vals


def test_lossy_policy_error_and_allow():
    rp.config(lossy="error")
    try:
        with pytest.raises(ConversionError):
            roundtrip([pd.Timestamp("2024-01-01", tz="UTC"), pd.Timestamp("2024-01-01", tz="Asia/Tokyo")])
    finally:
        rp.reset_config()
    rp.config(lossy="allow")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            roundtrip([pd.Timestamp("2024-01-01", tz="UTC"), pd.Timestamp("2024-01-01", tz="Asia/Tokyo")])
    finally:
        rp.reset_config()


def test_missing_policy_nan_keeps_nan():
    rp.config(missing="nan")
    try:
        from rpython.data.convert import to_envelope
        from rpython.data.context import Context
        env = to_envelope(pd.DataFrame({"x": [np.nan]}), Context())
        assert env["columns"][0]["values"] == ["NaN"]
    finally:
        rp.reset_config()


def test_register_converter_extension():
    class Money:
        def __init__(self, amount, ccy):
            self.amount, self.ccy = amount, ccy

    rp.register_converter(family="money", kind="money", detect=lambda o: isinstance(o, Money),
                          encode=lambda o, ctx: {"amount": o.amount, "ccy": o.ccy},
                          decode=lambda env, ctx: Money(env["amount"], env["ccy"]))
    back, ctx = roundtrip(Money(5.0, "EUR"))
    assert isinstance(back, Money) and back.ccy == "EUR" and ctx.plan.family == "money"


def test_introspection_does_not_trigger_properties():
    calls = []

    class P:
        @property
        def boom(self):
            calls.append(1)
            raise RuntimeError("side effect")

        def m(self):
            pass
    info = rp.introspect(P())
    assert "boom" in info.properties and "m" in info.methods and calls == []


def test_save_load_formats(tmp_path):
    df = pd.DataFrame({"a": [1, 2], "c": pd.Categorical(["x", "y"], ordered=True), "t": pd.date_range("2020", periods=2, tz="UTC")})
    for ext in ("parquet", "feather", "json"):
        p = str(tmp_path / f"d.{ext}")
        rp.save(df, p)
        back = rp.load(p)
        assert back.shape == df.shape and list(back.columns) == list(df.columns)
    with pytest.warns(UserWarning):
        rp.save(df, str(tmp_path / "d.csv"))
    csv_back = rp.load(str(tmp_path / "d.csv"))
    assert csv_back["c"].cat.ordered and str(csv_back["t"].dt.tz) == "UTC"      # sidecar restored semantics
    arr = np.arange(6).reshape(2, 3)
    rp.save(arr, str(tmp_path / "a.npy"))
    assert np.array_equal(rp.load(str(tmp_path / "a.npy")), arr)
    with pytest.raises(ConversionError):
        rp.save(df, str(tmp_path / "d.unknownext"))


def test_bundle_roundtrip(tmp_path):
    p = rp.panel(pd.DataFrame({"id": ["a", "a", "b"], "year": [1, 2, 1], "v": [1., 2., 3.]}), id="id", time="year")
    b = rp.save(p, str(tmp_path / "panel.rpx"))
    assert os.path.exists(os.path.join(b, "manifest.json")) and os.path.exists(os.path.join(b, "portable", "envelope.json"))
    back = rp.load(b)
    assert isinstance(back.index, pd.MultiIndex) and back.attrs["rpython"]["panel"]["id"] == "id"
    from rpython.persistence.io import bundle_info
    assert bundle_info(b)["family"] == "panel"
    rich = rp.save(pd.DataFrame({"a": [1]}), str(tmp_path / "plain.rpx"))
    assert rp.load(rich).equals(pd.DataFrame({"a": [1]}))
    with pytest.raises(ConversionError):
        rp.config(lossy="error")
        try:
            rp.save(p, str(tmp_path / "panel.csv"))
        finally:
            rp.reset_config()


@pytest.mark.skipif(not has("pyreadstat"), reason="pyreadstat")
def test_stata_labels(tmp_path):
    lf = rp.labelled(pd.DataFrame({"sex": [1, 2], "inc": [1.0, 2.0]}), variable_labels={"inc": "Income"}, value_labels={"sex": {1: "male", 2: "female"}})
    p = str(tmp_path / "s.dta")
    rp.save(lf, p)
    back = rp.load(p)
    assert back.value_labels["sex"] == {1: "male", 2: "female"} and back.variable_labels["inc"] == "Income"


def test_explain_history_and_dry_run():
    rp.explain_plan(np.zeros((3, 3)), print_it=False)
    from rpython.explain import explain
    txt = explain(2, print_it=False)
    assert "numpy.ndarray" in txt or "Source:" in txt


def test_lockfile(tmp_path):
    from rpython.env.lock import lock
    p = str(tmp_path / "rpython.lock")
    data = lock(p, print_it=False)
    assert data["python"]["packages"]["pandas"] and os.path.exists(p)
    txt = open(p, encoding="utf-8").read()
    assert "password" not in txt.lower()


def test_cli_help_and_env():
    out = subprocess.run([sys.executable, "-m", "rpython.cli", "env", "--json"], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    data = json.loads(out.stdout)
    assert "python" in data and "r_candidates" in data
    out = subprocess.run([sys.executable, "-m", "rpython.cli", "--help"], capture_output=True, text=True, timeout=60)
    assert "doctor" in out.stdout and "self-test" in out.stdout


def test_worker_python_eval_captures():
    from rpython.worker import python_eval
    r = python_eval("import math\nprint('hi')\nmath.sqrt(9)")
    assert r.value == 3.0 and r.stdout == "hi\n" and r.error is None
    r = python_eval("1/0")
    assert r.error.startswith("ZeroDivisionError")
