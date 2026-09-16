"""Scenarios D and E (design spec §61).

D. Large data: the planner selects Arrow IPC / lazy strategies; types survive; memory is guarded.
E. Unknown package / custom object: an object no registry knows becomes a proxy whose methods work.
"""
import numpy as np
import pandas as pd

import rpython as rp

r = rp.R()

# ---- D: large table ------------------------------------------------------------------------------
n = 1_000_000
big = pd.DataFrame({"id": np.arange(n), "x": np.random.default_rng(0).normal(size=n),
                    "g": pd.Categorical(np.random.default_rng(1).choice(["a", "b", "c"], n)),
                    "t": pd.date_range("2020-01-01", periods=n, freq="min")})
r["big"] = big
print(rp.explain_last(print_it=False).splitlines()[6])         # Transfer: arrow-ipc
print(r("c(nrow(big), class(big$g), class(big$t)[1])"))
back = r.get("big")
print("types preserved:", back.dtypes.equals(big.dtypes), "values equal:", back.equals(big))

# lazy sources are shared, not copied
import pyarrow as pa, pyarrow.parquet as pq, pyarrow.dataset as ds, tempfile, os
tmp = tempfile.mkdtemp()
pq.write_table(pa.Table.from_pandas(big.head(100_000)), os.path.join(tmp, "part-0.parquet"))
r["lake"] = ds.dataset(tmp, format="parquet")
print(r("class(lake)[1]"), r("nrow(dplyr::collect(dplyr::filter(lake, x > 2)))") if r.capabilities["packages"].get("dplyr") else "")

# memory guard
rp.config(memory_threshold_bytes=10_000)
try:
    import scipy.sparse as sp
    rp.to_dense(sp.random(5000, 5000, density=1e-4, format="csr"))
except rp.MemoryGuardError as e:
    print("guard:", str(e).splitlines()[0])
rp.reset_config()

# ---- E: unknown R object ---------------------------------------------------------------------------
r("Account <- R6::R6Class('Account', public = list(balance = 0, deposit = function(x) { self$balance <- self$balance + x; invisible(self) }))")
acc = r("Account$new()")                                        # not in any registry -> proxy
print(acc.rclass, acc.methods()[:5])
acc.deposit(100)
acc.deposit(25)
print("balance:", acc.balance)
acc.save("account.rds")                                         # native serialisation of a proxy
print(rp.load("account.rds", session=r, convert=False).rclass)

# ---- E: unknown Python object in R ------------------------------------------------------------------
class Kalman:
    def __init__(self):
        self.state = 0.0

    def step(self, obs, gain=0.5):
        self.state += gain * (obs - self.state)
        return self.state

r["kf"] = Kalman()                                              # stays in Python; R gets a proxy
print(r("kf$step(10); kf$step(20, gain = 0.8)"))
print("same object back:", r["kf"].state)
r.close()
