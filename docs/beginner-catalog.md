# Beginner Command Catalog

Every entry: what it does, why the important line exists, what comes back, what to expect, common mistakes.
All Python blocks run as-is (they are part of the test suite).

## A. Starting / setup

```python
import rpython as rp
r = rp.R()          # starts an isolated R worker (or reuses the default one); r.capabilities tells you what R has
print(r.capabilities["r_version"])
print(rp.check())   # True when R answers; rp.doctor() prints the full report
```

* **Returns:** an `RSession`. Creating a second `rp.R(timeout=60)` with arguments starts a *new* worker.
* **Mistake:** calling `rp.R()` in a loop expecting fresh state — the default session persists (`r.restart()` resets it).

From R: `library(rpython); py <- python()` (needs `pip install rpython` in the chosen interpreter; set `RPYTHON_PYTHON` to pin it).

## B. Packages

```python
import rpython as rp
r = rp.R()
stats = r.package("stats")               # load (attaches nothing; functions are called as stats::name)
print(stats.median([3, 1, 2]))            # 2.0
print(r.installed("stats", "notapkg"))    # {'stats': True, 'notapkg': False}
# r.install("plm")                        # CRAN; "user/repo" -> GitHub; source="bioc" -> Bioconductor
```

* Dotted names: `forecast.auto_arima` resolves to `forecast::auto.arima`; keyword `n_ahead=` becomes `n.ahead=` when R expects it.
* **Mistake:** `r("library(plm)")` then `r("plm(...)")` works too, but `r.package("plm").plm(...)` is explicit and needs no attach.

## C. Data

```python
import numpy as np, pandas as pd, rpython as rp
r = rp.R()
r["v"] = [1.0, None, float("nan")]       # None -> NA, nan -> NaN (explicit tokens on the wire)
r["m"] = np.arange(6.0).reshape(2, 3)    # numpy -> matrix; m[1,2] in R == m[0,1] in Python
r["d"] = {"a": 1, "b": ["x", "y"]}       # dict -> named list
df = pd.DataFrame({"g": pd.Categorical(["a", "b"], ordered=True), "t": pd.date_range("2024", periods=2, tz="UTC")})
r["df"] = df                              # categories + order + timezone preserved
print(r("levels(df$g)"), r("attr(df$t, 'tzone')"))
print(type(r["df"]).__name__, r["df"].equals(df))
```

Declaring structure (never guessed silently):

```python
import numpy as np, pandas as pd, rpython as rp
panel = rp.panel(pd.DataFrame({"id": ["a", "a", "b", "b"], "year": [1, 2, 1, 2], "y": [1., 2., 3., 4.]}), id="id", time="year")
ts = rp.timeseries(pd.DataFrame({"date": pd.date_range("2020-01-01", periods=6, freq="MS"), "y": range(6)}), time="date", freq="MS")
lab = rp.labelled(pd.DataFrame({"sex": [1, 2]}), value_labels={"sex": {1: "male", 2: "female"}}, variable_labels={"sex": "Sex"})
sv = rp.survival(pd.DataFrame({"t": [1., 2.], "d": [1, 0]}), time="t", event="d")
for obj in (panel, ts, lab, sv):
    print(obj.describe_structure().splitlines()[0])
```

## D. Code execution

```python
import rpython as rp
r = rp.R()
print(r("1 + 1"))                          # single expression -> value
res = r.eval("""
x <- 1:10
cat("sum:", sum(x), "\n")
mean(x)
""")                                       # multi-line block -> Result
print(res.stdout, res.value)
print(r.call("paste", "a", "b", sep="-"))  # call a function with positional and keyword args
```

* `r.source("script.R")` runs a file; `r.function("name")` binds a function.
* **Mistake:** forgetting that R code runs in the worker's own environment — variables set with `r["x"]` are visible, Python variables are not (send them first).

## E. Results

```python
import rpython as rp
r = rp.R()
fit = r("lm(mpg ~ wt, data = mtcars)")     # rich object -> RObjectProxy (stays in R)
print(fit.rclass, fit.package)             # ['lm'] stats
print(fit.coef())                          # pandas Series
print(fit.summary().r_squared > 0.7)       # nested proxies; fields with dots use underscores
print(fit.fields()[:3], fit.methods()[:3])
plain = fit.to_python()                    # forced conversion to a dict (structure kept, class recorded)
print(type(plain).__name__)
try:
    r("stop('boom')")
except rp.RError as e:
    print(str(e).splitlines()[0])          # R error: boom
```

## F. Notebook / Colab

```text
%load_ext rpython     # or rp.setup()
%r summary(mtcars$mpg)
%%r -i df -o fit
fit <- lm(y ~ x, data = df)
```

`-i` sends notebook variables, `-o` brings R variables back, `-s` silent, `-v` prints Explain Mode after the cell.
Plots display automatically. Colab: `!pip install rpython` then `rp.setup()`; `rpython lock` / `rp.restore()` for fresh runtimes.

## G. Save / load

```python
import pandas as pd, rpython as rp
df = pd.DataFrame({"c": pd.Categorical(["a", "b"], ordered=True)})
rp.save(df, "d.parquet")                   # lossless
rp.save(df, "d.csv")                       # warns + sidecar d.csv.rpx.json
print(rp.load("d.csv")["c"].cat.ordered)   # True
b = rp.save(df, "d.rpx")                   # universal bundle (manifest + portable + native)
print(rp.load(b).equals(df))
```

Models: `fit.save("fit.rds")`, `rp.load("fit.rds", session=r)`; plots: `res.plot.save("p.png")`, `g.save("g.svg")`.

## H. Diagnostics

```python
import rpython as rp
r = rp.R()
r["x"] = [1, 2, 3]
rp.explain_last()                          # plan, transfer path, fidelity for the last transfer
rep = rp.validate_roundtrip([1.0, None, 3.0], r)
print(rep.summary().splitlines()[-1])      # Overall: lossless
```

`rp.doctor()`, `rp.check()`, `rp.self_test(full=True)`, `rp.fix()`, `rp.restore("rpython.lock")`; CLI: `rpython doctor`, `rpython self-test --full`, `rpython env`, `rpython catalog`.
