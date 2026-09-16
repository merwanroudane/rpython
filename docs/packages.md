# Packages

| | Python side | R side |
|---|---|---|
| install R packages | `r.install("plm", "fixest")`, `r.install("user/repo")`, `source="bioc"` | `install.packages()` |
| install Python packages | `pip install ...` | `py$install("polars", source = "pip")` (or `"uv"`, `"conda"`) |
| load | `r.package("plm")` | `py$package("sklearn.linear_model")` |
| list what the bridge sees | `rpython packages` | `py$capabilities` |

Unknown packages are used through the generic path: load → call → inspect result → convert or proxy. Compilation, system libraries, CUDA etc. are reported with the R/pip output rather than pretended away.
