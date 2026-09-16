"""``rpython.lock`` -- unified reproducibility manifest (design spec §23).

It orchestrates rather than replaces native lock systems: it records the
Python interpreter + key packages (and points at pyproject/uv.lock/
requirements when present) and the R version + package versions (and
points at renv.lock when present).  ``restore()`` re-installs what is
missing, reporting each step.  No secrets, no absolute user paths beyond
the R home.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import platform
import sys
from typing import Any

from .detect import detect_python, find_r


def lock(path: str = "rpython.lock", r_packages: list[str] | None = None, print_it: bool = True) -> dict[str, Any]:
    py = detect_python()
    data: dict[str, Any] = {
        "rpython_lock": 1,
        "created": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine()},
        "python": {"version": py.version, "kind": py.kind, "manager": py.manager, "packages": {k: v for k, v in py.packages.items() if v},
                   "native_lock": _first_existing(["uv.lock", "poetry.lock", "requirements.txt", "pyproject.toml", "environment.yml"])},
        "r": None,
        "backend": {"transfer": "auto"},
    }
    r = find_r()
    if r is not None:
        entry: dict[str, Any] = {"version": r.version, "home": r.home, "native_lock": _first_existing(["renv.lock", "DESCRIPTION"]), "packages": {}}
        try:
            from ..runtime.r_session import RSession
            with RSession(timeout=120) as s:
                want = r_packages or list(s.capabilities.get("packages", {}).keys())
                versions = s.run("local({ ip <- utils::installed.packages(); as.list(setNames(ip[, 'Version'], rownames(ip))) })")
                entry["packages"] = {p: versions[p] for p in want if p in versions}
                if not r_packages:
                    entry["packages"].update({p: versions[p] for p in s.packages_loaded if p in versions})
        except Exception as e:  # noqa: BLE001
            entry["error"] = str(e)
        data["r"] = entry
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    if print_it:
        print(f"wrote {path}: Python {py.version} ({len(data['python']['packages'])} packages), "
              f"R {data['r']['version'] if data['r'] else 'n/a'} ({len(data['r']['packages']) if data['r'] else 0} packages)")
    return data


def _first_existing(names: list[str]) -> str | None:
    for n in names:
        if os.path.exists(n):
            return n
    return None


def restore(path: str = "rpython.lock", print_it: bool = True, install: bool = True) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    report: dict[str, Any] = {"python_missing": [], "r_missing": [], "actions": []}
    py = detect_python()
    for pkg, ver in (data.get("python", {}).get("packages") or {}).items():
        if not py.packages.get(pkg):
            report["python_missing"].append(f"{pkg}=={ver}")
    if report["python_missing"] and install:
        import subprocess
        cmd = [sys.executable, "-m", "pip", "install", *report["python_missing"]]
        report["actions"].append(" ".join(cmd))
        subprocess.run(cmd, check=False)
    r = data.get("r") or {}
    if r.get("packages"):
        try:
            from ..runtime.r_session import RSession
            with RSession(timeout=3600) as s:
                have = s.installed(*r["packages"].keys())
                report["r_missing"] = [p for p, ok in have.items() if not ok]
                if report["r_missing"] and install:
                    report["actions"].append(f"R install.packages({report['r_missing']})")
                    s.install(*report["r_missing"])
        except Exception as e:  # noqa: BLE001
            report["error"] = str(e)
    if print_it:
        print(json.dumps(report, indent=1))
    return report
