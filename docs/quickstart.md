# Quickstart

```python
import pandas as pd, rpython as rp
r = rp.R()
df = pd.DataFrame({"x": [1., 2., 3.], "g": pd.Categorical(["a", "b", "a"])})
r["df"] = df
fit = r("lm(x ~ g, data = df)")
print(fit.coef())
back = r["df"]
assert back.equals(df)
rp.explain_last()
```

From R:

```r
library(rpython)
py <- python()
pd <- py$package("pandas")
df <- pd$DataFrame(list(x = c(1, 2, 3)))
py_to_r(df)
```

Next: [beginner catalog](beginner-catalog.md), [data conversion](data-conversion.md), [catalog of data structures](data-structures-catalog.md).
