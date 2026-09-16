# Data conversion

## The rules

1. **Detection → classification → negotiation → best path → fidelity → proxy fallback.** See `rp.explain_last()`.
2. **Never silently lossy.** `rp.config(lossy="warn"|"error"|"allow")` decides what happens when a target cannot hold a semantic; the default warns and records the loss in the fidelity report.
3. **Missing values are explicit.** `None`/`pd.NA` ↔ `NA`; `nan` ↔ `NaN` for scalars/arrays; pandas float64 `NaN` ↔ `NA` (pandas semantics) unless `rp.config(missing="nan")`.
4. **Unknown ≠ unsupported.** Anything without an adapter becomes a proxy; `rp.register_converter()` adds an exact adapter without touching the core.

## Choosing the transfer path

`rp.config(transfer="auto"|"arrow"|"json")`; `arrow_threshold_rows` (default 5 000). Arrow needs `pyarrow` in Python and `arrow` in R; otherwise JSON is used and reported.

## Per-family details

See [data-structures-catalog.md](data-structures-catalog.md).

## Extending

```python
import rpython as rp

class Money:
    def __init__(self, amount, ccy): self.amount, self.ccy = amount, ccy

rp.register_converter(family="money", kind="money", detect=lambda o: isinstance(o, Money),
                      encode=lambda o, ctx: {"amount": o.amount, "ccy": o.ccy},
                      decode=lambda env, ctx: Money(env["amount"], env["ccy"]))
back, ctx = rp.roundtrip(Money(5, "EUR"))
print(back.ccy, ctx.plan.family)
```

R side: `rpx_register_decoder("money", function(env) structure(list(amount = env$amount, ccy = env$ccy), class = "money"))` and `rpx_register_encoder(function(x) inherits(x, "money"), function(x) list(rpx = 1L, kind = "money", amount = x$amount, ccy = x$ccy))`.
