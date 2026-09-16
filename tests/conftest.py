"""Shared fixtures.  Tests marked ``r`` need a working R; they are skipped
(never silently passed) when R or the companion cannot start."""
from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("PYTHONIOENCODING", "utf-8")


def _r_available() -> bool:
    try:
        from rpython.env.detect import find_r
        return find_r() is not None
    except Exception:
        return False


def pytest_collection_modifyitems(config, items):
    if _r_available() and not os.environ.get("RPYTHON_SKIP_R"):
        return
    skip = pytest.mark.skip(reason="R runtime not available (set RPYTHON_R_HOME) or RPYTHON_SKIP_R set")
    for item in items:
        if "r" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def r():
    """One R worker for the whole test session."""
    from rpython.runtime.r_session import RSession
    s = RSession(timeout=600)
    yield s
    s.close()


@pytest.fixture
def tmp_path_str(tmp_path):
    return str(tmp_path)


def has(mod: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(mod) is not None


needs = lambda mod: pytest.mark.skipif(not has(mod), reason=f"{mod} not installed")  # noqa: E731
