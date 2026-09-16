# Explain Mode

Every transfer records a plan: source, target, detected family, transfer backend and tier, payload size, copies, per-step notes, risks and a fidelity report.

```python
import pandas as pd, rpython as rp
plan = rp.explain_plan(pd.DataFrame({"country": ["FR", "FR", "DE", "DE"], "year": [2000, 2001, 2000, 2001], "v": [1., 2., 3., 4.]}), print_it=False)
print(plan.family, [n for n in plan.notes if "suggestion" in n][:1])
```

`rp.explain_last()`, `rp.explain(n)` (history), `rp.explain_plan(obj)` (dry run). R side: `rpx_explain(x)`.
