"""Release readiness report from *real* test runs (design spec §55).

Runs pytest with JUnit output, the R testthat suite, and R CMD check, then
writes RELEASE_REPORT.md with per-subsystem passed/total counts.  Counts are
read from the JUnit XML; nothing is typed by hand.

Run: python tools/release_report.py
"""
from __future__ import annotations

import datetime as dt
import glob
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SUBSYSTEMS = {
    "Primitives & collections": ["tests/unit/test_primitives.py", "tests/unit/test_collections_arrays.py::test_collection", "tests/property/test_property_roundtrip.py::test_nested"],
    "Arrays & sparse": ["tests/unit/test_collections_arrays.py::test_ndarray", "tests/unit/test_collections_arrays.py::test_masked", "tests/unit/test_collections_arrays.py::test_dtype",
                        "tests/unit/test_collections_arrays.py::test_memory", "tests/unit/test_collections_arrays.py::test_uint64", "tests/unit/test_collections_arrays.py::test_unicode",
                        "tests/unit/test_collections_arrays.py::test_torch", "tests/roundtrip/test_families_python.py::test_sparse", "tests/property/test_property_roundtrip.py::test_arrays",
                        "tests/property/test_property_roundtrip.py::test_random_sparse"],
    "Tabular (pandas/polars/arrow)": ["tests/roundtrip/test_families_python.py::test_dataframe", "tests/roundtrip/test_families_python.py::test_index", "tests/roundtrip/test_families_python.py::test_edge",
                                      "tests/roundtrip/test_families_python.py::test_series", "tests/roundtrip/test_families_python.py::test_polars", "tests/roundtrip/test_families_python.py::test_arrow",
                                      "tests/property/test_property_roundtrip.py::test_typed", "tests/property/test_property_roundtrip.py::test_unicode", "tests/property/test_property_roundtrip.py::test_categorical"],
    "Time series": ["tests/roundtrip/test_families_python.py::test_timeseries", "tests/property/test_property_roundtrip.py::test_time_series"],
    "Panel / cross-section": ["tests/roundtrip/test_families_python.py::test_panel", "tests/roundtrip/test_families_python.py::test_repeated", "tests/property/test_property_roundtrip.py::test_random_panels"],
    "Survey / survival": ["tests/roundtrip/test_families_python.py::test_labelled", "tests/roundtrip/test_families_python.py::test_survival"],
    "Spatial / raster / spatiotemporal": ["tests/roundtrip/test_families_python.py::test_spatial", "tests/roundtrip/test_families_python.py::test_spatiotemporal", "tests/roundtrip/test_families_python.py::test_raster"],
    "Networks": ["tests/roundtrip/test_families_python.py::test_network", "tests/property/test_property_roundtrip.py::test_random_graphs"],
    "Text / media / scientific / economics": ["tests/roundtrip/test_families_python.py::test_text", "tests/roundtrip/test_families_python.py::test_media", "tests/roundtrip/test_families_python.py::test_xarray",
                                              "tests/roundtrip/test_families_python.py::test_economics"],
    "Proxies & lazy objects": ["tests/roundtrip/test_families_python.py::test_unknown", "tests/roundtrip/test_families_python.py::test_lazy", "tests/roundtrip/test_families_python.py::test_autodetection"],
    "R runtime & Python -> R -> Python (live)": ["tests/integration/test_r_session.py"],
    "R -> Python (live)": ["tests/integration/test_r_drives_python.py"],
    "Economics end-to-end (live)": ["tests/economics/"],
    "Databases": ["tests/database/"],
    "Persistence / edge cases / CLI": ["tests/edge_cases/"],
    "Documentation examples": ["tests/docs/"],
}


def run_pytest(junit: str) -> int:
    cmd = [sys.executable, "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider", f"--junitxml={junit}"]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run(cmd, cwd=ROOT, env=env).returncode


def parse_junit(junit: str) -> list[tuple[str, str, str]]:
    """(nodeid, outcome, subsystem-key) for every test case."""
    out = []
    for tc in ET.parse(junit).getroot().iter("testcase"):
        cls = tc.get("classname", "").replace(".", "/")
        name = tc.get("name", "")
        nodeid = f"{cls}.py::{name}" if cls else name
        outcome = "passed"
        if tc.find("failure") is not None or tc.find("error") is not None:
            outcome = "failed"
        elif tc.find("skipped") is not None:
            outcome = "skipped"
        out.append((nodeid, outcome, name))
    return out


def classify(nodeid: str) -> str:
    for sub, patterns in SUBSYSTEMS.items():
        for p in patterns:
            if p.endswith("/") and p.rstrip("/") in nodeid:
                return sub
            if "::" in p:
                f, prefix = p.split("::")
                if f in nodeid and ("::" + prefix) in nodeid:
                    return sub
            elif p in nodeid:
                return sub
    return "Other"


def run_r_tests() -> tuple[str, str]:
    from rpython.env.detect import find_r
    inst = find_r()
    if inst is None:
        return ("R package (testthat)", "R not found")
    code = ('suppressMessages(library(testthat)); res <- as.data.frame(testthat::test_dir("r-package/tests/testthat", package = "rpython", reporter = "silent", stop_on_failure = FALSE));'
            'cat(sum(res$passed), sum(res$failed) + sum(res$error), sum(res$skipped), "\\n")')
    env = dict(os.environ, RPYTHON_PYTHON=sys.executable)
    out = subprocess.run([inst.rscript, "-e", code], cwd=ROOT, capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    m = re.findall(r"(\d+) (\d+) (\d+)\s*$", out.stdout.strip())
    if not m:
        return ("R package (testthat)", "could not run: " + (out.stderr or out.stdout)[-300:])
    p, f, s = map(int, m[-1])
    return ("R package (testthat)", f"{p} / {p + f} expectations passed, {s} skipped -> {'PASS' if f == 0 else 'FAIL'}")


def run_r_check() -> tuple[str, str]:
    from rpython.env.detect import find_r
    inst = find_r()
    if inst is None:
        return ("R CMD check", "R not found")
    rbin = os.path.join(os.path.dirname(inst.rscript), "R.exe" if os.name == "nt" else "R")
    tmp = tempfile.mkdtemp(prefix="rpython-check-")
    env = dict(os.environ, RPYTHON_PYTHON=sys.executable, _R_CHECK_FORCE_SUGGESTS_="false")
    subprocess.run([rbin, "CMD", "build", "--no-build-vignettes", os.path.join(ROOT, "r-package")], cwd=tmp, capture_output=True, env=env)
    tars = glob.glob(os.path.join(tmp, "rpython_*.tar.gz"))
    if not tars:
        return ("R CMD check", "build failed")
    out = subprocess.run([rbin, "CMD", "check", "--no-manual", tars[0]], cwd=tmp, capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    status = re.findall(r"Status: (.*)", out.stdout + out.stderr)
    shutil.rmtree(tmp, ignore_errors=True)
    return ("R CMD check", status[-1].strip() if status else "no status line")


def main() -> None:
    junit = os.path.join(tempfile.gettempdir(), "rpython-junit.xml")
    rc = run_pytest(junit)
    cases = parse_junit(junit)
    table: dict[str, list[int]] = {k: [0, 0, 0] for k in list(SUBSYSTEMS) + ["Other"]}
    for nodeid, outcome, _ in cases:
        sub = classify(nodeid)
        table[sub][{"passed": 0, "failed": 1, "skipped": 2}[outcome]] += 1
    r_tests = run_r_tests()
    r_check = run_r_check()
    import importlib.metadata as md
    lines = ["# Release readiness report", "",
             f"Generated {dt.datetime.now().isoformat(timespec='minutes')} by `python tools/release_report.py` on {platform.platform()}, "
             f"Python {platform.python_version()}, pandas {md.version('pandas')}, numpy {md.version('numpy')}.", "",
             "Counts come from the JUnit output of the full pytest run; nothing here is typed by hand.", "",
             "| Subsystem | Passed / Total | Skipped | Status |", "|---|---|---|---|"]
    total_p = total_t = 0
    for sub, (p, f, s) in table.items():
        if p + f + s == 0:
            continue
        status = "PASS" if f == 0 else "FAIL"
        lines.append(f"| {sub} | {p} / {p + f} | {s} | {status} |")
        total_p += p
        total_t += p + f
    lines.append(f"| **All Python tests** | **{total_p} / {total_t}** | | **{'PASS' if total_p == total_t else 'FAIL'}** |")
    lines.append(f"| {r_tests[0]} | {r_tests[1]} | | |")
    lines.append(f"| {r_check[0]} | {r_check[1]} | | |")
    lines += ["", "## Limitations recorded", "",
              "* Vendor databases other than SQLite/DuckDB/Parquet are interface-tested with fakes, not live (see `rpython catalog`).",
              "* R `ts` objects with frequencies other than 1/4/12 decode to a numeric time index.",
              "* Bioinformatics / chemistry / phylogenetics objects use the generic proxy path (adapters can be registered).",
              "* Embedded bridges have lower per-call latency; RPython uses a separate worker process by design.", ""]
    out = os.path.join(ROOT, "RELEASE_REPORT.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n".join(lines))
    sys.exit(0 if rc == 0 else 1)


if __name__ == "__main__":
    main()
