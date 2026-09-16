# Jupyter and Google Colab

```text
%load_ext rpython
%r 1 + 1
%%r -i df -o model -v
model <- lm(y ~ x, data = df)
%%py
import polars as pl
```

Colab (fresh runtime):

```text
!pip install "rpython-bridge[arrow]"
import rpython as rp
r = rp.setup()          # R is preinstalled on Colab; rp.doctor() otherwise explains how to add it
r.install("plm")
```

Restore after a runtime reset: `rp.restore("rpython.lock")` (create it with `rpython lock`).
The notebook `notebooks/colab_quickstart.ipynb` walks through install → setup → R package → data transfer → plot → magics → diagnostics.
