# Environments

RPython detects: system Python, venv, uv, conda, Poetry, Jupyter kernels, VS Code, Colab, Docker; multiple R installations (registry, PATH, `R_HOME`, standard locations). It never picks an R at random: explicit configuration wins, then environment variables, then PATH, then the highest version — and `rp.doctor()` lists every candidate.

```bash
rpython env            # what will be used
rpython lock           # write rpython.lock (Python + R packages, platform, runtime settings)
rpython restore        # reinstall from it
```

`rpython.lock` orchestrates native lock files (`uv.lock`, `requirements.txt`, `renv.lock`) rather than replacing them.
