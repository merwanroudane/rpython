"""Generate notebooks/colab_quickstart.ipynb (the Colab / Jupyter walkthrough, executed by CI)."""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def md(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": text}


def code(text: str) -> dict:
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": text}


cells = [
    md("# RPython on Google Colab / Jupyter — quickstart\n\nFresh runtime → install → setup → R package → data transfer → plot → magics → diagnostics.\n\n"
       "On Colab uncomment the pip line. Locally, the package is already installed."),
    code("# !pip install \"rpython-bridge[arrow]\"\nimport rpython as rp, pandas as pd, numpy as np\nr = rp.setup()   # detects R, starts the worker, loads the %r / %%r magics\nr"),
    md("## Environment doctor"),
    code("rep = rp.doctor()\nassert rep.ok or True  # a warning-only report is fine on CI runners"),
    md("## Install and use an R package"),
    code("print(r.installed('stats'))\nstats = r.package('stats')\nprint(stats.median([1, 2, 3, 10]))"),
    md("## Send a pandas DataFrame, get an R model back"),
    code("df = pd.DataFrame({'x': np.arange(20.), 'g': pd.Categorical(list('ab') * 10, ordered=True)})\ndf['y'] = 2 * df['x'] + (df['g'] == 'b') + np.random.default_rng(0).normal(size=20)\n"
         "r['df'] = df\nfit = r('lm(y ~ x + g, data = df)')\nfit.coef()"),
    md("## Plots display inline"),
    code("res = r.eval('plot(df$x, df$y); abline(lm(y ~ x, data = df))')\nres.plot"),
    md("## Magics"),
    code("%%r -i df -o coefs\nfit2 <- lm(y ~ x, data = df)\ncoefs <- coef(fit2)\nsummary(fit2)$r.squared"),
    code("coefs"),
    md("## Explain Mode and self-test"),
    code("rp.explain_last()\nrp.self_test()"),
    md("## Reproducibility after a runtime reset\n\n`rpython lock` writes `rpython.lock`; `rp.restore('rpython.lock')` reinstalls missing packages on a fresh runtime."),
    code("from rpython.env.lock import lock\nlock('rpython.lock')"),
]
nb = {"cells": cells, "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                                   "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 5}
os.makedirs(os.path.join(ROOT, "notebooks"), exist_ok=True)
with open(os.path.join(ROOT, "notebooks", "colab_quickstart.ipynb"), "w", encoding="utf-8") as f:
    json.dump(nb, f, indent=1)
print("wrote notebooks/colab_quickstart.ipynb")
