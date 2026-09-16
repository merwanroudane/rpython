"""Universal R object proxy (MASTER_PROMPT section 28).

An :class:`RObjectProxy` stands for an object that stays alive in the R
worker: S3 models, S4 objects, R6 instances, closures, package-specific
results.  Attribute access delegates to R:

    >>> fit = r("lm(mpg ~ wt, data = mtcars)")
    >>> fit.summary()            # summary(fit) in R -> proxy / value
    >>> fit.coef()               # coef(fit) -> pandas Series
    >>> fit.predict(newdata=df)  # predict(fit, newdata = df)
    >>> fit.coefficients         # fit$coefficients (field)
    >>> fit.methods()            # methods available for its classes
    >>> fit.to_python()          # force a (possibly partial) conversion
    >>> fit.raw                  # the envelope R sent
"""
from __future__ import annotations

from typing import Any


class RObjectProxy:
    __slots__ = ("_env", "_session", "_released")

    def __init__(self, env: dict[str, Any], session: Any = None):
        object.__setattr__(self, "_env", env)
        object.__setattr__(self, "_session", session)
        object.__setattr__(self, "_released", False)

    # ------------------------------------------------------------------ meta
    @property
    def handle(self) -> str:
        return self._env["handle"]

    @property
    def rclass(self) -> list[str]:
        return list(self._env.get("class") or [])

    @property
    def package(self) -> str | None:
        return self._env.get("package")

    @property
    def raw(self) -> dict[str, Any]:
        return self._env

    @property
    def session(self) -> Any:
        return self._session

    def methods(self) -> list[str]:
        return sorted(set(self._env.get("methods") or []))

    def fields(self) -> list[str]:
        return list(self._env.get("fields") or []) + list(self._env.get("slots") or [])

    def summary_text(self) -> str:
        return self._env.get("summary") or self._env.get("repr") or ""

    def _need_session(self) -> Any:
        if self._session is None or not getattr(self._session, "alive", False):
            raise RuntimeError(f"R object {self.rclass} has no live R session (handle {self.handle}); "
                               "the proxy cannot be used after r.close()")
        return self._session

    # ------------------------------------------------------------------ delegation
    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        s = self._need_session()
        fields = list(self._env.get("fields") or []) + list(self._env.get("slots") or [])
        if name in fields:
            return s.field(self.handle, name)
        dotted = name.replace("_", ".")
        if dotted in fields:              # r_squared -> r.squared, fitted_values -> fitted.values
            return s.field(self.handle, dotted)
        return RMethod(self, name)

    def __dir__(self) -> list[str]:
        return sorted(set(self.methods()) | set(self.fields()) | {"summary", "print", "plot", "predict", "coef",
                                                                    "to_python", "save", "methods", "fields", "raw", "rclass"})

    def __getitem__(self, key: Any) -> Any:
        s = self._need_session()
        if isinstance(key, int):
            return s.call("[[", self, key + 1)
        return s.field(self.handle, str(key))

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        s = self._need_session()
        return s.call({"handle": self.handle}, *args, **kwargs)

    def to_python(self) -> Any:
        """Force conversion (R list -> dict etc.); rich semantics may be partially lost and are reported."""
        return self._need_session().convert(self.handle)

    def save(self, path: str, **kw: Any) -> str:
        """RDS for data/models; png/svg/pdf/html for plot objects (ggplot, htmlwidget)."""
        s = self._need_session()
        low = path.lower()
        if low.endswith((".png", ".svg", ".pdf", ".jpg", ".jpeg", ".html")):
            return s.save_plot(self.handle, path, **kw)
        return s.save_rds(self, path)

    def release(self) -> None:
        if not self._released and self._session is not None:
            object.__setattr__(self, "_released", True)
            self._session.release(self.handle)

    def __repr__(self) -> str:
        cls = "/".join(self.rclass)
        pkg = f" from {self.package}" if self.package else ""
        text = self._env.get("repr") or ""
        head = f"<R {cls}{pkg} (proxy {self.handle})>"
        return head + ("\n" + text if text else "")

    def _repr_html_(self) -> str:
        import html
        return f"<pre>{html.escape(repr(self))}</pre>"

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("R proxies are read-only from Python; assign in R with r.assign()/r('obj$x <- ...')")


class RMethod:
    """A method/generic bound to an R proxy: ``fit.predict(newdata=df)`` -> ``predict(fit, newdata = df)``."""

    __slots__ = ("obj", "name")

    def __init__(self, obj: RObjectProxy, name: str):
        self.obj, self.name = obj, name

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self.obj._need_session().method(self.obj.handle, self.name, *args, **kwargs)

    def __repr__(self) -> str:
        return f"<R method {self.name}() on {'/'.join(self.obj.rclass)}>"
