"""R -> Python direction: Rscript drives a Python worker through the companion package."""
import os
import subprocess
import sys

import pytest

from rpython.env.detect import find_r

pytestmark = pytest.mark.r

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_r_drives_python(tmp_path):
    inst = find_r()
    src = os.path.join(ROOT, "r-package", "R").replace("\\", "/")
    script = tmp_path / "drive.R"
    script.write_text(f"""
for (f in sort(list.files('{src}', pattern='[.]R$', full.names=TRUE))) source(f, encoding='UTF-8')
py <- python()
stopifnot(py$run("1 + 1") == 2)
np <- py$package("numpy")
stopifnot(identical(np$arange(3L), 0:2))
df <- data.frame(x = c(1.5, NA), f = factor(c("a","b"), ordered = TRUE), d = as.Date("2024-01-01") + 0:1)
py$assign("df", df)
stopifnot(isTRUE(py$run("df['f'].cat.ordered")))
stopifnot(py$run("str(df['d'].dtype)") == "object")
back <- py$get("df")
stopifnot(identical(back$f, df$f), identical(back$d, df$d), is.na(back$x[2]))
sk <- py$package("sklearn.linear_model")
m <- sk$LinearRegression()
m$fit(matrix(c(1,2,3,4), ncol = 1), c(2,4,6,8))
stopifnot(abs(m$coef_ - 2) < 1e-9)
py$assign("rf", function(x) x * 10)
stopifnot(py$run("rf(4.0)") == 40)
err <- tryCatch(py$run("1/0"), error = function(e) conditionMessage(e))
stopifnot(grepl("ZeroDivisionError", err))
py$close()
cat("R-DRIVES-PYTHON-OK\n")
""", encoding="utf-8")
    env = dict(os.environ, RPYTHON_PYTHON=sys.executable, PYTHONIOENCODING="utf-8")
    out = subprocess.run([inst.rscript, str(script)], capture_output=True, text=True, timeout=300, env=env, encoding="utf-8", errors="replace")
    assert "R-DRIVES-PYTHON-OK" in out.stdout, out.stdout + out.stderr
