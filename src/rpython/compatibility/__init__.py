"""Packaged compatibility registry (design spec: compatibility firewall / registry).

The YAML entries ship *inside* the wheel (``rpython/compatibility/*.yaml``)
and are read through :mod:`importlib.resources`, so they resolve from an
installed package, a notebook, a container or any working directory.  A
missing or unreadable resource raises :class:`CompatibilityResourceError`
with the cause and the fix -- never a silent empty registry.

The registry is informational (tested versions, preferred path, known
issues); it is **not** a whitelist: unknown packages still go through the
generic conversion path.
"""
from __future__ import annotations

from importlib.resources import files
from typing import Any


class CompatibilityResourceError(RuntimeError):
    """A packaged compatibility resource could not be located or parsed."""

    def __init__(self, resource: str, cause: str):
        super().__init__(
            f"Compatibility resource {resource!r} could not be loaded.\n"
            f"Likely cause: {cause}\n"
            "Recommended action: reinstall the package (pip install --force-reinstall rpython-bridge) and run `rpython doctor`."
        )
        self.resource, self.cause = resource, cause


def _parse_yaml(text: str) -> dict[str, Any]:
    """Minimal YAML subset parser for the registry files (scalars, lists, flow lists)."""
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text) or {}
    except ImportError:
        pass
    out: dict[str, Any] = {}
    key: str | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if line.startswith("  - ") and key is not None:
            out.setdefault(key, [])
            if not isinstance(out[key], list):
                out[key] = []
            out[key].append(line[4:].strip())
            continue
        if ":" in line and not line.startswith(" "):
            key, _, value = line.partition(":")
            key, value = key.strip(), value.strip()
            if value == "":
                out[key] = []
            elif value.startswith("[") and value.endswith("]"):
                inner = value[1:-1].strip()
                out[key] = [v.strip().strip('"').strip("'") for v in inner.split(",")] if inner else []
            else:
                out[key] = value.strip('"')
    return out


def resource_names() -> list[str]:
    try:
        root = files(__name__)
        return sorted(p.name for p in root.iterdir() if p.name.endswith(".yaml"))
    except Exception as e:  # noqa: BLE001
        raise CompatibilityResourceError("rpython/compatibility/*.yaml", f"{type(e).__name__}: {e}") from e


def load(name: str) -> dict[str, Any]:
    """Load one registry entry by file name (``"pandas.yaml"``) or package name (``"pandas"``)."""
    fname = name if name.endswith(".yaml") else f"{name}.yaml"
    try:
        text = files(__name__).joinpath(fname).read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise CompatibilityResourceError(fname, "file is not shipped in this installation") from e
    except Exception as e:  # noqa: BLE001
        raise CompatibilityResourceError(fname, f"{type(e).__name__}: {e}") from e
    data = _parse_yaml(text)
    if not isinstance(data, dict) or "package" not in data:
        raise CompatibilityResourceError(fname, "malformed entry (missing 'package' key)")
    return data


def registry() -> dict[str, dict[str, Any]]:
    """All packaged entries, keyed by ``runtime:package`` (e.g. ``python:pandas``, ``r:sf``)."""
    names = resource_names()
    if not names:
        raise CompatibilityResourceError("rpython/compatibility/*.yaml", "no YAML entries found in the installed package")
    out: dict[str, dict[str, Any]] = {}
    for n in names:
        entry = load(n)
        out[f"{entry.get('runtime', '?')}:{entry['package']}"] = entry
    return out


def lookup(package: str, runtime: str | None = None) -> dict[str, Any] | None:
    """Entry for a package, or None when the registry has nothing to say (which is fine)."""
    for key, entry in registry().items():
        rt, pkg = key.split(":", 1)
        if pkg.lower() == package.lower() and (runtime is None or rt == runtime):
            return entry
    return None
