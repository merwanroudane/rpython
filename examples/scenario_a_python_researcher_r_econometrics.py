"""Scenario A -- a Python researcher using R econometrics (MASTER_PROMPT section 61).

1. load pandas data          2. declare the panel structure      3. load an R econometrics package
4. pass the panel to R       5. fit a fixed-effects model         6. retrieve the summary
7. plot diagnostics          8. save model + data                 9. reload and inspect metadata
"""
import numpy as np
import pandas as pd

import rpython as rp

rng = np.random.default_rng(7)
countries, years = [f"C{i:02d}" for i in range(12)], list(range(2005, 2020))
df = pd.DataFrame([(c, y) for c in countries for y in years], columns=["country", "year"])
df["invest"] = rng.normal(size=len(df))
df["gdp"] = 0.8 * df["invest"] + rng.normal(size=len(df)) + df["country"].map({c: i * 0.1 for i, c in enumerate(countries)})

panel = rp.panel(df, id="country", time="year")                     # 2. explicit, never guessed
print(panel.describe_structure())

r = rp.R()
if not r.installed("plm")["plm"]:
    r.install("plm")                                                 # 3. CRAN install through the bridge
r["p"] = panel                                                       # 4. becomes plm::pdata.frame
fit = r("fit <- plm::plm(gdp ~ invest, data = p, model = 'within')")  # 5. stays in R (also bound as `fit`)
print(fit.coef())                                                    # 6. pandas Series
summ = fit.summary()
print(summ.rclass, summ.r_squared)                                   #    nested proxy field -> named Series
res = r.eval("plot(as.numeric(fitted(fit)), as.numeric(residuals(fit)), xlab = 'fitted', ylab = 'residuals'); abline(h = 0)")
res.plot.save("scenario_a_residuals.png")                           # 7.
fit.save("scenario_a_fit.rds")                                       # 8. native serialisation
bundle = rp.save(panel, "scenario_a_panel.rpx")
reloaded = rp.load(bundle)                                           # 9. panel semantics survive
print(reloaded.attrs["rpython"]["panel"]["n_entities"], reloaded.index.names)
rp.explain_last()
r.close()
