# Architecture

```text
Public API (rp.*, RSession, proxies, rp.panel/...)      R package (python(), rpx_*)
            │                                                    │
Semantic data layer: registry of adapters (tiers A→E), Context/TransferPlan, fidelity
            │
Portable envelope (RPX v1): JSON + Arrow IPC + WKB + handles + shared paths
            │
Transport: newline-delimited JSON over stdio (Python→R worker) or TCP (R→Python worker); "@RPX@" framing
            │
Workers: Rscript running rpython_worker()  |  python -m rpython.worker
```

* `data/semantic.py` model, `data/registry.py`, `data/context.py`, `data/convert.py`, one module per family.
* `database/` base (ConnectionRef, SecretVault, adapters), `relation.py` (lazy Relation + envelope), `registry.py`, `api.py`.
* `runtime/r_session.py` process lifecycle, protocol, callbacks (R calling Python proxies while Python waits).
* `proxy/` RObjectProxy / RPackage / RFunction. `results/` Result, Plot, RError. `persistence/` save/load/bundle.
* `diagnostics/`, `env/` (detection, lock), `notebook/magics.py`, `cli.py`, `worker.py`.
* `r-package/R/`: `aaa_state.R`, `rpx_encode.R`, `rpx_decode.R`, `worker.R`, `python.R`, `pyproxy.R`, `db.R`.

Design principles: R and Python are equal citizens; native code stays native; no silent semantic corruption; large data is not copied blindly; hide backend complexity, never backend limitations.
