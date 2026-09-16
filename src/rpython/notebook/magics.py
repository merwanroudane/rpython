"""Jupyter / Colab magics (MASTER_PROMPT section 25).

    %load_ext rpython          (or rp.setup())

    %r 1 + 1                       # line magic
    %%r -i df -o model             # cell magic: send df, get model back
    library(plm)
    model <- plm(y ~ x1 + x2, data = df, model = "within")

    %%py                           # run Python in the worker namespace (symmetry / SoS-style)

Flags: ``-i a,b`` inputs, ``-o x,y`` outputs, ``-s`` silent, ``-v`` verbose (explain), ``-w W -h H`` plot size.
"""
from __future__ import annotations

import shlex
from typing import Any

try:
    from IPython.core.magic import Magics, cell_magic, line_magic, magics_class  # type: ignore
    from IPython.display import display  # type: ignore
except Exception:  # pragma: no cover - IPython optional
    Magics = object  # type: ignore

    def magics_class(c):  # type: ignore
        return c

    def line_magic(f):  # type: ignore
        return f

    def cell_magic(f):  # type: ignore
        return f

    def display(*a, **k):  # type: ignore
        print(*a)


def _parse(line: str) -> tuple[dict[str, Any], str]:
    opts: dict[str, Any] = {"inputs": [], "outputs": [], "silent": False, "verbose": False}
    toks = shlex.split(line) if line else []
    rest: list[str] = []
    i = 0
    while i < len(toks):
        t = toks[i]
        if t in ("-i", "--input") and i + 1 < len(toks):
            opts["inputs"] += [x for x in toks[i + 1].split(",") if x]
            i += 2
        elif t in ("-o", "--output") and i + 1 < len(toks):
            opts["outputs"] += [x for x in toks[i + 1].split(",") if x]
            i += 2
        elif t in ("-s", "--silent"):
            opts["silent"] = True
            i += 1
        elif t in ("-v", "--verbose"):
            opts["verbose"] = True
            i += 1
        else:
            rest.append(t)
            i += 1
    return opts, " ".join(rest)


@magics_class
class RPythonMagics(Magics):
    def __init__(self, shell: Any):
        super().__init__(shell)
        self._session = None

    def session(self) -> Any:
        if self._session is None or not self._session.alive:
            from ..runtime.r_session import default_session
            self._session = default_session()
        return self._session

    def _run(self, opts: dict[str, Any], code: str) -> Any:
        from ..explain import explain_last
        s = self.session()
        ns = self.shell.user_ns
        for name in opts["inputs"]:
            if name not in ns:
                raise NameError(f"-i {name}: not defined in the notebook")
            s.assign(name, ns[name])
        res = s.eval(code)
        if res.stdout and not opts["silent"]:
            print(res.stdout)
        for m in res.messages:
            print(m)
        for w in res.warnings:
            print("Warning:", w)
        for p in res.plots:
            p.show()
        for name in opts["outputs"]:
            ns[name] = s.get(name)
        if opts["verbose"]:
            explain_last()
        if res.visible and res.value is not None and not opts["silent"]:
            return res.value
        return None

    @line_magic
    def r(self, line: str) -> Any:
        opts, code = _parse(line)
        return self._run(opts, code)

    @cell_magic("r")
    def r_cell(self, line: str, cell: str) -> Any:
        opts, _ = _parse(line)
        return self._run(opts, cell)

    @line_magic
    def py(self, line: str) -> Any:
        from ..worker import python_eval
        r = python_eval(line, ns=self.shell.user_ns)
        if r.stdout:
            print(r.stdout)
        if r.error:
            raise RuntimeError(r.error)
        return r.value

    @cell_magic("py")
    def py_cell(self, line: str, cell: str) -> Any:
        from ..worker import python_eval
        r = python_eval(cell, ns=self.shell.user_ns)
        if r.stdout:
            print(r.stdout)
        if r.error:
            raise RuntimeError(r.error)
        return r.value

    @line_magic
    def rpython(self, line: str) -> Any:
        """``%rpython doctor`` / ``%rpython explain`` / ``%rpython self_test``."""
        from .. import doctor, explain_last, self_test
        cmd = line.strip() or "doctor"
        if cmd == "doctor":
            return doctor()
        if cmd == "explain":
            return explain_last()
        if cmd.startswith("self_test"):
            return self_test(full="full" in cmd)
        print("usage: %rpython doctor | explain | self_test [full]")


def load_ipython_extension(ipython: Any) -> None:
    ipython.register_magics(RPythonMagics)


def unload_ipython_extension(ipython: Any) -> None:  # pragma: no cover
    pass
