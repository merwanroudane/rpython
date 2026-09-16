# Contributing

Thanks for helping make R and Python one workspace.

## Setup

```bash
git clone https://github.com/merwanroudane/rpython && cd rpython
pip install -e ".[dev]"
R -e 'install.packages(c("jsonlite","arrow","data.table","Matrix","xts","zoo","haven","survival","sf","igraph","plm","duckdb","RSQLite","dbplyr","testthat"))'
python -m pytest tests -q            # R-dependent tests are skipped when R is absent
R CMD INSTALL r-package && Rscript -e 'testthat::test_dir("r-package/tests/testthat", package = "rpython")'
```

After editing anything in `r-package/R/`, run `python tools/sync_r.py` (CI checks that the bundled copy is in sync).

## Adding a converter

1. Python: create an `Adapter` subclass in `src/rpython/data/<family>.py` (or call `rp.register_converter`),
   define `detect`, `encode`, `decode`, set `priority` (specific wrappers first) and register it with
   `REGISTRY.register(..., tested=True, limitations=(...))`.
2. R: add `rpx_encode_<family>` / `rpx_decode_<family>` in `r-package/R/` and dispatch on the class / `kind`.
3. Tests: a `Python -> envelope -> Python` round trip in `tests/roundtrip`, live `Python -> R -> Python` and
   `R -> Python -> R` tests in `tests/integration`, and a family-specific equality in `rpython/fidelity.py`.
4. Docs: a row in `docs/data-structures-catalog.md` stating what is preserved and what is not.

## Adding a database adapter

Subclass `DatabaseAdapter` in `src/rpython/database/`, register it in `database/registry.py`, keep
`tested_live=False` unless CI really runs the service, and add the R driver name (`r_package`).

## Style

Typed Python, focused modules, docstrings explaining *why*; no placeholder code in core paths; never claim a
conversion is lossless unless a test validates it. Commits are authored by their human contributors.
