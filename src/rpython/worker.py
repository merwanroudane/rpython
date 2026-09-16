"""Python worker: the mirror image of the R worker, used when **R drives
Python** (``library(rpython); py <- python()``).

Transport: a TCP socket (R connects with ``socketConnection``) or stdio.
Same message shapes as the R worker so both directions share one
protocol; Python objects that have no R representation stay here behind
handles (:data:`~rpython.data.custom.OBJECT_STORE`).

Run with ``python -m rpython.worker --port 0`` (prints the chosen port).
"""
from __future__ import annotations

import contextlib
import importlib
import io
import json
import socket
import subprocess
import sys
import traceback
import warnings
from dataclasses import dataclass
from typing import Any

from .data.context import Context
from .data.convert import to_envelope, from_envelope, _json_default
from .data.custom import OBJECT_STORE, proxy_encode, introspect
from .data.semantic import Runtime

PROTO = "@RPX@"


@dataclass
class EvalResult:
    value: Any
    stdout: str
    warnings: list[str]
    error: str | None
    traceback: str | None
    plots: list[str]


class _Namespace(dict):
    pass


_USER_NS: dict[str, Any] = {"__name__": "__rpython__"}


def python_eval(code: str, session: Any = None, ns: dict[str, Any] | None = None, plots: bool = True) -> EvalResult:
    """Execute Python code; the last expression's value is returned (like a notebook cell)."""
    import ast
    ns = _USER_NS if ns is None else ns
    buf = io.StringIO()
    caught: list[str] = []
    value: Any = None
    err = tb = None
    plot_files: list[str] = []
    try:
        tree = ast.parse(code, mode="exec")
        last_expr = None
        if tree.body and isinstance(tree.body[-1], ast.Expr):
            last_expr = ast.Expression(tree.body.pop().value)
        with contextlib.redirect_stdout(buf), warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            exec(compile(tree, "<rpython>", "exec"), ns)
            if last_expr is not None:
                value = eval(compile(last_expr, "<rpython>", "eval"), ns)
            caught = [str(x.message) for x in w]
        if plots:
            plot_files = _collect_matplotlib()
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
        tb = traceback.format_exc()
    return EvalResult(value, buf.getvalue(), caught, err, tb, plot_files)


def _collect_matplotlib() -> list[str]:
    try:
        import matplotlib
        import matplotlib.pyplot as plt
    except Exception:
        return []
    out = []
    import tempfile
    for num in plt.get_fignums():
        fig = plt.figure(num)
        if fig.axes:
            p = tempfile.mktemp(prefix="rpython-py-", suffix=".png")
            fig.savefig(p, dpi=110, bbox_inches="tight")
            out.append(p)
    if out:
        plt.close("all")
    return out


class PythonWorker:
    def __init__(self, reader: Any, writer: Any):
        self.reader, self.writer = reader, writer
        self.stop = False
        self.capabilities = {"arrow": _has("pyarrow")}
        self.transfer = "auto"

    # ------------------------------------------------------------------ transport
    def send(self, msg: dict[str, Any]) -> None:
        payload = json.dumps(msg, ensure_ascii=False, default=_json_default).encode("utf-8")
        self.writer.write((PROTO + str(len(payload)) + "\n").encode("ascii") + payload)   # length-prefixed frame
        self.writer.flush()

    def read(self) -> dict[str, Any] | None:
        while True:
            line = self.reader.readline()
            if not line:
                return None
            s = line.decode("utf-8", errors="replace")
            if s.startswith(PROTO):
                return json.loads(s[len(PROTO):])

    def callback(self, msg: dict[str, Any]) -> Any:
        """Ask R (the client) to do something -- e.g. call a method on an R proxy."""
        msg["op"] = "callback"
        self.send(msg)
        while True:
            reply = self.read()
            if reply is None:
                raise RuntimeError("connection to R closed during callback")
            if reply.get("op") == "callback_result":
                if reply.get("ok"):
                    return from_envelope(reply.get("value"), self._ctx_in())
                raise RuntimeError(f"R error: {reply.get('error')}")
            self.handle(reply)

    def _ctx_in(self) -> Context:
        return Context(direction="r->py", target_runtime=Runtime.PYTHON, session=_RClientSession(self))

    def _ctx_out(self) -> Context:
        return Context(direction="py->r", target_runtime=Runtime.R, session=_RClientSession(self), capabilities=self.capabilities)

    def enc(self, value: Any, convert: bool = True) -> dict[str, Any]:
        ctx = self._ctx_out()
        if not convert:
            return proxy_encode(value, ctx)
        return to_envelope(value, ctx)

    def dec(self, env: Any) -> Any:
        return from_envelope(env, self._ctx_in())

    # ------------------------------------------------------------------ ops
    def handle(self, req: dict[str, Any]) -> None:
        rid = req.get("id")
        op = req.get("op")
        try:
            res = self._dispatch(op, req)
            res["id"] = rid
            res.setdefault("ok", True)
        except Exception as e:  # noqa: BLE001
            res = {"id": rid, "ok": False, "error": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc(), "runtime": "python"}
        self.send(res)

    def _dispatch(self, op: str, req: dict[str, Any]) -> dict[str, Any]:
        import platform
        if op == "hello":
            self.capabilities["peer_arrow"] = bool(req.get("arrow"))
            self.transfer = req.get("transfer", "auto")
            return {"python_version": platform.python_version(), "executable": sys.executable, "arrow": _has("pyarrow"),
                    "packages": {p: _has(p) for p in ("numpy", "pandas", "pyarrow", "polars", "scipy", "xarray", "networkx", "shapely",
                                                     "geopandas", "sklearn", "statsmodels", "torch", "matplotlib", "duckdb", "sqlalchemy")},
                    "pid": __import__("os").getpid()}
        if op == "eval":
            r = python_eval(req.get("code", ""), plots=not req.get("plots") is False)
            if r.error:
                return {"ok": False, "error": r.error, "traceback": r.traceback, "stdout": r.stdout, "warnings": r.warnings, "runtime": "python"}
            return {"value": self.enc(r.value, req.get("convert", True)), "stdout": r.stdout, "warnings": r.warnings, "messages": [],
                    "plots": r.plots, "visible": r.value is not None}
        if op == "assign":
            _USER_NS[req["name"]] = self.dec(req.get("value"))
            return {}
        if op == "get":
            return {"value": self.enc(_USER_NS[req["name"]], req.get("convert", True))}
        if op == "exists":
            return {"value": req["name"] in _USER_NS}
        if op == "import":
            mod = importlib.import_module(req["module"])
            names = [n for n in dir(mod) if not n.startswith("_")]
            return {"handle": OBJECT_STORE.put(mod), "exports": names, "version": getattr(mod, "__version__", "")}
        if op == "getattr":
            obj = OBJECT_STORE.get(req["handle"]) if req.get("handle") else _USER_NS
            if isinstance(obj, dict):
                attr = obj[req["name"]]
            else:
                try:
                    attr = getattr(obj, req["name"])
                except AttributeError:
                    import types
                    if isinstance(obj, types.ModuleType):   # lazy submodule: sklearn.linear_model
                        attr = importlib.import_module(f"{obj.__name__}.{req['name']}")
                    else:
                        raise
            if callable(attr) and not req.get("value"):
                return {"value": {"rpx": 1, "kind": "proxy", "runtime": "python", "handle": OBJECT_STORE.put(attr), "callable": True,
                                  "class": [type(attr).__name__], "module": getattr(attr, "__module__", ""), "methods": [], "attributes": [],
                                  "repr": repr(attr)[:200], "meta": {"source_class": "callable"}}, "callable": True}
            return {"value": self.enc(attr, req.get("convert", True)), "callable": False}
        if op in ("call", "call_method"):
            target = OBJECT_STORE.get(req["handle"]) if req.get("handle") else _resolve(req["fn"])
            if op == "call_method":
                target = getattr(target, req["name"])
            args = [self.dec(a) for a in req.get("args") or []]
            kwargs = {k: self.dec(v) for k, v in (req.get("kwargs") or {}).items()}
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                value = target(*args, **kwargs)
            plots = _collect_matplotlib() if req.get("plots", True) else []
            return {"value": self.enc(value, req.get("convert", True)), "stdout": buf.getvalue(), "warnings": [str(x.message) for x in w],
                    "messages": [], "plots": plots}
        if op == "describe":
            obj = OBJECT_STORE.get(req["handle"])
            return {"value": introspect(obj).to_dict()}
        if op == "convert":
            return {"value": to_envelope(OBJECT_STORE.get(req["handle"]), self._ctx_out())}
        if op == "release":
            OBJECT_STORE.release(req["handle"])
            return {}
        if op == "install":
            pk = list(req.get("packages") or [])
            src = req.get("source", "pip")
            cmd = [sys.executable, "-m", "pip", "install", *pk] if src in ("pip", "pypi", "auto") else [src, "add" if src == "uv" else "install", *pk]
            out = subprocess.run(cmd, capture_output=True, text=True)
            ok = out.returncode == 0
            return {"ok": ok, "stdout": out.stdout[-4000:], "error": None if ok else out.stderr[-2000:]}
        if op == "installed":
            return {"value": [p for p in req.get("packages") or [] if _has(p)]}
        if op == "signature":
            import inspect
            fn = OBJECT_STORE.get(req["handle"]) if req.get("handle") else _resolve(req["fn"])
            try:
                sig = inspect.signature(fn)
                params = list(sig.parameters)
                defaults = {k: (repr(v.default) if v.default is not inspect.Parameter.empty else None) for k, v in sig.parameters.items()}
            except (TypeError, ValueError):
                params, defaults = [], {}
            return {"value": {"args": params, "defaults": defaults, "doc": (inspect.getdoc(fn) or "")[:4000]}}
        if op == "ping":
            return {"value": "pong"}
        if op == "shutdown":
            self.stop = True
            return {}
        raise ValueError(f"unknown op {op!r}")

    def serve(self) -> None:
        self.send({"op": "ready", "pid": __import__("os").getpid()})
        while not self.stop:
            req = self.read()
            if req is None:
                break
            self.handle(req)


class _RClientSession:
    """Minimal 'session' so R proxies received by the Python worker can call back into R."""

    def __init__(self, worker: PythonWorker):
        self.worker = worker
        self.alive = True
        self.capabilities = worker.capabilities

    def method(self, handle: str, name: str, *args: Any, **kwargs: Any) -> Any:
        return self.worker.callback({"what": "method", "handle": handle, "method": name,
                                     "args": [self.worker.enc(a) for a in args], "kwargs": {k: self.worker.enc(v) for k, v in kwargs.items()}})

    def field(self, handle: str, name: str, convert: bool = True) -> Any:
        return self.worker.callback({"what": "field", "handle": handle, "name": name})

    def call(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        return self.worker.callback({"what": "call", "fn": fn, "args": [self.worker.enc(a) for a in args],
                                     "kwargs": {k: self.worker.enc(v) for k, v in kwargs.items()}})

    def convert(self, handle: str) -> Any:
        return self.worker.callback({"what": "convert", "handle": handle})

    def release(self, handle: str) -> None:
        with contextlib.suppress(Exception):
            self.worker.callback({"what": "release", "handle": handle})

    def save_rds(self, obj: Any, path: str) -> str:
        return self.worker.callback({"what": "save", "handle": obj.handle, "path": path})

    def save_plot(self, handle: str, path: str, width: float = 8, height: float = 6, dpi: int = 150) -> str:
        return self.worker.callback({"what": "plot_save", "handle": handle, "path": path, "width": width, "height": height, "dpi": dpi})


def _resolve(spec: str) -> Any:
    if spec in _USER_NS:
        return _USER_NS[spec]
    mod, _, attr = spec.rpartition(".")
    if not mod:
        import builtins
        return getattr(builtins, attr)
    m = importlib.import_module(mod)
    return getattr(m, attr)


def _has(pkg: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(pkg) is not None


def main(argv: list[str] | None = None) -> None:
    import argparse
    ap = argparse.ArgumentParser(description="RPython Python worker")
    ap.add_argument("--port", type=int, default=None, help="listen on this TCP port (0 = choose) and print it")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--connect", type=int, default=None, help="connect to an R-side listener on this port instead")
    a = ap.parse_args(argv)
    if a.port is None and a.connect is None:
        w = PythonWorker(sys.stdin.buffer, sys.stdout.buffer)
        w.serve()
        return
    if a.connect is not None:
        s = socket.create_connection((a.host, a.connect))
    else:
        srv = socket.socket()
        srv.bind((a.host, a.port))
        srv.listen(1)
        print(f"RPYTHON_PORT={srv.getsockname()[1]}", flush=True)
        s, _ = srv.accept()
    r = s.makefile("rb")
    wfile = s.makefile("wb")
    PythonWorker(r, wfile).serve()
    s.close()


if __name__ == "__main__":
    main()
