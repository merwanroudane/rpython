# Release readiness report

Generated 2026-09-16T15:16 by `python tools/release_report.py` on Windows-10-10.0.26200-SP0, Python 3.11.0, pandas 3.0.5, numpy 2.4.6.

Counts come from the JUnit output of the full pytest run; nothing here is typed by hand.

| Subsystem | Passed / Total | Skipped | Status |
|---|---|---|---|
| Primitives & collections | 59 / 59 | 0 | PASS |
| Arrays & sparse | 20 / 20 | 0 | PASS |
| Tabular (pandas/polars/arrow) | 10 / 10 | 0 | PASS |
| Time series | 2 / 2 | 0 | PASS |
| Panel / cross-section | 3 / 3 | 0 | PASS |
| Survey / survival | 2 / 2 | 0 | PASS |
| Spatial / raster / spatiotemporal | 3 / 3 | 0 | PASS |
| Networks | 2 / 2 | 0 | PASS |
| Text / media / scientific / economics | 4 / 4 | 0 | PASS |
| Proxies & lazy objects | 3 / 3 | 0 | PASS |
| R runtime & Python -> R -> Python (live) | 18 / 18 | 0 | PASS |
| R -> Python (live) | 1 / 1 | 0 | PASS |
| Economics end-to-end (live) | 12 / 12 | 0 | PASS |
| Databases | 9 / 9 | 0 | PASS |
| Persistence / edge cases / CLI | 14 / 14 | 1 | PASS |
| Documentation examples | 31 / 31 | 0 | PASS |
| Other | 3 / 3 | 0 | PASS |
| **All Python tests** | **196 / 196** | | **PASS** |
| R package (testthat) | 43 / 43 expectations passed, 0 skipped -> PASS | | |
| R CMD check | OK | | |

## Limitations recorded

* Vendor databases other than SQLite/DuckDB/Parquet are interface-tested with fakes, not live (see `rpython catalog`).
* R `ts` objects with frequencies other than 1/4/12 decode to a numeric time index.
* Bioinformatics / chemistry / phylogenetics objects use the generic proxy path (adapters can be registered).
* Embedded bridges have lower per-call latency; RPython uses a separate worker process by design.
