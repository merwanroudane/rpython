"""R packages and functions as first-class Python objects (sections 21, 27).

    >>> forecast = r.package("forecast")
    >>> fit = forecast.auto_arima(y)      # forecast::auto.arima(y)
    >>> forecast.auto_arima.signature()
    >>> forecast.auto_arima.help()

Python identifiers cannot contain dots, so ``auto_arima`` resolves to
``auto.arima`` when the exact name does not exist.  Unknown packages need
no registry entry: any installed package works through the same path.
"""
from __future__ import annotations

from typing import Any


class RFunction:
    __slots__ = ("session", "spec", "_sig")

    def __init__(self, session: Any, spec: str):
        self.session, self.spec, self._sig = session, spec, None

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        # Python keyword names cannot contain dots; allow ``n_ahead`` -> ``n.ahead`` when R expects it.
        sig = self._safe_signature()
        if sig:
            rnames = set(sig.get("args") or [])
            kwargs = {(k if k in rnames else k.replace("_", ".") if k.replace("_", ".") in rnames else k): v
                      for k, v in kwargs.items()}
        return self.session.call(self.spec, *args, **kwargs)

    def _safe_signature(self) -> dict[str, Any] | None:
        if self._sig is None:
            try:
                self._sig = self.session.signature(self.spec)
            except Exception:
                self._sig = {}
        return self._sig or None

    def signature(self) -> dict[str, Any]:
        return self._safe_signature() or {}

    def help(self) -> str:
        doc = (self._safe_signature() or {}).get("doc")
        return doc or f"no help page found for {self.spec}"

    def __repr__(self) -> str:
        sig = self._safe_signature() or {}
        args = ", ".join(sig.get("args") or [])
        return f"<R function {self.spec}({args})>"


class RPackage:
    def __init__(self, session: Any, name: str, exports: list[str], version: str = ""):
        object.__setattr__(self, "_session", session)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "exports", list(exports))
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "_export_set", set(exports))

    def _resolve(self, attr: str) -> str:
        if attr in self._export_set:
            return attr
        dotted = attr.replace("_", ".")
        if dotted in self._export_set:
            return dotted
        # partial: e.g. ``auto_arima`` vs ``auto.arima`` handled above; try mixed
        for cand in self._export_set:
            if cand.replace(".", "_") == attr:
                return cand
        return attr  # let R raise a clear error (non-exported / internal)

    def __getattr__(self, attr: str) -> Any:
        if attr.startswith("_"):
            raise AttributeError(attr)
        return RFunction(self._session, f"{self.name}::{self._resolve(attr)}")

    def __getitem__(self, name: str) -> RFunction:
        return RFunction(self._session, f"{self.name}::{name}")

    def __dir__(self) -> list[str]:
        return sorted(self.exports)

    def __repr__(self) -> str:
        return f"<R package {self.name} {self.version} ({len(self.exports)} exports)>"

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("R packages are read-only")
