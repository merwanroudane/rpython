# Panel data

```python
import numpy as np, pandas as pd, rpython as rp
r = rp.R()
pdf = pd.DataFrame({"country": np.repeat(["FR", "DE"], 3), "year": [2000, 2001, 2002] * 2, "y": np.arange(6.), "x": np.arange(6.) ** 2})
p = rp.panel(pdf, id="country", time="year")
print(p.describe_structure())
r["p"] = p
if r.capabilities["packages"].get("plm"):
    fit = r("plm::plm(y ~ x, data = p, model = 'within')")
    print(fit.coef())
back = r["p"]
print(back.index.names)
```

* `rp.cross_section(df, id=, weight=, strata=, cluster=)`, `rp.repeated_cross_section(df, wave=)` (never treated as a panel), `rp.hierarchical(df, levels=[...])`.
* Duplicated `(id, time)` keys cannot become a `pdata.frame`: the data.frame + `rpython.panel` attribute is used and the duplicates are counted.
* A DataFrame that *looks* like a panel is only ever *suggested* in Explain Mode.
