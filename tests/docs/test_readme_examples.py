"""README / docs examples are tests (design spec §51).

Every ```python block in README.md and docs/*.md runs verbatim (blocks with
notebook magics or shell lines are skipped).  Blocks that start an R session
need R and are marked accordingly.
"""
import os
import re
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FILES = [os.path.join(ROOT, "README.md")] + sorted(
    os.path.join(ROOT, "docs", f) for f in os.listdir(os.path.join(ROOT, "docs")) if f.endswith(".md"))


def _blocks():
    out = []
    for path in FILES:
        text = open(path, encoding="utf-8").read()
        for i, m in enumerate(re.finditer(r"```python\n(.*?)```", text, re.S)):
            code = m.group(1)
            if any(tok in code for tok in ("%r", "%%r", "%py", "%%py", "!pip", "%load_ext")):
                continue
            out.append(pytest.param(code, id=f"{os.path.basename(path)}#{i}", marks=[pytest.mark.r] if "rp.R()" in code or "session=r" in code or "rp.setup" in code else []))
    return out


@pytest.mark.parametrize("code", _blocks())
def test_doc_example(code, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONWARNINGS="ignore")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=600, env=env, encoding="utf-8", errors="replace")
    assert out.returncode == 0, f"example failed:\n{code}\n--- stderr ---\n{out.stderr[-3000:]}"
