# Diagnostics

| Call | Purpose |
|---|---|
| `rp.doctor()` | platform, Python, every R installation found and which one is used, key packages on both sides, worker readiness, round-trip and plot checks, issues + fixes |
| `rp.check()` | one-second readiness |
| `rp.self_test(full=True)` | 25+ interoperability checks across families |
| `rp.fix()` | installs pyarrow / core R packages (never touches system settings) |
| `rp.restore(lock)` | reinstalls what `rpython.lock` lists |
| `rpython env --json` | machine-readable runtime report |

Errors are human-readable and actionable (`RError`, `ConversionError`, `MemoryGuardError`) with the raw traceback attached.
