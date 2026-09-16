# Security notes

RPython executes user code in two runtimes by design; it tries not to add risks of its own.

* **Process isolation.** R runs in a separate `Rscript` process (Python → R) and Python in a separate worker
  (R → Python). A crash stays in the worker. Both workers only ever talk to the parent over stdio or a
  loopback (`127.0.0.1`) socket that the parent opened; nothing listens on external interfaces.
* **Pickle.** `rp.save(obj, "x.pkl")` / `rp.load("x.pkl")` and `.rpx` bundles loaded with `prefer_native=True`
  use `pickle`, which executes code on load. RPython warns every time; only load pickles you trust.
* **Package installation runs code.** `r.install()` / `py$install()` run `install.packages()` / `pip`, which
  execute build scripts from CRAN, PyPI, GitHub or local paths. GitHub (`"user/repo"`) and local sources are
  not vetted by anyone; treat them as you would treat cloning and building that code yourself. RPython never
  installs system packages, never elevates privileges and never modifies system or R/Python configuration.
* **Database credentials.** Passwords and tokens found in URLs go to a process-local vault; connection
  references sent to the other runtime carry only the *name* of an environment variable. Secrets never enter
  envelopes, logs, Explain Mode output, `rpython.lock` or `.rpx` bundles. SQL parameters are bound (or quoted
  with the driver's own `dbQuoteLiteral` on the R side), never concatenated.
* **Temporary files.** Arrow IPC payloads and plots are written to a per-session temporary directory
  (`tempfile.mkdtemp` / R `tempdir()`); they contain your data, so treat that directory like your data.
* **Remote execution.** No remote backend is shipped in 0.1. If one is added, it will carry its own
  authentication and documented trust boundary; the local API will not change.
* **Reporting.** Security issues: merwanroudane920@gmail.com.
