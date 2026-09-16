"""Clean-install smoke test: run this with the *installed* package from a directory
outside the repository (so nothing from the source tree can be imported by accident).

    python -m build
    python -m venv .venv-wheel && .venv-wheel/bin/pip install dist/*.whl pandas pyarrow
    cd /tmp && python /path/to/tools/wheel_smoke.py [--no-r]

Checks: import, packaged compatibility resources, bundled R companion, and (with R)
scalar / DataFrame / Unicode / datetime / factor / plot round trips through the wheel.
"""
from __future__ import annotations

import os
import sys


def main() -> int:
    no_r = "--no-r" in sys.argv
    cwd = os.getcwd()
    import rpython as rp
    pkg_dir = os.path.dirname(os.path.abspath(rp.__file__))
    assert not os.path.abspath(cwd).startswith(os.path.dirname(pkg_dir)), "run this from outside the source tree"
    assert "site-packages" in pkg_dir or "dist-packages" in pkg_dir, f"rpython imported from a source tree: {pkg_dir}"
    print("import           ok", rp.__version__, pkg_dir)

    from rpython.compatibility import registry, load
    reg = registry()
    assert len(reg) >= 10 and load("pandas")["package"] == "pandas"
    print("compat resources ok", len(reg), "entries via importlib.resources")

    from rpython.runtime.r_session import r_source_dir
    rfiles = [f for f in os.listdir(r_source_dir()) if f.endswith(".R")]
    assert "worker.R" in rfiles and "rpx_encode.R" in rfiles, rfiles
    print("R companion      ok", len(rfiles), "files bundled")

    from rpython.data.convert import roundtrip
    import pandas as pd, numpy as np
    df = pd.DataFrame({"x": [1.5, np.nan], "c": pd.Categorical(["a", "b"], ordered=True), "t": pd.date_range("2024", periods=2, tz="UTC"), "é": ["عربي", "b"]})
    back, _ = roundtrip(df)
    assert back.equals(df)
    print("python roundtrip ok")

    if no_r:
        print("R checks skipped (--no-r)")
        return 0
    r = rp.R(timeout=300)
    assert r("1 + 1") == 2.0
    assert r("'héllo عربي'") == "héllo عربي"
    r["df"] = df
    assert r("is.ordered(df$c) && attr(df$t, 'tzone') == 'UTC'")
    assert r["df"].equals(df)
    assert r.eval("plot(1:3)").plots
    fit = r("lm(mpg ~ wt, data = mtcars)")
    assert abs(fit.coef().iloc[1] + 5.344) < 0.01
    rep = rp.doctor(print_it=False, start_r=False)
    assert all(m != "✗" for _, _, m in rep.rows), rep.render()
    r.close()
    print("R interop        ok (scalar, DataFrame, Unicode, datetime, factor, plot, proxy, doctor)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
