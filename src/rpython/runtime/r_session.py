"""Persistent, isolated R worker session (MASTER_PROMPT sections 7, 27-29).

The R runtime always lives in its own process (``Rscript`` running the
companion package's ``rpython_worker()``), so a crashing native R package
cannot take the Python kernel down.  Objects cross the boundary as
portable envelopes (JSON + Arrow IPC files); rich R objects stay in R
behind :class:`~rpython.proxy.r_object.RObjectProxy`.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from typing import Any

from ..config import get_config
from ..data.context import Context, ConversionError
from ..data.convert import to_envelope, from_envelope, _json_default
from ..data.custom import OBJECT_STORE
from ..data.semantic import Runtime
from ..env.detect import find_r, RInstall
from ..explain import record_plan
from ..results.result import Result, RError

PROTO = "@RPX@"


def r_source_dir() -> str:
    """Directory holding the R companion sources (bundled copy or dev checkout)."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bundled = os.path.join(here, "r")
    if os.path.isdir(bundled) and any(f.endswith(".R") for f in os.listdir(bundled)):
        return bundled
    dev = os.path.join(os.path.dirname(os.path.dirname(here)), "r-package", "R")
    if os.path.isdir(dev):
        return dev
    raise RuntimeError("R companion sources not found (expected src/rpython/r/*.R)")


class RSession:
    """A live R process.  Create with ``rp.R()``.

    Parameters
    ----------
    r_home : explicit R installation directory (else autodetected)
    timeout : default seconds to wait for a single R call (None = forever)
    safe : kept for API symmetry; the worker is *always* a separate process
    """

    def __init__(self, r_home: str | None = None, timeout: float | None = None, safe: bool = True,
                 workdir: str | None = None, autostart: bool = True):
        self.install: RInstall | None = None
        self._r_home = r_home
        self.timeout = timeout
        self.safe = safe
        self.workdir = workdir
        self.proc: subprocess.Popen | None = None
        self.capabilities: dict[str, Any] = {}
        self.stray: list[str] = []
        self._stderr: list[str] = []
        self._lock = threading.RLock()
        self._id = 0
        self.last: Result | None = None
        self.packages_loaded: set[str] = set()
        if autostart:
            self.start()

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> "RSession":
        cfg = get_config()
        home = self._r_home or cfg.r_home
        inst = None
        if home:
            from ..env.detect import _rscript_in, _version_of
            rs = _rscript_in(home)
            if rs is None:
                raise ConversionError(f"No Rscript found under {home}", runtime="r", cause="wrong R home",
                                      fix="pass r_home='C:/Program Files/R/R-4.x.y' or fix R_HOME")
            inst = RInstall(home, rs, _version_of(rs), source="explicit")
        else:
            inst = find_r()
        if inst is None:
            raise ConversionError("R runtime not found", runtime="r", cause="no R installation detected",
                                  fix="install R from https://cran.r-project.org/ or set RPYTHON_R_HOME; run rp.doctor() for details")
        self.install = inst
        src = r_source_dir().replace("\\", "/")
        code = (f"for (f in sort(list.files('{src}', pattern='[.]R$', full.names=TRUE))) source(f, encoding='UTF-8', local=FALSE); "
                "rpython_worker()")
        env = dict(os.environ)
        env.setdefault("R_HOME", inst.home)
        env["RPYTHON_PEER"] = "python"
        env["LANG"] = env.get("LANG") or "en_US.UTF-8"
        self.proc = subprocess.Popen([inst.rscript, "--no-save", "--no-restore", "-e", code], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                     errors="replace", bufsize=1, env=env, cwd=os.getcwd())
        threading.Thread(target=self._drain_stderr, daemon=True).start()
        ready = self._read_message(timeout=120)
        if ready is None or ready.get("op") != "ready":
            raise ConversionError("R worker failed to start", runtime="r", cause="\n".join(self._stderr[-20:]),
                                  fix="run rp.doctor(); check that jsonlite is installed: install.packages('jsonlite')")
        hello = self._request({"op": "hello", "arrow": _has_pyarrow(), "transfer": cfg.transfer,
                               "arrow_threshold_rows": cfg.arrow_threshold_rows, "workdir": self.workdir}, timeout=120)
        self.capabilities = hello
        self.workdir = hello.get("workdir", self.workdir)
        return self

    def _drain_stderr(self) -> None:
        assert self.proc is not None and self.proc.stderr is not None
        for line in self.proc.stderr:
            self._stderr.append(line.rstrip("\n"))
            if len(self._stderr) > 2000:
                del self._stderr[:1000]

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def close(self) -> None:
        if self.proc is None:
            return
        try:
            if self.alive:
                try:
                    self._send({"id": self._next_id(), "op": "shutdown"})
                except Exception:
                    pass
                try:
                    self.proc.wait(timeout=5)
                except Exception:
                    self.proc.kill()
        finally:
            self.proc = None

    def restart(self) -> "RSession":
        self.close()
        return self.start()

    def __enter__(self) -> "RSession":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def __del__(self) -> None:  # pragma: no cover
        try:
            self.close()
        except Exception:
            pass

    # ------------------------------------------------------------------ transport
    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def _send(self, msg: dict[str, Any]) -> None:
        assert self.proc is not None and self.proc.stdin is not None
        payload = json.dumps(msg, ensure_ascii=False, default=_json_default).encode("utf-8")
        frame = (PROTO + str(len(payload)) + "\n").encode("ascii") + payload   # length-prefixed: safe for huge messages
        try:
            self.proc.stdin.buffer.write(frame)
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            raise ConversionError("R worker is not running", runtime="r", cause=str(e),
                                  fix="r.restart()  (stderr tail: " + " | ".join(self._stderr[-5:]) + ")") from e

    def _read_message(self, timeout: float | None = None) -> dict[str, Any] | None:
        assert self.proc is not None and self.proc.stdout is not None
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            if deadline is not None and time.monotonic() > deadline:
                raise TimeoutError(f"R call exceeded {timeout} s")
            line = self.proc.stdout.readline()
            if line == "":
                if not self.alive:
                    return None
                continue
            if line.startswith(PROTO):
                return json.loads(line[len(PROTO):])
            self.stray.append(line.rstrip("\n"))

    def _request(self, msg: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
        with self._lock:
            rid = self._next_id()
            msg["id"] = rid
            self._send(msg)
            while True:
                reply = self._read_message(timeout if timeout is not None else self.timeout)
                if reply is None:
                    raise ConversionError("R worker terminated unexpectedly", runtime="r",
                                          cause="\n".join(self._stderr[-15:]) or "process exited",
                                          fix="the main Python process is intact; call r.restart() and retry. "
                                              "If a specific package crashes R, report it with rp.doctor() output")
                if reply.get("op") == "callback":
                    self._serve_callback(reply)
                    continue
                if reply.get("id") == rid:
                    if reply.get("ok") is False and "error" in reply and msg["op"] != "install":
                        raise RError(reply.get("error", "R error"), call=reply.get("call"), traceback=reply.get("traceback"),
                                     stdout=reply.get("stdout"), warnings=reply.get("warnings") or [],
                                     classes=reply.get("class") or [])
                    return reply
                # a response for another id: should not happen (single-threaded protocol)
                self.stray.append(f"unexpected reply {reply.get('id')}")

    # ------------------------------------------------------------------ callbacks (R -> Python)
    def _serve_callback(self, req: dict[str, Any]) -> None:
        try:
            value = self._do_callback(req)
            if isinstance(value, _CallableMarker):
                env: dict[str, Any] = {"rpx": 1, "kind": "proxy", "runtime": "python", "handle": value.handle,
                                       "callable": True, "class": ["function"], "module": "builtins", "methods": [],
                                       "attributes": [], "repr": "<bound method>", "meta": {"source_class": "function"}}
            else:
                ctx = Context(direction="py->r", target_runtime=Runtime.R, session=self, capabilities=self.capabilities)
                env = to_envelope(value, ctx)
            self._send({"op": "callback_result", "ok": True, "value": env})
        except Exception as e:  # noqa: BLE001
            self._send({"op": "callback_result", "ok": False, "error": f"{type(e).__name__}: {e}"})

    def _do_callback(self, req: dict[str, Any]) -> Any:
        what = req.get("what")
        ctx = Context(direction="r->py", target_runtime=Runtime.PYTHON, session=self)
        if what == "getattr":
            obj = OBJECT_STORE.get(req["handle"])
            attr = getattr(obj, req["name"])
            if callable(attr):
                return _CallableMarker(OBJECT_STORE.put(attr))
            return attr
        if what == "call":
            obj = OBJECT_STORE.get(req["handle"])
            args = [from_envelope(a, ctx) for a in req.get("args") or []]
            kwargs = {k: from_envelope(v, ctx) for k, v in (req.get("kwargs") or {}).items()}
            return obj(*args, **kwargs)
        if what == "call_method":
            obj = OBJECT_STORE.get(req["handle"])
            args = [from_envelope(a, ctx) for a in req.get("args") or []]
            kwargs = {k: from_envelope(v, ctx) for k, v in (req.get("kwargs") or {}).items()}
            return getattr(obj, req["name"])(*args, **kwargs)
        if what == "release":
            OBJECT_STORE.release(req["handle"])
            return None
        if what == "python":
            # R side executing arbitrary Python (R -> Python symmetry from inside an R->Python callback)
            from ..worker import python_eval
            return python_eval(req.get("code", ""), self).value
        raise ValueError(f"unknown callback {what!r}")

    # ------------------------------------------------------------------ conversion helpers
    def _to_r(self, obj: Any, label: str = "") -> dict[str, Any]:
        ctx = Context(direction="py->r", target_runtime=Runtime.R, session=self, capabilities=self.capabilities)
        env = to_envelope(obj, ctx)
        ctx.plan.target = "R"
        record_plan(ctx.plan, label or "python -> R")
        return env

    def _from_r(self, env: Any, label: str = "", convert: bool = True) -> Any:
        ctx = Context(direction="r->py", target_runtime=Runtime.PYTHON, session=self, capabilities=self.capabilities)
        obj = from_envelope(env, ctx)
        record_plan(ctx.plan, label or "R -> python")
        return obj

    # ------------------------------------------------------------------ public API
    def eval(self, code: str, *, convert: bool = True, plots: bool = True, timeout: float | None = None) -> Result:
        """Run R code; return a :class:`Result` (value, stdout, messages, warnings, plots)."""
        reply = self._request({"op": "eval", "code": code, "convert": convert, "plots": plots, "value": True}, timeout=timeout)
        value = self._from_r(reply.get("value"), "R eval -> python")
        res = Result.from_reply(value, reply, session=self, source=code)
        self.last = res
        return res

    def run(self, code: str, **kw: Any) -> Any:
        """Run R code and return its value (native Python object or proxy)."""
        return self.eval(code, **kw).value

    __call__ = run

    def assign(self, name: str, value: Any) -> None:
        self._request({"op": "assign", "name": name, "value": self._to_r(value, f"python -> R `{name}`")})

    def get(self, name: str, convert: bool = True) -> Any:
        reply = self._request({"op": "get", "name": name, "convert": convert})
        return self._from_r(reply["value"], f"R `{name}` -> python")

    def exists(self, name: str) -> bool:
        return bool(self._request({"op": "exists", "name": name})["value"])

    def __setitem__(self, name: str, value: Any) -> None:
        self.assign(name, value)

    def __getitem__(self, name: str) -> Any:
        return self.get(name)

    def call(self, fn: str | dict[str, Any], *args: Any, convert: bool = True, plots: bool = True,
             timeout: float | None = None, **kwargs: Any) -> Any:
        """Call an R function (``"stats::lm"``, ``"mean"`` or a proxied closure)."""
        env_args = [self._to_r(a, f"arg {i} -> R") for i, a in enumerate(args)]
        env_kwargs = {k: self._to_r(v, f"arg {k} -> R") for k, v in kwargs.items()}
        reply = self._request({"op": "call", "fn": fn, "args": env_args, "kwargs": env_kwargs, "convert": convert, "plots": plots},
                              timeout=timeout)
        value = self._from_r(reply.get("value"), "R result -> python")
        res = Result.from_reply(value, reply, session=self, source=f"{fn}(...)")
        self.last = res
        return res.value if res.plot is None or not isinstance(value, type(None)) else res

    def method(self, handle: str, name: str, *args: Any, convert: bool = True, plots: bool = True, **kwargs: Any) -> Any:
        env_args = [self._to_r(a) for a in args]
        env_kwargs = {k: self._to_r(v) for k, v in kwargs.items()}
        reply = self._request({"op": "method", "handle": handle, "method": name, "args": env_args, "kwargs": env_kwargs,
                               "convert": convert, "plots": plots})
        value = self._from_r(reply.get("value"), f"R {name}() -> python")
        res = Result.from_reply(value, reply, session=self, source=f"{name}(<{handle}>)")
        self.last = res
        if value is None and res.plot is not None:
            return res.plot
        return value

    def field(self, handle: str, name: str, convert: bool = True) -> Any:
        reply = self._request({"op": "field", "handle": handle, "name": name, "convert": convert})
        return self._from_r(reply["value"], f"R ${name} -> python")

    def describe(self, handle: str) -> dict[str, Any]:
        return self._request({"op": "describe", "handle": handle})["value"]

    def convert(self, handle: str) -> Any:
        return self._from_r(self._request({"op": "convert", "handle": handle})["value"], "R proxy -> python (forced)")

    def release(self, handle: str) -> None:
        if self.alive:
            try:
                self._request({"op": "release", "handle": handle})
            except Exception:
                pass

    def library(self, package: str) -> "RPackage":
        from ..proxy.r_package import RPackage
        reply = self._request({"op": "library", "package": package})
        self.packages_loaded.add(package)
        return RPackage(self, package, reply.get("exports") or [], reply.get("version", ""))

    package = library

    def function(self, name: str) -> "RFunction":
        from ..proxy.r_package import RFunction
        return RFunction(self, name)

    def install(self, *packages: str, source: str = "auto", repos: str | None = None, timeout: float = 1800) -> Result:
        """Install R packages from CRAN / GitHub (``"user/repo"``) / Bioconductor."""
        pk = list(packages)
        src = source
        if src == "auto":
            src = "github" if any("/" in p for p in pk) else "cran"
        reply = self._request({"op": "install", "packages": pk, "source": src, "repos": repos}, timeout=timeout)
        res = Result(value=bool(reply.get("ok")), stdout=reply.get("stdout", ""), messages=reply.get("messages") or [],
                     warnings=reply.get("warnings") or [], errors=[reply["error"]] if reply.get("error") else [],
                     session=self, source=f"install {pk}")
        if not reply.get("ok"):
            raise RError(f"R package installation failed: {', '.join(pk)}\n{reply.get('error') or ''}\n"
                         f"Source: {src}\nRecommended: check compiler/toolchain (Rtools on Windows) and system libraries; "
                         f"see stdout in r.last.stdout", stdout=reply.get("stdout"))
        return res

    def installed(self, *packages: str) -> dict[str, bool]:
        have = set(self._request({"op": "installed", "packages": list(packages)})["value"])
        return {p: p in have for p in packages}

    def source(self, path: str) -> Result:
        p = os.path.abspath(path).replace("\\", "/")
        return self.eval(f"source('{p}', encoding = 'UTF-8')")

    def signature(self, fn: str) -> dict[str, Any]:
        return self._request({"op": "signature", "fn": fn})["value"]

    def save_rds(self, obj: Any, path: str) -> str:
        from ..proxy.r_object import RObjectProxy
        p = os.path.abspath(path).replace("\\", "/")
        if isinstance(obj, RObjectProxy):
            self._request({"op": "save", "handle": obj.handle, "path": p})
        else:
            self._request({"op": "save", "value": self._to_r(obj), "path": p})
        return p

    def load_rds(self, path: str, convert: bool = True) -> Any:
        p = os.path.abspath(path).replace("\\", "/")
        return self._from_r(self._request({"op": "load", "path": p, "convert": convert})["value"], "readRDS -> python")

    def save_plot(self, handle: str, path: str, width: float = 8, height: float = 6, dpi: int = 150) -> str:
        p = os.path.abspath(path).replace("\\", "/")
        self._request({"op": "plot_save", "handle": handle, "path": p, "width": width, "height": height, "dpi": dpi})
        return p

    def setenv(self, name: str, value: str) -> None:
        """Set an environment variable inside the R worker (in-memory; used for DB secrets, never logged)."""
        self._request({"op": "setenv", "name": name, "value": value})

    def ping(self) -> bool:
        try:
            return self._request({"op": "ping"}, timeout=30).get("value") == "pong"
        except Exception:
            return False

    def __repr__(self) -> str:
        v = self.capabilities.get("r_version", "?")
        return f"<RSession R {v} pid={self.capabilities.get('pid')} {'alive' if self.alive else 'closed'}>"


class _CallableMarker:
    """Tells the R side that a Python attribute is callable (bound method handle)."""

    def __init__(self, handle: str):
        self.handle = handle


def _has_pyarrow() -> bool:
    try:
        import pyarrow  # noqa: F401
        return True
    except Exception:
        return False


_DEFAULT: RSession | None = None


def default_session(**kw: Any) -> RSession:
    global _DEFAULT
    if _DEFAULT is None or not _DEFAULT.alive:
        _DEFAULT = RSession(**kw)
    return _DEFAULT
