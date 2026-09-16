# Functions across the boundary

```python
import rpython as rp
r = rp.R()
r("sq <- function(x, k = 2) x^k")
sq = r.function("sq")
print(sq(3), sq(3, k=3))                      # 9.0 27.0
print(r.signature("sq"))                      # arguments and defaults
r["pyf"] = lambda a, b=1: a + b               # Python callable usable from R
print(r("pyf(2, b = 40)"))                    # 42.0
r["df_fn"] = lambda df: df.assign(z=df["x"] * 2)
print(r("df_fn(data.frame(x = 1:2))$z"))      # [2 4]
```

Warnings, messages and errors raised inside the callee are captured and re-raised on the caller's side with context.
