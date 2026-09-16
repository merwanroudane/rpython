import collections
import dataclasses
import math

import numpy as np
import pytest

from rpython.data.convert import roundtrip, to_envelope
from rpython.data.context import Context, MemoryGuardError
from rpython.data.collections import CycleRef


@dataclasses.dataclass
class Point:
    x: float
    y: float
    tag: str = "p"


Pair = collections.namedtuple("Pair", "a b")


@pytest.mark.parametrize("value", [
    [1, 2, 3], [1.0, None, float("nan")], ["a", None, "c"], (1, 2), {"a": 1, "b": [1, 2]}, {1: "x", (2, 3): "y"},
    [1, "a", None, [2, 3]], {"nested": {"x": [1, 2, {"y": None}]}}, set([1, 2]), frozenset({"a"}),
    collections.OrderedDict(a=1, b=2), Pair(1, "z"), Point(1.0, 2.0), [], {}, [[]], [None, None],
    [True, False, None], [b"x", b"y"], ["mixed", 1, 2.5, True],
])
def test_collection_roundtrip(value):
    back, _ = roundtrip(value)
    if isinstance(value, list) and any(isinstance(v, float) and math.isnan(v) for v in value):
        assert [None if v is None else ("nan" if isinstance(v, float) and math.isnan(v) else v) for v in back] == \
               [None if v is None else ("nan" if isinstance(v, float) and math.isnan(v) else v) for v in value]
    else:
        assert back == value
        assert type(back) is type(value)


def test_homogeneous_list_becomes_atomic_vector_with_container_meta():
    env = to_envelope([1, 2, 3], Context())
    assert env["kind"] == "vector" and env["type"] == "integer" and env["meta"]["container"] == "list"
    env = to_envelope((1.5, 2.5), Context())
    assert env["meta"]["container"] == "tuple"


def test_heterogeneous_list_is_r_list():
    env = to_envelope([1, "a"], Context())
    assert env["kind"] == "list" and [i["kind"] for i in env["items"]] == ["vector", "vector"]


def test_cycle_detection():
    a = [1]
    a.append(a)
    back, ctx = roundtrip(a)
    assert isinstance(back[1], CycleRef)
    assert any("cycle" in w for w in ctx.warnings)


def test_ndarray_roundtrip_shapes_orders():
    for arr in (np.arange(6).reshape(2, 3), np.asfortranarray(np.arange(24.).reshape(2, 3, 4)), np.arange(6).reshape(2, 3)[:, ::2],
                np.zeros((0, 3)), np.array(5.0), np.array([1e-300, 1e300, -0.0])):
        back, ctx = roundtrip(arr)
        assert back.shape == arr.shape and np.array_equal(back, arr) and back.dtype == arr.dtype


def test_memory_order_is_explicit_not_transposed():
    c = np.arange(6).reshape(2, 3)
    f = np.asfortranarray(c)
    ec, ef = to_envelope(c, Context()), to_envelope(f, Context())
    assert ec["order"] == "C" and ef["order"] == "F"
    assert ec["values"] == [0, 1, 2, 3, 4, 5] and ef["values"] == [0, 3, 1, 4, 2, 5]
    assert np.array_equal(roundtrip(c)[0], roundtrip(f)[0])


def test_masked_array_roundtrip():
    m = np.ma.masked_array(np.arange(6.).reshape(2, 3), mask=[[0, 1, 0], [1, 0, 0]])
    back, _ = roundtrip(m)
    assert np.ma.isMaskedArray(back) and np.array_equal(np.ma.getmaskarray(back), np.ma.getmaskarray(m))
    assert np.array_equal(back.compressed(), m.compressed())


@pytest.mark.parametrize("dtype", ["int8", "int16", "uint8", "uint16", "int32", "uint32", "int64", "float32", "float64", "bool", "complex128"])
def test_dtype_restored(dtype):
    arr = (np.arange(4) % 2).astype(dtype)
    back, ctx = roundtrip(arr)
    assert back.dtype == arr.dtype and np.array_equal(back, arr)


def test_uint64_beyond_int64_goes_int64_string():
    arr = np.array([2**63 + 1], dtype=np.uint64)
    env = to_envelope(arr, Context())
    assert env["dtype"] == "int64" and env["values"] == [str(2**63 + 1)]


def test_unicode_strings_array():
    arr = np.array(["é", "عربي", "日本語"])
    back, _ = roundtrip(arr)
    assert back.tolist() == arr.tolist()


@pytest.mark.skipif(not __import__("importlib").util.find_spec("torch"), reason="torch not installed")
def test_torch_tensor():
    import torch
    t = torch.arange(6, dtype=torch.float32).reshape(2, 3)
    back, ctx = roundtrip(t)
    assert isinstance(back, torch.Tensor) and torch.equal(back, t)
    assert ctx.plan.history[0].note.startswith("6 elements")
