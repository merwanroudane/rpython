# Time series

| Python | R | When |
|---|---|---|
| `Series`/`DataFrame` with `DatetimeIndex` (freq 1/4/12/52/7/24/365) or `PeriodIndex` | `ts` / `mts` | regular, no tz, no duplicates |
| irregular, tz-aware, duplicates | `xts` (or `zoo`) | |
| `rp.timeseries(df, time=, ids=[...])` | `tsibble` | keyed / grouped |

```python
import numpy as np, pandas as pd, rpython as rp
r = rp.R()
y = pd.Series(np.arange(12.), index=pd.date_range("2021-01-01", periods=12, freq="MS"))
r["y"] = y
print(r("frequency(y)"), r("start(y)"))
fc = r.package("stats").arima(y, order=[1, 0, 0])   # any R time-series function
print(fc.rclass)
print(rp.timeseries(y).describe_structure())
```

Preserved: values, index, frequency, timezone, missing periods, duplicate timestamps, series names, seasonal period.
R `ts` objects with unusual frequencies decode to a numeric time index (documented limitation).
