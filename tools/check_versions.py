"""Release gate: the version must be identical in pyproject.toml, rpython.__version__,
r-package/DESCRIPTION and the R worker capabilities; optionally also in a git tag (vX.Y.Z)."""
import os
import re
import sys
import tomllib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
py = tomllib.load(open(os.path.join(ROOT, "pyproject.toml"), "rb"))["project"]["version"]
init = re.search(r'__version__ = "([^"]+)"', open(os.path.join(ROOT, "src/rpython/__init__.py"), encoding="utf-8").read()).group(1)
desc = re.search(r"^Version:\s*(\S+)", open(os.path.join(ROOT, "r-package/DESCRIPTION"), encoding="utf-8").read(), re.M).group(1)
worker = re.search(r'rpython_version = "([^"]+)"', open(os.path.join(ROOT, "r-package/R/worker.R"), encoding="utf-8").read()).group(1)
versions = {"pyproject.toml": py, "rpython.__version__": init, "r-package/DESCRIPTION": desc, "worker.R capabilities": worker}
tag = sys.argv[1] if len(sys.argv) > 1 else None
if tag:
    versions["git tag"] = tag.lstrip("v")
bad = {k: v for k, v in versions.items() if v != py}
for k, v in versions.items():
    print(f"{k:24s} {v}")
if bad:
    print("VERSION MISMATCH:", bad)
    sys.exit(1)
print("versions consistent:", py)
