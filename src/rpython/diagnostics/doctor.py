"""Diagnostics: ``doctor()``, ``check()``, ``self_test()``, ``fix()``, ``restore()``
(MASTER_PROMPT sections 32, 52)."""
from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass, field
from typing import Any

from ..env.detect import detect_python, find_r, find_r_candidates

OK, WARN, FAIL = "✓", "⚠", "✗"


@dataclass
class Report:
    rows: list[tuple[str, str, str]] = field(default_factory=list)   # (label, value, mark)
    issues: list[str] = field(default_factory=list)
    fixes: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)

    def add(self, label: str, value: str, mark: str = OK) -> None:
        self.rows.append((label, value, mark))

    def issue(self, text: str, fix: str | None = None) -> None:
        self.issues.append(text)
        if fix:
            self.fixes.append(fix)

    @property
    def ok(self) -> bool:
        return not any(m == FAIL for _, _, m in self.rows)

    def render(self) -> str:
        w = max((len(l) for l, _, _ in self.rows), default=10) + 2
        lines = [f"{l.ljust(w)} {v} {m}" for l, v, m in self.rows]
        if self.issues:
            lines.append("")
            lines.append("Issues:")
            lines += [f"- {i}" for i in self.issues]
        if self.fixes:
            lines.append("")
            lines.append("Suggested fix:")
            lines += [f"  {f}" for f in self.fixes]
        return "\n".join(lines)

    def __repr__(self) -> str:
        return self.render()


def _env_name(py: Any) -> str:
    if py.in_colab:
        return "Google Colab"
    if py.in_jupyter:
        return "Jupyter"
    if py.in_vscode:
        return "VS Code"
    if py.in_docker:
        return "Docker"
    return "terminal / script"


def doctor(print_it: bool = True, start_r: bool = True) -> Report:
    """Environment report: platform, Python, R (all candidates), key packages, bridge readiness."""
    rep = Report()
    py = detect_python()
    rep.add("Platform", f"{platform.system()} {platform.release()} ({platform.machine()})")
    rep.add("Environment", _env_name(py))
    rep.add("Python", f"{py.version}  {py.executable}  [{py.kind}{' / ' + py.manager if py.manager else ''}]")
    cands = find_r_candidates()
    chosen = find_r()
    if chosen is None:
        rep.add("R", "not found", FAIL)
        rep.issue("No R installation detected (checked RPYTHON_R_HOME, R_HOME, PATH, registry, standard locations)",
                  "install R from https://cran.r-project.org/ then set RPYTHON_R_HOME=<R home> if it is not on PATH")
    else:
        rep.add("R", f"{chosen.version}  {chosen.home}  [via {chosen.source}]")
        if len(cands) > 1:
            rep.add("R installations", "; ".join(f"{c.version} ({c.source})" for c in cands), WARN)
            rep.issue(f"{len(cands)} R installations found; using {chosen.version} from {chosen.source}. "
                      "Set RPYTHON_R_HOME or rp.config(r_home=...) to choose explicitly.")
    for pkg in ("pandas", "numpy", "pyarrow", "polars", "scipy", "xarray", "networkx", "shapely", "geopandas", "duckdb", "sqlalchemy"):
        v = py.packages.get(pkg)
        rep.add(f"  {pkg}", v or "not installed", OK if v else (WARN if pkg not in ("pandas", "numpy") else FAIL))
    if not py.packages.get("pyarrow"):
        rep.issue("pyarrow missing: large tables fall back to JSON transfer", "pip install pyarrow")
    rep.add("Jupyter", "detected" if py.in_jupyter else "not active", OK if py.in_jupyter else WARN)
    rep.data["python"] = py.to_dict()
    rep.data["r_candidates"] = [c.to_dict() for c in cands]
    if chosen is not None and start_r:
        try:
            from ..runtime.r_session import RSession
            with RSession(timeout=120) as s:
                caps = s.capabilities
                rep.add("R worker", f"ready (R {caps.get('r_version')}, pid {caps.get('pid')})")
                pk = caps.get("packages") or {}
                rep.add("  jsonlite", "ok" if pk.get("jsonlite") else "missing", OK if pk.get("jsonlite") else FAIL)
                rep.add("  arrow (R)", "ok" if pk.get("arrow") else "missing", OK if pk.get("arrow") else WARN)
                for p in ("data.table", "sf", "igraph", "Matrix", "xts", "haven", "survival", "plm", "terra", "duckdb", "RSQLite", "ggplot2"):
                    rep.add(f"  {p}", "ok" if pk.get(p) else "missing", OK if pk.get(p) else WARN)
                missing = [p for p in ("arrow", "data.table", "sf", "igraph", "Matrix", "xts", "haven", "survival") if not pk.get(p)]
                if missing:
                    rep.issue(f"R packages missing for full semantic coverage: {', '.join(missing)}",
                              f"rp.fix()   # or in R: install.packages(c({', '.join(repr(m) for m in missing)}))")
                rep.add("Python -> R -> Python", "ok" if _roundtrip_ok(s) else "failed", OK if _roundtrip_ok(s) else FAIL)
                rep.add("Plot transport", "ok" if _plot_ok(s) else "failed", OK if _plot_ok(s) else WARN)
                rep.data["r"] = caps
        except Exception as e:  # noqa: BLE001
            rep.add("R worker", f"failed to start: {e}", FAIL)
            rep.issue(f"R worker could not start: {e}", "install.packages('jsonlite') in R; then rp.doctor() again")
    rep.add("Magics", "available (%r / %%r / %py / %%py)" if _has_ipython() else "IPython not installed", OK if _has_ipython() else WARN)
    if print_it:
        print(rep.render())
    return rep


def _roundtrip_ok(s: Any) -> bool:
    try:
        import pandas as pd
        df = pd.DataFrame({"x": [1, 2, None], "c": pd.Categorical(["a", "b", "a"], ordered=True)})
        s.assign(".rp_doc", df)
        back = s.get(".rp_doc")
        return list(back.columns) == ["x", "c"] and back["c"].cat.ordered
    except Exception:
        return False


def _plot_ok(s: Any) -> bool:
    try:
        res = s.eval("plot(1:3)")
        return bool(res.plots)
    except Exception:
        return False


def _has_ipython() -> bool:
    try:
        import IPython  # noqa: F401
        return True
    except Exception:
        return False


def check(print_it: bool = True) -> bool:
    """Lightweight readiness test: R found and the worker answers ``ping``."""
    ok = find_r() is not None
    if ok:
        try:
            from ..runtime.r_session import RSession
            with RSession(timeout=60) as s:
                ok = s.ping()
        except Exception:
            ok = False
    if print_it:
        print(f"RPython bridge {'ready ' + OK if ok else 'not ready ' + FAIL + ' (run rp.doctor())'}")
    return ok


def self_test(full: bool = False, print_it: bool = True, session: Any = None) -> Report:
    """User-facing interoperability self-test across the core families."""
    import numpy as np
    import pandas as pd
    from ..runtime.r_session import RSession
    rep = Report()
    s = session or RSession(timeout=300)
    own = session is None

    def t(label: str, fn: Any) -> None:
        try:
            ok = bool(fn())
        except Exception as e:  # noqa: BLE001
            ok = False
            rep.issue(f"{label}: {type(e).__name__}: {str(e).splitlines()[0][:160]}")
        rep.add(label, "", OK if ok else FAIL)

    t("Python -> R scalar", lambda: (s.assign("x", 41), s.run("x + 1") == 42)[1])
    t("R -> Python scalar", lambda: s.run("'héllo'") == "héllo")
    t("Python -> R vector", lambda: (s.assign("v", [1.0, None, float('nan')]), s.run("c(is.na(v)[2] && !is.nan(v)[2], is.nan(v)[3])").tolist() == [True, True])[1])
    df = pd.DataFrame({"x": [1.5, np.nan, 3.0], "s": ["a", "b", None], "i": pd.array([1, None, 3], dtype="Int64"),
                       "c": pd.Categorical(["lo", "hi", "lo"], categories=["lo", "hi"], ordered=True),
                       "t": pd.to_datetime(["2024-01-01", "2024-06-01", "2024-12-31"]).tz_localize("Europe/Paris")})
    t("pandas -> R data.frame", lambda: (s.assign("df", df), s.run("is.data.frame(df) && is.ordered(df$c) && inherits(df$t, 'POSIXct')"))[1])
    t("R data.frame -> pandas", lambda: s.get("df").equals(df))
    t("categorical / factor", lambda: list(s.get("df")["c"].cat.categories) == ["lo", "hi"] and s.get("df")["c"].cat.ordered)
    t("datetime + timezone", lambda: str(s.get("df")["t"].dt.tz) == "Europe/Paris" and s.run("format(df$t[1], tz='Europe/Paris', '%H')") == "00")
    t("missing values (pandas NaN -> NA, None -> NA)", lambda: s.run("c(sum(is.na(df$x)), sum(is.nan(df$x)), is.na(df$s[3]))").tolist() == [1, 0, 1])
    t("missing values (R NA / NaN / Inf -> Python)", lambda: (lambda v: bool(v[0] is pd.NA and np.isnan(v[1]) and np.isinf(v[2])) and bool(np.isnan(s.run("c(NA, 1)")[0])))(s.run("c(NA, NaN, Inf)")))
    ts = pd.Series(np.arange(24.0), index=pd.date_range("2020-01-01", periods=24, freq="MS"), name="y")
    t("time series (ts, frequency)", lambda: (s.assign("y", ts), s.run("is.ts(y) && frequency(y) == 12 && start(y)[1] == 2020"))[1])
    from ..data.panel import panel
    p = panel(pd.DataFrame({"id": ["a", "a", "b", "b"], "year": [2000, 2001, 2000, 2001], "v": [1.0, 2.0, 3.0, 4.0]}), id="id", time="year")
    t("panel metadata", lambda: (s.assign("p", p), s.run("!is.null(attr(p, 'rpython.panel')) && identical(attr(p, 'rpython.panel')$id, 'id')"))[1])
    t("numpy matrix -> R matrix", lambda: (s.assign("m", np.arange(6.).reshape(2, 3)), s.run("dim(m)[1] == 2 && m[1, 2] == 1 && m[2, 1] == 3"))[1])
    t("R matrix -> numpy", lambda: np.array_equal(s.run("matrix(1:6, 2, 3)"), np.array([[1, 3, 5], [2, 4, 6]])))
    t("R package call (stats::lm)", lambda: abs(float(s.run("unname(coef(lm(mpg ~ wt, data = mtcars))[2])")) + 5.344) < 0.01)
    t("rich object proxy + method", lambda: len(s.run("lm(mpg ~ wt, data = mtcars)").coef()) == 2)
    t("plot transfer", lambda: bool(s.eval("plot(1:10)").plots))
    t("Arrow transfer", lambda: bool(s.capabilities.get("arrow")) and (lambda big: (s.assign("big", big), s.get("big").equals(big))[1])(pd.DataFrame({"a": np.arange(6000), "b": np.random.rand(6000)})))
    t("Unicode / Arabic / French names", lambda: (s.assign("u", pd.DataFrame({"ville é": ["Paris"], "مدينة": ["الجزائر"]})), s.get("u").columns.tolist() == ["ville é", "مدينة"])[1])
    t("Python -> R -> Python function callback", lambda: (s.assign("f", lambda a, b=1: a + b), s.run("f(2, b = 3)") == 5)[1])
    t("Jupyter integration", _has_ipython)
    if full:
        try:
            import scipy.sparse as sp
            m = sp.random(50, 40, density=0.1, format="csc", random_state=1)
            t("sparse matrix (Matrix)", lambda: (s.assign("sm", m), s.run("if (inherits(sm, 'dgCMatrix')) Matrix::nnzero(sm) else -1") == m.nnz and (s.get("sm") != m).nnz == 0)[1])
        except ImportError:
            pass
        try:
            import networkx as nx
            g = nx.MultiDiGraph([("a", "b"), ("a", "b"), ("b", "c")])
            t("network (igraph, parallel edges)", lambda: (s.assign("g", g), s.run("igraph::ecount(g) == 3 && igraph::is_directed(g)"))[1])
        except ImportError:
            pass
        try:
            import shapely
            from ..data.spatial import spatial
            gdf = spatial(pd.DataFrame({"n": [1], "x": [2.0], "y": [48.0]}), lon="x", lat="y", crs="EPSG:4326")
            t("spatial (sf, CRS)", lambda: (s.assign("g2", gdf), s.run("inherits(g2, 'sf') && sf::st_crs(g2)$epsg == 4326"))[1])
        except ImportError:
            pass
        try:
            import xarray as xr
            da = xr.DataArray(np.arange(6.).reshape(2, 3), dims=("a", "b"), coords={"a": ["x", "y"], "b": [1, 2, 3]}, name="v")
            t("xarray (labelled array)", lambda: (s.assign("da", da), s.run("identical(dim(da), c(2L, 3L)) && dimnames(da)[[1]][2] == 'y'"))[1])
        except ImportError:
            pass
        from ..data.survival import survival
        sv = survival(pd.DataFrame({"t": [1.0, 2.0, 3.0], "d": [1, 0, 1]}), time="t", event="d")
        t("survival (Surv)", lambda: (s.assign("sv", sv), s.run("inherits(sv, 'Surv')"))[1])
        from ..data.survey import labelled
        lf = labelled(pd.DataFrame({"sex": [1, 2]}), value_labels={"sex": {1: "male", 2: "female"}}, variable_labels={"sex": "Sex"})
        t("labelled (haven)", lambda: (s.assign("lf", lf), s.run("inherits(lf$sex, 'haven_labelled') && attr(lf$sex, 'label') == 'Sex'"))[1])
        t("database (DuckDB shared relation)", _db_test(s))
    if own:
        s.close()
    if print_it:
        print(rep.render())
    return rep


def _db_test(s: Any) -> Any:
    def run() -> bool:
        import tempfile
        import pandas as pd
        from ..database.api import connect
        path = os.path.join(tempfile.mkdtemp(prefix="rpython-db-"), "t.duckdb")
        db = connect(f"duckdb:///{path}")
        db.write("tbl", pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]}))
        rel = db.table("tbl").filter("a >= ?", [2])
        rel.schema(); rel.count()          # cache metadata, then release the writer lock
        db.close()
        s.assign("rel", rel)                # R opens the same file read-only
        n = s.run("nrow(dplyr::collect(rel))") if s.capabilities.get("packages", {}).get("dbplyr") else s.run("nrow(DBI::dbGetQuery(rel$con, rel$sql))")
        return int(n) == 2
    return run


def fix(dry_run: bool = False, print_it: bool = True) -> list[str]:
    """Safe automatic repairs: install missing core R packages (CRAN) and pyarrow (pip). Never touches system config."""
    actions: list[str] = []
    py = detect_python()
    if not py.packages.get("pyarrow"):
        actions.append(f"{sys.executable} -m pip install pyarrow")
    r = find_r()
    if r is None:
        actions.append("install R (https://cran.r-project.org/) -- cannot be automated safely")
    else:
        from ..runtime.r_session import RSession
        try:
            with RSession(timeout=120) as s:
                pk = s.capabilities.get("packages") or {}
                missing = [p for p in ("jsonlite", "arrow", "data.table", "Matrix", "xts", "zoo", "haven", "survival", "sf", "igraph") if not pk.get(p)]
                if missing and not dry_run:
                    s.install(*missing, timeout=3600)
                actions += [f"R: install.packages('{m}')" for m in missing]
        except Exception as e:  # noqa: BLE001
            actions.append(f"R worker failed ({e}); in R run: install.packages('jsonlite')")
    if not dry_run:
        for a in actions:
            if a.startswith(sys.executable):
                import subprocess
                subprocess.run(a.split(), check=False)
    if print_it:
        print("\n".join(("[dry run] " if dry_run else "") + a for a in actions) if actions else "Nothing to fix " + OK)
    return actions


def restore(lockfile: str = "rpython.lock", print_it: bool = True) -> dict[str, Any]:
    """Restore the environment described by ``rpython.lock`` (see :mod:`rpython.env.lock`)."""
    from ..env.lock import restore as _restore
    return _restore(lockfile, print_it=print_it)
