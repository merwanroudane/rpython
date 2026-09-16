# Models and proxies

```python
import pandas as pd, rpython as rp
r = rp.R()
fit = r("glm(am ~ wt, data = mtcars, family = binomial)")
print(fit.rclass)                                   # ['glm', 'lm']
print(fit.predict(newdata=pd.DataFrame({"wt": [2.5]}), type="response"))
print(fit.aic, fit.summary().coefficients.shape)    # fields and nested proxies
fit.save("model.rds")
again = rp.load("model.rds", session=r, convert=False)
print(again.rclass)
```

Python objects in R: `r["model"] = sklearn_model` then `model$predict(X)` in R. Objects always return as the same Python object.
