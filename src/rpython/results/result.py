"""Unified result model (MASTER_PROMPT section 29) and human-readable R errors."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class RError(Exception):
    """An error raised inside R, rendered for humans with the raw details attached."""

    def __init__(self, message: str, *, call: str | None = None, traceback: str | None = None,
                 stdout: str | None = None, warnings: list[str] | None = None, classes: list[str] | None = None):
        self.message, self.call, self.r_traceback = message, call, traceback
        self.stdout, self.warnings, self.classes = stdout or "", warnings or [], classes or []
        super().__init__(self.render())

    def render(self) -> str:
        lines = ["R error: " + self.message.strip()]
        if self.call:
            lines.append(f"In call: {self.call}")
        hint = _hint_for(self.message)
        if hint:
            lines.append(f"Recommended action:\n  {hint}")
        if self.warnings:
            lines.append("R warnings: " + "; ".join(self.warnings[:5]))
        lines.append("Technical details: err.r_traceback / err.stdout")
        return "\n".join(lines)


def _hint_for(msg: str) -> str:
    m = msg.lower()
    if "there is no package called" in m:
        pkg = msg.split("‘")[-1].split("’")[0] if "‘" in msg else msg.split("'")[-2] if "'" in msg else "<pkg>"
        return f"r.install('{pkg}')  # or rp.fix()"
    if "could not find function" in m:
        return "load the package first: r.library('<package>') or call it as 'pkg::fun'"
    if "object" in m and "not found" in m:
        return "assign it first: r.assign('name', value) or r['name'] = value"
    if "unexpected" in m and ("symbol" in m or "input" in m):
        return "R syntax error: check quotes/braces in the code string"
    return ""


class Plot:
    """A rendered plot (PNG file) with notebook display and ``save()``."""

    def __init__(self, path: str, session: Any = None, handle: str | None = None):
        self.path, self.session, self.handle = path, session, handle

    def _repr_png_(self) -> bytes:
        with open(self.path, "rb") as f:
            return f.read()

    def save(self, path: str, width: float = 8, height: float = 6, dpi: int = 150) -> str:
        import shutil
        if self.handle and self.session is not None and not path.lower().endswith(".png"):
            return self.session.save_plot(self.handle, path, width, height, dpi)
        shutil.copyfile(self.path, path)
        return path

    def show(self) -> None:
        try:
            from IPython.display import display, Image  # type: ignore
            display(Image(filename=self.path))
        except Exception:
            import webbrowser
            webbrowser.open("file://" + self.path)

    def __repr__(self) -> str:
        return f"<Plot {self.path}>"


@dataclass
class Result:
    """What an R evaluation produced.  ``value`` is the natural Python object
    (or a proxy); the rest is everything R said while producing it."""

    value: Any = None
    stdout: str = ""
    messages: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    plots: list[Plot] = field(default_factory=list)
    visible: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] | None = None
    session: Any = None
    source: str = ""

    @classmethod
    def from_reply(cls, value: Any, reply: dict[str, Any], session: Any = None, source: str = "") -> "Result":
        from ..proxy.r_object import RObjectProxy
        handle = value.handle if isinstance(value, RObjectProxy) else None
        plots = [Plot(p, session, handle) for p in (reply.get("plots") or [])]
        return cls(value=value, stdout=reply.get("stdout") or "", messages=list(reply.get("messages") or []),
                   warnings=list(reply.get("warnings") or []), plots=plots, visible=bool(reply.get("visible", True)),
                   raw={k: v for k, v in reply.items() if k != "value"}, session=session, source=source)

    # --- convenience views ---------------------------------------------
    @property
    def plot(self) -> Plot | None:
        return self.plots[-1] if self.plots else None

    @property
    def table(self) -> Any:
        import pandas as pd
        return self.value if isinstance(self.value, pd.DataFrame) else None

    @property
    def model(self) -> Any:
        from ..proxy.r_object import RObjectProxy
        return self.value if isinstance(self.value, RObjectProxy) else None

    @property
    def summary(self) -> str:
        from ..proxy.r_object import RObjectProxy
        if isinstance(self.value, RObjectProxy):
            return self.value.summary_text()
        return repr(self.value)

    @property
    def ok(self) -> bool:
        return not self.errors

    def __repr__(self) -> str:
        parts = [f"<Result value={type(self.value).__name__}"]
        if self.stdout:
            parts.append(f"stdout={len(self.stdout.splitlines())} lines")
        if self.warnings:
            parts.append(f"warnings={len(self.warnings)}")
        if self.plots:
            parts.append(f"plots={len(self.plots)}")
        return " ".join(parts) + ">"

    def _repr_html_(self) -> str:
        import html
        out = []
        if self.stdout:
            out.append(f"<pre>{html.escape(self.stdout)}</pre>")
        if self.value is not None and hasattr(self.value, "_repr_html_"):
            out.append(self.value._repr_html_())
        elif self.value is not None:
            out.append(f"<pre>{html.escape(repr(self.value))}</pre>")
        for w in self.warnings:
            out.append(f"<div style='color:#b45309'>Warning: {html.escape(w)}</div>")
        for p in self.plots:
            import base64
            out.append(f"<img src='data:image/png;base64,{base64.b64encode(p._repr_png_()).decode()}'/>")
        return "\n".join(out)

    def display(self) -> None:
        if self.stdout:
            print(self.stdout)
        for w in self.warnings:
            print("Warning:", w)
        for p in self.plots:
            p.show()
        if self.value is not None and self.visible:
            print(self.value)
