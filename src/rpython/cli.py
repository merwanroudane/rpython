"""Command-line interface (design spec §42).

    rpython doctor            environment report
    rpython check             quick readiness check
    rpython self-test [--full]
    rpython fix [--dry-run]
    rpython env [--json]      detected Python / R runtimes
    rpython packages          R + Python package availability for the bridge
    rpython install r forecast plm
    rpython install py pandas polars
    rpython lock [path]       write rpython.lock
    rpython restore [path]    restore from rpython.lock
    rpython run -e "1 + 1"    run R code
    rpython worker [--port N] run the Python worker (used by R's python())
    rpython catalog           supported data families and database backends
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any


def _print_json(obj: Any) -> None:
    print(json.dumps(obj, indent=1, default=str, ensure_ascii=False))


def cmd_doctor(a: argparse.Namespace) -> int:
    from .diagnostics.doctor import doctor
    rep = doctor(print_it=not a.json, start_r=not a.no_r)
    if a.json:
        _print_json({"rows": rep.rows, "issues": rep.issues, "fixes": rep.fixes, "data": rep.data})
    return 0 if rep.ok else 1


def cmd_check(a: argparse.Namespace) -> int:
    from .diagnostics.doctor import check
    return 0 if check() else 1


def cmd_self_test(a: argparse.Namespace) -> int:
    from .diagnostics.doctor import self_test
    rep = self_test(full=a.full)
    return 0 if rep.ok else 1


def cmd_fix(a: argparse.Namespace) -> int:
    from .diagnostics.doctor import fix
    fix(dry_run=a.dry_run)
    return 0


def cmd_env(a: argparse.Namespace) -> int:
    from .env.detect import detect_python, find_r_candidates, find_r
    py = detect_python()
    cands = find_r_candidates()
    chosen = find_r()
    data = {"python": py.to_dict(), "r_candidates": [c.to_dict() for c in cands], "r_selected": chosen.to_dict() if chosen else None}
    if a.json:
        _print_json(data)
    else:
        print(f"Python {py.version}  {py.executable}  [{py.kind}]")
        for c in cands:
            print(f"R {c.version}  {c.home}  [{c.source}]" + ("  <- selected" if chosen and c.home == chosen.home else ""))
        if not cands:
            print("R: not found")
    return 0


def cmd_packages(a: argparse.Namespace) -> int:
    from .env.detect import detect_python
    py = detect_python()
    print("Python:")
    for k, v in py.packages.items():
        print(f"  {k:12s} {v or '-'}")
    try:
        from .runtime.r_session import RSession
        with RSession(timeout=120) as s:
            print(f"R {s.capabilities.get('r_version')}:")
            for k, v in sorted(s.capabilities.get("packages", {}).items()):
                print(f"  {k:20s} {'ok' if v else '-'}")
    except Exception as e:  # noqa: BLE001
        print(f"R: unavailable ({e})")
    return 0


def cmd_install(a: argparse.Namespace) -> int:
    if a.runtime == "r":
        from .runtime.r_session import RSession
        with RSession(timeout=3600) as s:
            s.install(*a.packages, source=a.source)
        print("installed:", ", ".join(a.packages))
        return 0
    import subprocess
    cmd = [sys.executable, "-m", "pip", "install", *a.packages] if a.source in ("auto", "pip", "pypi") else [a.source, "add" if a.source == "uv" else "install", *a.packages]
    return subprocess.run(cmd).returncode


def cmd_lock(a: argparse.Namespace) -> int:
    from .env.lock import lock
    lock(a.path)
    return 0


def cmd_restore(a: argparse.Namespace) -> int:
    from .env.lock import restore
    restore(a.path)
    return 0


def cmd_run(a: argparse.Namespace) -> int:
    from .runtime.r_session import RSession
    code = a.expr if a.expr else open(a.file, encoding="utf-8").read()
    with RSession(timeout=None) as s:
        res = s.eval(code)
        if res.stdout:
            print(res.stdout)
        for w in res.warnings:
            print("Warning:", w, file=sys.stderr)
        if res.visible and res.value is not None:
            print(res.value)
        for p in res.plots:
            print("plot:", p.path)
    return 0


def cmd_worker(a: argparse.Namespace) -> int:
    from .worker import main as worker_main
    argv = []
    if a.port is not None:
        argv += ["--port", str(a.port)]
    if a.connect is not None:
        argv += ["--connect", str(a.connect)]
    worker_main(argv)
    return 0


def cmd_catalog(a: argparse.Namespace) -> int:
    from .data.convert import ensure_adapters
    from .data.registry import REGISTRY
    from .database import registry as dbreg
    ensure_adapters()
    if a.json:
        _print_json({"families": [{"family": e.adapter.family, "kinds": list(e.adapter.kinds), "tier": e.adapter.tier.value,
                                   "requires": list(e.adapter.requires), "r_requires": list(e.adapter.r_requires),
                                   "available": e.adapter.available(), "tested": e.tested, "limitations": list(e.limitations)}
                                  for e in REGISTRY.entries()],
                     "databases": dbreg.catalog(), "compatibility": __import__("rpython.compatibility", fromlist=["registry"]).registry()})
        return 0
    print("Object families (detection order):")
    for e in REGISTRY.entries():
        ad = e.adapter
        print(f"  {ad.family:16s} kinds={','.join(ad.kinds):40s} {ad.tier.value.split('.')[0]}  py={','.join(ad.requires) or '-'}  R={','.join(ad.r_requires) or '-'}  {'available' if ad.available() else 'missing deps'}")
    print("\nDatabase backends:")
    for c in dbreg.catalog():
        print(f"  {c['backend']:14s} {c['category']:11s} py={','.join(c['python_requires']) or 'stdlib':22s} R={c['r_package'] or '-':12s} live-tested={c['tested_live']}")
    from .compatibility import registry as compat_registry
    print("\nCompatibility registry (packaged):")
    for key, e in compat_registry().items():
        print(f"  {key:22s} tested={','.join(e.get('tested_versions') or []) or '-':18s} {str(e.get('preferred_path', ''))[:70]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="rpython", description="RPython: R and Python, one seamless research workspace")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("doctor", help="environment report"); p.add_argument("--json", action="store_true"); p.add_argument("--no-r", action="store_true"); p.set_defaults(fn=cmd_doctor)
    p = sub.add_parser("check", help="quick readiness check"); p.set_defaults(fn=cmd_check)
    p = sub.add_parser("self-test", help="interoperability self-test"); p.add_argument("--full", action="store_true"); p.set_defaults(fn=cmd_self_test)
    p = sub.add_parser("fix", help="safe automatic repairs"); p.add_argument("--dry-run", action="store_true"); p.set_defaults(fn=cmd_fix)
    p = sub.add_parser("env", help="detected runtimes"); p.add_argument("--json", action="store_true"); p.set_defaults(fn=cmd_env)
    p = sub.add_parser("packages", help="package availability"); p.set_defaults(fn=cmd_packages)
    p = sub.add_parser("install", help="install R or Python packages"); p.add_argument("runtime", choices=["r", "py"]); p.add_argument("packages", nargs="+")
    p.add_argument("--source", default="auto"); p.set_defaults(fn=cmd_install)
    p = sub.add_parser("lock", help="write rpython.lock"); p.add_argument("path", nargs="?", default="rpython.lock"); p.set_defaults(fn=cmd_lock)
    p = sub.add_parser("restore", help="restore from rpython.lock"); p.add_argument("path", nargs="?", default="rpython.lock"); p.set_defaults(fn=cmd_restore)
    p = sub.add_parser("run", help="run R code"); p.add_argument("-e", "--expr"); p.add_argument("file", nargs="?"); p.set_defaults(fn=cmd_run)
    p = sub.add_parser("worker", help="run the Python worker"); p.add_argument("--port", type=int); p.add_argument("--connect", type=int); p.set_defaults(fn=cmd_worker)
    p = sub.add_parser("catalog", help="supported families and backends"); p.add_argument("--json", action="store_true"); p.set_defaults(fn=cmd_catalog)
    return ap


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    a = build_parser().parse_args(argv)
    return int(a.fn(a) or 0)


if __name__ == "__main__":
    sys.exit(main())
