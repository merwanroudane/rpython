# python.R -- R drives Python: the symmetric side of the bridge.
#
#   library(rpython)
#   py <- python()
#   sk <- py$package("sklearn.linear_model")
#   model <- sk$LinearRegression()
#   model$fit(X, y)
#   py$run("import numpy as np; np.arange(3)")
#
# Transport: R opens a server socket, launches `python -m rpython.worker
# --connect <port>` and talks the same newline-delimited JSON protocol
# the Python side uses for R.  Python objects without an R equivalent stay
# in Python behind rpx_pyproxy handles; R objects sent to Python that have
# no Python equivalent stay in R behind handles served by py_request().

rpx_find_python <- function(python = NULL) {
  cands <- c(python, Sys.getenv("RPYTHON_PYTHON"), Sys.getenv("RETICULATE_PYTHON"),
             Sys.getenv("VIRTUAL_ENV") |> (\(v) if (nzchar(v)) file.path(v, if (.Platform$OS.type == "windows") "Scripts/python.exe" else "bin/python") else "")(),
             Sys.getenv("CONDA_PREFIX") |> (\(v) if (nzchar(v)) file.path(v, if (.Platform$OS.type == "windows") "python.exe" else "bin/python") else "")(),
             Sys.which("python3"), Sys.which("python"))
  cands <- cands[nzchar(cands)]
  for (p in cands) {
    ok <- tryCatch(system2(p, c("-c", shQuote("import rpython, sys; print(sys.version.split()[0])")), stdout = TRUE, stderr = FALSE), error = function(e) character())
    if (length(ok) && !is.null(attr(ok, "status")) && attr(ok, "status") != 0) next
    if (length(ok) && grepl("^[0-9]", ok[1])) return(list(path = p, version = ok[1]))
  }
  stop("No Python interpreter with the 'rpython' package found.\n",
       "Tried: ", paste(cands, collapse = ", "), "\n",
       "Recommended action: pip install rpython   (then set RPYTHON_PYTHON=<path to python> if it is not on PATH)")
}

#' @export
python_start <- function(python = NULL, timeout = 60) {
  info <- rpx_find_python(python)
  port <- sample(20000:60000, 1)
  # Python listens; R connects (avoids the blocking accept problem in base R).
  log <- tempfile("rpython-py-", fileext = ".log")
  args <- c("-m", "rpython.worker", "--port", port)
  pid <- system2(info$path, args, stdout = log, stderr = log, wait = FALSE)
  deadline <- Sys.time() + timeout
  con <- NULL
  while (Sys.time() < deadline) {
    Sys.sleep(0.2)
    con <- tryCatch(suppressWarnings(socketConnection(host = "127.0.0.1", port = port, server = FALSE, blocking = TRUE,
                                                      open = "r+b", timeout = 600, encoding = "UTF-8")), error = function(e) NULL)
    if (!is.null(con)) break
    if (file.exists(log) && any(grepl("Error|Traceback", readLines(log, warn = FALSE)))) break
  }
  if (is.null(con)) stop("Python worker did not start. Log:\n", paste(readLines(log, warn = FALSE), collapse = "\n"))
  s <- new.env(parent = emptyenv())
  s$con <- con; s$id <- 0L; s$alive <- TRUE; s$python <- info$path; s$version <- info$version; s$log <- log
  class(s) <- "rpython_session"
  ready <- py_read(s)
  if (is.null(ready) || !identical(ready$op, "ready")) stop("Python worker handshake failed")
  s$capabilities <- py_request(s, list(op = "hello", arrow = rpx_has("arrow"), transfer = .rpx_state$transfer))
  .rpx_state$peer_arrow <- isTRUE(s$capabilities$arrow)
  .rpx_state$py <- s
  s$run <- function(code, ...) py_run(s, code, ...)
  s$eval <- function(code, ...) py_eval(s, code, ...)
  s$package <- function(name) py_package(s, name)
  s$import <- s$package
  s$assign <- function(name, value) py_assign(s, name, value)
  s$get <- function(name) py_get(s, name)
  s$install <- function(...) py_install(s, ...)
  s$call <- function(fn, ...) py_call_fn(s, fn, ...)
  s$close <- function() py_close(s)
  s
}

#' Start a Python session driven from R: `py <- python()`.
#' @export
python <- python_start

#' @export
print.rpython_session <- function(x, ...) {
  cat("<Python session ", x$version, " (", x$python, ") ", if (isTRUE(x$alive)) "alive" else "closed", ">\n", sep = "")
  invisible(x)
}

py_send <- function(s, msg) {
  writeLines(paste0("@RPX@", rpx_json(msg)), con = s$con, useBytes = TRUE)
  flush(s$con)
}

py_read <- function(s) {
  repeat {
    line <- readLines(s$con, n = 1L, warn = FALSE, encoding = "UTF-8")
    if (!length(line)) { s$alive <- FALSE; return(NULL) }
    if (startsWith(line, "@RPX@")) return(jsonlite::fromJSON(substring(line, 6L), simplifyVector = FALSE))
  }
}

# Serve a callback from Python (it wants something from R: an R proxy method, field, function call ...)
py_serve_callback <- function(s, req) {
  res <- tryCatch({
    val <- switch(req$what,
      method = { r <- rpx_call_method(rpx_get_handle(req$handle), req$method, lapply(req$args %||% list(), rpx_decode), lapply(req$kwargs %||% list(), rpx_decode), plots = FALSE); if (!is.null(r$error)) stop(r$error); r$value },
      field = rpx_get_field(rpx_get_handle(req$handle), req$name),
      call = { fn <- rpx_resolve_function(req$fn); r <- rpx_eval_call(fn, c(lapply(req$args %||% list(), rpx_decode), lapply(req$kwargs %||% list(), rpx_decode)), plots = FALSE); if (!is.null(r$error)) stop(r$error); r$value },
      convert = rpx_get_handle(req$handle),
      release = { if (exists(req$handle, envir = .rpx_state$handles)) rm(list = req$handle, envir = .rpx_state$handles); NULL },
      save = { saveRDS(rpx_get_handle(req$handle), req$path); req$path },
      plot_save = { rpx_save_plot(rpx_get_handle(req$handle), req$path, req$width %||% 8, req$height %||% 6, req$dpi %||% 150); req$path },
      stop("unknown callback ", req$what))
    list(op = "callback_result", ok = TRUE, value = if (identical(req$what, "convert")) rpx_encode(val) else rpx_encode(val))
  }, error = function(e) list(op = "callback_result", ok = FALSE, error = conditionMessage(e)))
  py_send(s, res)
}

#' Low-level request to the Python worker (returns the decoded reply list).
py_request <- function(s, msg) {
  if (!isTRUE(s$alive)) stop("Python session is closed; start a new one with python()")
  if (!is.null(msg$what) && is.null(msg$op)) { msg$op <- msg$what; msg$what <- NULL }
  s$id <- s$id + 1L
  msg$id <- s$id
  py_send(s, msg)
  repeat {
    reply <- py_read(s)
    if (is.null(reply)) stop("Python worker terminated. Log:\n", paste(utils::tail(readLines(s$log, warn = FALSE), 20), collapse = "\n"))
    if (identical(reply$op, "callback")) { py_serve_callback(s, reply); next }
    if (identical(reply$id, s$id)) {
      if (isFALSE(reply$ok)) {
        stop(structure(class = c("rpython_python_error", "error", "condition"),
                       list(message = paste0("Python error: ", reply$error, "\n", if (!is.null(reply$traceback)) paste(utils::tail(strsplit(reply$traceback, "\n")[[1]], 6), collapse = "\n") else ""),
                            call = NULL, traceback = reply$traceback, stdout = reply$stdout)))
      }
      if (!is.null(reply$stdout) && nzchar(reply$stdout)) cat(reply$stdout)
      for (w in reply$warnings %||% list()) warning(w, call. = FALSE)
      if (!is.null(reply$value)) return(rpx_decode(reply$value))
      return(reply)
    }
  }
}

#' Run Python code; returns the value of the last expression (converted) or a proxy.
#' @export
py_run <- function(s, code, convert = TRUE) {
  r <- py_request(s, list(op = "eval", code = paste(code, collapse = "\n"), convert = convert, plots = TRUE))
  r
}

#' Run Python code and return the full result list (value, stdout, warnings, plots).
#' @export
py_eval <- function(s, code, convert = TRUE) {
  if (!isTRUE(s$alive)) stop("Python session is closed")
  s$id <- s$id + 1L
  py_send(s, list(id = s$id, op = "eval", code = paste(code, collapse = "\n"), convert = convert, plots = TRUE))
  repeat {
    reply <- py_read(s)
    if (is.null(reply)) stop("Python worker terminated")
    if (identical(reply$op, "callback")) { py_serve_callback(s, reply); next }
    if (identical(reply$id, s$id)) {
      if (isFALSE(reply$ok)) stop("Python error: ", reply$error)
      return(list(value = rpx_decode(reply$value), stdout = reply$stdout, warnings = unlist(reply$warnings), plots = unlist(reply$plots), visible = reply$visible))
    }
  }
}

#' Import a Python package/module as a proxy: `np <- py$package("numpy"); np$arange(3)`.
#' @export
py_package <- function(s, name) {
  r <- py_request(s, list(op = "import", module = name))
  structure(list(), handle = r$handle, pyclass = "module", module = name, methods = unlist(r$exports), attributes = character(),
            repr = paste0("<module '", name, "' ", r$version %||% "", ">"), class = "rpx_pyproxy")
}

#' @export
py_assign <- function(s, name, value) { py_request(s, list(op = "assign", name = name, value = rpx_encode(value))); invisible(NULL) }

#' @export
py_get <- function(s, name, convert = TRUE) py_request(s, list(op = "get", name = name, convert = convert))

#' Install Python packages with pip (or uv/conda via `source`).
#' @export
py_install <- function(s, ..., source = "pip") {
  r <- py_request(s, list(op = "install", packages = list(...), source = source))
  if (!isTRUE(r$ok)) stop("Python package installation failed:\n", r$error)
  invisible(TRUE)
}

py_call_fn <- function(s, fn, ...) {
  args <- list(...); nms <- names(args); if (is.null(nms)) nms <- rep("", length(args))
  py_request(s, list(op = "call", fn = fn, args = lapply(unname(args[nms == ""]), rpx_encode), kwargs = lapply(args[nms != ""], rpx_encode)))
}

#' @export
py_close <- function(s) {
  if (isTRUE(s$alive)) {
    tryCatch(py_send(s, list(id = s$id + 1L, op = "shutdown")), error = function(e) NULL)
    tryCatch(close(s$con), error = function(e) NULL)
    s$alive <- FALSE
  }
  if (identical(.rpx_state$py, s)) .rpx_state$py <- NULL
  invisible(NULL)
}

#' Explain the last transfer (R side): what representation was chosen and why.
#' @export
rpx_explain <- function(x) {
  env <- rpx_encode(x)
  cat("Kind:", env$kind, "\n")
  if (!is.null(env$meta$source_class)) cat("Source class:", env$meta$source_class, "\n")
  if (!is.null(env$arrow)) cat("Transfer: Arrow IPC file\n") else cat("Transfer: JSON\n")
  if (!is.null(env$semantics) && length(env$semantics)) cat("Semantic blocks:", paste(names(env$semantics), collapse = ", "), "\n")
  if (identical(env$kind, "proxy")) cat("No native Python representation: object stays in R behind a proxy\n")
  invisible(env)
}
