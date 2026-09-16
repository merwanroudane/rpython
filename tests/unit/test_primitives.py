"""Primitive types: Python -> envelope -> Python, with explicit missing-value semantics."""
import datetime as dt
import decimal
import enum
import fractions
import math
import uuid

import numpy as np
import pandas as pd
import pytest

from rpython.data.convert import roundtrip, to_envelope
from rpython.data.context import Context


class Color(enum.Enum):
    RED = 1
    BLUE = 2


@pytest.mark.parametrize("value", [
    None, True, False, 0, 1, -1, 2**31 - 1, 2**40, -(2**62), 1.5, -0.0, 1e300, 1 + 2j,
    "héllo", "عربي", "", "a\nb", b"\x00\x01\xff", bytearray(b"xyz"),
    decimal.Decimal("1.234567890123456789012345"), fractions.Fraction(3, 7), uuid.UUID(int=12345),
    dt.date(2024, 2, 29), dt.datetime(2024, 1, 2, 3, 4, 5, 678901), dt.timedelta(days=1, seconds=90),
    pd.Timestamp("2024-01-01 12:00", tz="Europe/Paris"), pd.Timedelta("1h30min"),
    np.int8(3), np.uint64(2**63), np.float32(1.25), np.bool_(True), np.str_("s"), Color.BLUE,
])
def test_scalar_roundtrip(value):
    back, ctx = roundtrip(value)
    if isinstance(value, (bytearray,)):
        assert bytes(value) == back
    elif isinstance(value, np.generic):
        assert back == value.item() or back == value
    else:
        assert back == value
    assert ctx.plan.fidelity.get("values").status.value == "lossless"


def test_nan_inf_distinct_from_none():
    assert math.isnan(roundtrip(float("nan"))[0])
    assert roundtrip(float("inf"))[0] == math.inf
    assert roundtrip(float("-inf"))[0] == -math.inf
    assert roundtrip(None)[0] is None
    env = to_envelope(float("nan"), Context())
    assert env["values"] == ["NaN"]
    env = to_envelope(None, Context())
    assert env["kind"] == "null"


def test_int64_precision_never_rounded():
    big = 2**60 + 1
    env = to_envelope(big, Context())
    assert env["type"] == "int64" and env["values"] == [str(big)]
    assert roundtrip(big)[0] == big
    ctx = Context()
    to_envelope(big, ctx)
    assert any("2^53" in r for r in ctx.plan.risks)


def test_int32_vs_int64_classification():
    assert to_envelope(5, Context())["type"] == "integer"
    assert to_envelope(2**31, Context())["type"] == "int64"


def test_naive_vs_aware_datetime():
    naive = dt.datetime(2024, 3, 31, 2, 30)
    aware = pd.Timestamp("2024-03-31 02:30", tz="UTC")
    assert to_envelope(naive, Context())["meta"]["tz"] == "naive"
    assert to_envelope(aware, Context())["meta"]["tz"] == "UTC"
    assert roundtrip(naive)[0] == naive and roundtrip(naive)[0].tzinfo is None
    assert roundtrip(aware)[0] == aware


def test_enum_restored():
    back, _ = roundtrip(Color.RED)
    assert back is Color.RED
