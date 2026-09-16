# FAQ

**Is RPython a replacement for rpy2 / reticulate?** It is a higher-level, symmetric alternative built on process isolation and a semantic envelope. If you need in-process embedding for micro-latency, rpy2/reticulate remain excellent choices.

**Does it copy my data twice?** Small objects go through JSON once; tables use Arrow IPC (one file write/read); datasets, rasters and databases are shared, not copied.

**What happens with an object it has never seen?** It becomes a proxy; you can still call its methods and force a (documented) conversion with `.to_python()` / `py_to_r()`.

**Are RNG streams equivalent?** No. Data crosses faithfully; random number generators differ. `rp.simulation()` says so explicitly.

**Why does `NaN` in a pandas column become `NA` in R?** Because pandas uses `NaN` as its missing marker in float64 columns. `rp.config(missing="nan")` keeps `NaN`.

**Can I use it without Jupyter?** Yes — scripts, VS Code, the CLI and plain R sessions all use the same API.
