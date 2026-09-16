"""Environment detection: find R and Python runtimes deterministically.

Rules (MASTER_PROMPT section 22): never pick randomly among several R
installations.  Resolution order:

1. ``rp.config(r_home=...)`` / ``RPYTHON_R_HOME`` environment variable
2. ``R_HOME`` environment variable
3. ``Rscript`` on ``PATH``
4. Windows registry (``HKLM/HKCU\\SOFTWARE\\R-core\\R``)
5. well-known install locations

When several candidates exist and none was chosen explicitly, the
*highest version* is used and all candidates are reported by ``doctor()``.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RInstall:
    home: str
    rscript: str
    version: str = ""
    arch: str = ""
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _rscript_in(home: str) -> str | None:
    cands = [os.path.join(home, "bin", "Rscript.exe"), os.path.join(home, "bin", "x64", "Rscript.exe"),
             os.path.join(home, "bin", "Rscript")]
    for c in cands:
        if os.path.isfile(c):
            return c
    return None


def _version_of(rscript: str) -> str:
    try:
        out = subprocess.run([rscript, "--version"], capture_output=True, text=True, timeout=20)
        txt = (out.stdout or "") + (out.stderr or "")
        for tok in txt.replace("(", " ").split():
            if tok[0].isdigit() and tok.count(".") >= 1:
                return tok
    except Exception:
        pass
    return ""


def _from_registry() -> list[str]:
    homes: list[str] = []
    if sys.platform != "win32":
        return homes
    try:
        import winreg
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for key in (r"SOFTWARE\R-core\R", r"SOFTWARE\R-core\R64", r"SOFTWARE\WOW6432Node\R-core\R"):
                try:
                    with winreg.OpenKey(root, key) as k:
                        i = 0
                        while True:
                            try:
                                sub = winreg.EnumKey(k, i)
                                i += 1
                                with winreg.OpenKey(k, sub) as sk:
                                    p, _ = winreg.QueryValueEx(sk, "InstallPath")
                                    homes.append(p)
                            except OSError:
                                break
                        try:
                            p, _ = winreg.QueryValueEx(k, "InstallPath")
                            homes.append(p)
                        except OSError:
                            pass
                except OSError:
                    continue
    except Exception:
        pass
    return homes


def _well_known() -> list[str]:
    out: list[str] = []
    if sys.platform == "win32":
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", ""),
                     os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
            root = os.path.join(base, "R") if base else ""
            if root and os.path.isdir(root):
                out += [os.path.join(root, d) for d in os.listdir(root) if d.startswith("R-")]
    elif sys.platform == "darwin":
        out += ["/Library/Frameworks/R.framework/Resources", "/opt/homebrew/opt/r", "/usr/local/opt/r"]
    else:
        out += ["/usr/lib/R", "/usr/local/lib/R", "/opt/R/current", "/usr/lib64/R"]
    return [p for p in out if os.path.isdir(p)]


def _vtuple(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in v.split(".")[:3])
    except Exception:
        return (0,)


def find_r_candidates() -> list[RInstall]:
    seen: dict[str, RInstall] = {}

    def add(home: str, source: str) -> None:
        if not home:
            return
        home = os.path.normpath(home)
        rs = _rscript_in(home)
        if rs is None:
            return
        key = os.path.normcase(home)
        if key not in seen:
            seen[key] = RInstall(home, rs, source=source)

    from ..config import get_config
    add(get_config().r_home or "", "rp.config(r_home)")
    add(os.environ.get("RPYTHON_R_HOME", ""), "RPYTHON_R_HOME")
    add(os.environ.get("R_HOME", ""), "R_HOME")
    rs = shutil.which("Rscript")
    if rs:
        add(os.path.dirname(os.path.dirname(os.path.realpath(rs))), "PATH")
        # Windows: bin/x64/Rscript.exe
        add(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(rs)))), "PATH")
    for h in _from_registry():
        add(h, "registry")
    for h in _well_known():
        add(h, "well-known location")
    out = list(seen.values())
    for r in out:
        r.version = _version_of(r.rscript)
        r.arch = platform.machine()
    return out


def find_r() -> RInstall | None:
    """Deterministic choice: explicit config > env > PATH > highest registry/known version."""
    cands = find_r_candidates()
    if not cands:
        return None
    for src in ("rp.config(r_home)", "RPYTHON_R_HOME", "R_HOME", "PATH"):
        for c in cands:
            if c.source == src:
                return c
    return max(cands, key=lambda c: _vtuple(c.version))


@dataclass
class PythonEnv:
    executable: str = sys.executable
    version: str = platform.python_version()
    prefix: str = sys.prefix
    kind: str = "system"
    manager: str | None = None
    in_jupyter: bool = False
    in_colab: bool = False
    in_vscode: bool = False
    in_docker: bool = False
    packages: dict[str, str | None] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def detect_python() -> PythonEnv:
    env = PythonEnv()
    if sys.prefix != getattr(sys, "base_prefix", sys.prefix):
        env.kind = "venv"
    if os.environ.get("CONDA_PREFIX"):
        env.kind, env.manager = "conda", "conda"
    if os.environ.get("VIRTUAL_ENV") and os.environ.get("UV"):
        env.manager = "uv"
    if os.path.exists(os.path.join(sys.prefix, "uv.lock")) or os.environ.get("UV_PROJECT_ENVIRONMENT"):
        env.manager = env.manager or "uv"
    if os.environ.get("POETRY_ACTIVE"):
        env.manager = "poetry"
    env.in_colab = "google.colab" in sys.modules or os.path.exists("/content") and os.environ.get("COLAB_RELEASE_TAG") is not None
    try:
        from IPython import get_ipython  # type: ignore
        ip = get_ipython()
        env.in_jupyter = ip is not None and "IPKernelApp" in getattr(ip, "config", {})
    except Exception:
        env.in_jupyter = False
    env.in_vscode = os.environ.get("TERM_PROGRAM") == "vscode" or "VSCODE_PID" in os.environ
    env.in_docker = os.path.exists("/.dockerenv")
    import importlib.metadata as md
    for p in ("numpy", "pandas", "pyarrow", "polars", "scipy", "xarray", "networkx", "shapely", "geopandas",
              "duckdb", "sqlalchemy", "torch", "pyreadstat", "ipython", "matplotlib"):
        try:
            env.packages[p] = md.version(p)
        except md.PackageNotFoundError:
            env.packages[p] = None
    return env
