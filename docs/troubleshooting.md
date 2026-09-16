# Troubleshooting

See the table in the README first. Additional cases:

* **`TimeoutError: R call exceeded N s`** — pass `timeout=None` to `rp.R()` or the call; long installations use `r.install(..., timeout=3600)`.
* **R worker dies during a package call** — the Python process is intact; `r.restart()`; report the package with `rp.doctor()` output. The crash is isolated by design.
* **Unicode garbled on Windows consoles** — set `PYTHONIOENCODING=utf-8`; data itself is UTF-8 end to end.
* **`ConversionError: optional dependency missing`** — the message names the extra to install (`pip install "rpython[spatial]"`).
* **`MemoryGuardError`** — use pushdown/lazy paths or `allow_materialize=True`.
* **Proxy used after `r.close()`** — proxies belong to a session; reopen and recreate.
