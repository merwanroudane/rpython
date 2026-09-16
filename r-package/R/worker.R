# worker.R -- the R side of the RPython worker protocol.
#
# Transport: newline-delimited JSON.  Every protocol line is prefixed with
# "@RPX@" so stray output from user code can never be mistaken for a
# message.  Two transports are supported:
#   * stdio  (Python launches Rscript and talks over stdin/stdout)
#   * socket (R started standalone: rpython_worker(port = ...))
#
# Request  : {"id": n, "op": "...", ...}
# Response : {"id": n, "ok": true, ...} | {"id": n, "ok": false, "error": "...", ...}
# Callback : worker -> client {"op": "callback", ...}; client answers with
#            {"op": "callback_result", ...} before the original response.


rpx_json <- function(x) {
  jsonlite::toJSON(x, auto_unbox = TRUE, null = "null", na = "null", digits = I(17), force = TRUE, POSIXt = "ISO8601")
}

rpx_send <- function(msg) {
  line <- paste0("@RPX@", rpx_json(msg))
  writeLines(line, con = .rpx_state$conn_out, useBytes = TRUE)
  flush(.rpx_state$conn_out)
}

# Python -> R frames are length-prefixed ("@RPX@<nbytes>" newline payload-bytes): stdin line
# reading on Windows can hand back partial lines for multi-megabyte messages, byte counts cannot.
rpx_read_header <- function(con) {
  buf <- raw(0)
  repeat {
    b <- readBin(con, "raw", 1L)
    if (!length(b)) return(NULL)
    if (b == as.raw(10L)) break
    buf <- c(buf, b)
  }
  rawToChar(buf)
}

rpx_read_payload <- function(con, n) {
  out <- raw(0)
  while (length(out) < n) {
    chunk <- readBin(con, "raw", n - length(out))
    if (!length(chunk)) return(NULL)
    out <- c(out, chunk)
  }
  s <- rawToChar(out)
  Encoding(s) <- "UTF-8"
  s
}

rpx_read_frame <- function(con) {
  repeat {
    header <- rpx_read_header(con)
    if (is.null(header)) return(NULL)                     # EOF: client went away
    if (!startsWith(header, "@RPX@")) next                # stray output line: skip
    n <- suppressWarnings(as.integer(substring(header, 6L)))
    if (is.na(n)) {                                       # legacy single-line frame
      return(jsonlite::fromJSON(substring(header, 6L), simplifyVector = FALSE))
    }
    payload <- rpx_read_payload(con, n)
    if (is.null(payload)) return(NULL)
    return(jsonlite::fromJSON(payload, simplifyVector = FALSE))
  }
}

rpx_read <- function() rpx_read_frame(.rpx_state$conn_in)

#' Ask the client (Python) to do something and wait for the answer.
rpx_callback <- function(msg) {
  msg$op <- "callback"
  rpx_send(msg)
  repeat {
    reply <- rpx_read()
    if (is.null(reply)) stop("connection to Python closed during callback")
    if (identical(reply$op, "callback_result")) {
      if (isTRUE(reply$ok)) return(rpx_decode(reply$value))
      stop("Python error: ", reply$error)
    }
    # nested request from the client while we wait (rare): serve it
    rpx_handle(reply)
  }
}

# ---------------------------------------------------------------------------
# evaluation with capture of stdout / messages / warnings / plots / errors
# ---------------------------------------------------------------------------

rpx_open_plot_device <- function() {
  path <- rpx_new_file("_%03d.png")
  grDevices::png(path, width = 900, height = 650, res = 110)
  .rpx_state$plot_dev <- grDevices::dev.cur()
  .rpx_state$plot_path <- path
  .rpx_state$plot_drawn <- FALSE
  # hooks fire on every new page (base graphics and grid/ggplot2)
  setHook("plot.new", function() .rpx_state$plot_drawn <- TRUE, action = "replace")
  setHook("grid.newpage", function() .rpx_state$plot_drawn <- TRUE, action = "replace")
}

rpx_close_plot_device <- function() {
  out <- character()
  if (!is.null(.rpx_state$plot_dev) && .rpx_state$plot_dev %in% grDevices::dev.list()) {
    grDevices::dev.off(.rpx_state$plot_dev)
    files <- Sys.glob(sub("_%03d.png$", "_*.png", .rpx_state$plot_path))
    if (isTRUE(.rpx_state$plot_drawn)) out <- files[file.info(files)$size > 0] else unlink(files)
  }
  setHook("plot.new", NULL, action = "replace")
  setHook("grid.newpage", NULL, action = "replace")
  .rpx_state$plot_dev <- NULL
  out
}

rpx_eval <- function(code, envir = NULL, capture = TRUE, plots = TRUE) {
  envir <- envir %||% rpx_user_env()
  msgs <- character(); warns <- character(); out_lines <- character()
  err <- NULL; tb <- NULL; value <- NULL; visible <- FALSE
  exprs <- tryCatch(parse(text = code, keep.source = FALSE), error = function(e) { err <<- e; NULL })
  if (is.null(err)) {
    if (plots) rpx_open_plot_device()
    out_lines <- utils::capture.output({
      res <- withCallingHandlers(
        tryCatch({
          r <- NULL
          for (ex in exprs) r <- withVisible(eval(ex, envir))
          r
        }, error = function(e) {
          err <<- e
          tb <<- tryCatch(paste(utils::limitedLabels(sys.calls()), collapse = "\n"), error = function(x) NULL)
          NULL
        }),
        message = function(m) { msgs <<- c(msgs, sub("
$", "", conditionMessage(m))); invokeRestart("muffleMessage") },
        warning = function(w) { warns <<- c(warns, conditionMessage(w)); invokeRestart("muffleWarning") })
      if (!is.null(res)) { value <- res$value; visible <- res$visible }
      # auto-print ggplot / lattice / htmlwidget results so they hit the device
      if (visible && plots && (inherits(value, "ggplot") || inherits(value, "trellis") || inherits(value, "recordedplot"))) {
        print(value)
      }
    }, type = "output")
    plot_files <- if (plots) rpx_close_plot_device() else character()
  } else {
    plot_files <- character()
  }
  list(value = value, visible = visible, stdout = paste(out_lines, collapse = "\n"), messages = msgs, warnings = warns,
       error = err, traceback = tb, plots = plot_files)
}

rpx_user_env <- function() {
  if (is.null(.rpx_state$user_env)) .rpx_state$user_env <- new.env(parent = globalenv())
  .rpx_state$user_env
}

rpx_error_payload <- function(id, e, tb = NULL, where = "R") {
  list(id = id, ok = FALSE, error = conditionMessage(e), runtime = where,
       call = tryCatch(paste(deparse(conditionCall(e)), collapse = " "), error = function(x) NULL),
       class = class(e), traceback = tb)
}

# ---------------------------------------------------------------------------
# request handlers
# ---------------------------------------------------------------------------

rpx_capabilities <- function() {
  pk <- c("arrow", "nanoarrow", "data.table", "tibble", "sf", "terra", "stars", "igraph", "tidygraph", "Matrix", "zoo", "xts",
          "tsibble", "haven", "survival", "plm", "quanteda", "spdep", "bit64", "DBI", "RSQLite", "duckdb", "dbplyr", "dplyr",
          "ggplot2", "jsonlite", "R6", "magick", "tuneR", "ncdf4", "fda", "ape", "SummarizedExperiment")
  have <- vapply(pk, rpx_has, logical(1))
  list(r_version = as.character(getRversion()), r_home = R.home(), platform = R.version$platform,
       packages = as.list(have), workdir = rpx_workdir(), pid = Sys.getpid(), locale = Sys.getlocale("LC_CTYPE"),
       timezone = Sys.timezone(), encoding = "UTF-8", arrow = isTRUE(have[["arrow"]]),
       rpython_version = "0.1.0")
}

rpx_handle <- function(req) {
  id <- req$id
  op <- req$op
  res <- tryCatch({
    switch(op,
      hello = {
        .rpx_state$peer_arrow <- isTRUE(req$arrow)
        if (!is.null(req$transfer)) .rpx_state$transfer <- req$transfer
        if (!is.null(req$arrow_threshold_rows)) .rpx_state$arrow_threshold_rows <- as.integer(req$arrow_threshold_rows)
        if (!is.null(req$workdir)) { .rpx_state$workdir <- req$workdir; dir.create(req$workdir, showWarnings = FALSE, recursive = TRUE) }
        c(list(id = id, ok = TRUE), rpx_capabilities())
      },
      eval = {
        r <- rpx_eval(req$code, capture = !isFALSE(req$capture), plots = !isFALSE(req$plots))
        if (!is.null(r$error)) {
          p <- rpx_error_payload(id, r$error, r$traceback)
          p$stdout <- r$stdout; p$messages <- r$messages; p$warnings <- r$warnings
          p
        } else {
          val <- if (isFALSE(req$convert)) rpx_encode_proxy(r$value) else if (r$visible || isTRUE(req$value)) rpx_encode(r$value) else list(rpx = 1L, kind = "null")
          list(id = id, ok = TRUE, value = val, visible = r$visible, stdout = r$stdout, messages = as.list(r$messages),
               warnings = as.list(r$warnings), plots = as.list(r$plots))
        }
      },
      assign = {
        assign(req$name, rpx_decode(req$value), envir = rpx_user_env())
        list(id = id, ok = TRUE)
      },
      get = {
        val <- get(req$name, envir = rpx_user_env())
        list(id = id, ok = TRUE, value = if (isFALSE(req$convert)) rpx_encode_proxy(val) else rpx_encode(val))
      },
      exists = list(id = id, ok = TRUE, value = exists(req$name, envir = rpx_user_env())),
      call = {
        fn <- rpx_resolve_function(req$fn)
        args <- lapply(req$args %||% list(), rpx_decode)
        kwargs <- lapply(req$kwargs %||% list(), rpx_decode)
        r <- rpx_eval_call(fn, c(args, kwargs), plots = !isFALSE(req$plots))
        if (!is.null(r$error)) rpx_error_payload(id, r$error, r$traceback) else
          list(id = id, ok = TRUE, value = if (isFALSE(req$convert)) rpx_encode_proxy(r$value) else rpx_encode(r$value),
               stdout = r$stdout, messages = as.list(r$messages), warnings = as.list(r$warnings), plots = as.list(r$plots))
      },
      method = {
        obj <- rpx_get_handle(req$handle)
        args <- lapply(req$args %||% list(), rpx_decode)
        kwargs <- lapply(req$kwargs %||% list(), rpx_decode)
        r <- rpx_call_method(obj, req$method, args, kwargs, plots = !isFALSE(req$plots))
        if (!is.null(r$error)) rpx_error_payload(id, r$error, r$traceback) else
          list(id = id, ok = TRUE, value = if (isFALSE(req$convert)) rpx_encode_proxy(r$value) else rpx_encode(r$value),
               stdout = r$stdout, messages = as.list(r$messages), warnings = as.list(r$warnings), plots = as.list(r$plots))
      },
      field = {
        obj <- rpx_get_handle(req$handle)
        val <- rpx_get_field(obj, req$name)
        list(id = id, ok = TRUE, value = if (isFALSE(req$convert)) rpx_encode_proxy(val) else rpx_encode(val))
      },
      describe = {
        obj <- rpx_get_handle(req$handle)
        p <- rpx_encode_proxy(obj)
        p$handle <- req$handle
        list(id = id, ok = TRUE, value = p)
      },
      convert = {
        obj <- rpx_get_handle(req$handle)
        list(id = id, ok = TRUE, value = rpx_encode_force(obj))
      },
      release = { if (exists(req$handle, envir = .rpx_state$handles)) rm(list = req$handle, envir = .rpx_state$handles); list(id = id, ok = TRUE) },
      library = {
        ok <- suppressPackageStartupMessages(requireNamespace(req$package, quietly = TRUE))
        if (!ok) stop("R package '", req$package, "' is not installed")
        exports <- tryCatch(getNamespaceExports(req$package), error = function(e) character())
        list(id = id, ok = TRUE, exports = as.list(sort(exports)), version = as.character(utils::packageVersion(req$package)))
      },
      installed = list(id = id, ok = TRUE, value = as.list(rownames(utils::installed.packages())[rownames(utils::installed.packages()) %in% unlist(req$packages)])),
      install = {
        pk <- unlist(req$packages)
        r <- rpx_eval(rpx_install_code(pk, req$source %||% "cran", req$repos), plots = FALSE)
        ok <- all(vapply(pk, rpx_has, logical(1)))
        if (!is.null(r$error)) rpx_error_payload(id, r$error) else
          list(id = id, ok = ok, stdout = r$stdout, messages = as.list(r$messages), warnings = as.list(r$warnings),
               error = if (!ok) "installation finished but package(s) still not loadable" else NULL)
      },
      signature = {
        fn <- rpx_resolve_function(req$fn)
        f <- formals(fn)
        list(id = id, ok = TRUE, value = list(args = as.list(names(f)),
                                             defaults = lapply(f, function(d) if (is.symbol(d) && !nzchar(as.character(d))) NULL else paste(deparse(d), collapse = " ")),
                                             doc = rpx_help_text(req$fn)))
      },
      plot_save = {
        obj <- rpx_get_handle(req$handle)
        path <- req$path
        rpx_save_plot(obj, path, req$width %||% 8, req$height %||% 6, req$dpi %||% 150)
        list(id = id, ok = TRUE, path = path)
      },
      save = {
        obj <- if (!is.null(req$handle)) rpx_get_handle(req$handle) else rpx_decode(req$value)
        saveRDS(obj, req$path)
        list(id = id, ok = TRUE, path = req$path)
      },
      load = {
        obj <- readRDS(req$path)
        list(id = id, ok = TRUE, value = if (isFALSE(req$convert)) rpx_encode_proxy(obj) else rpx_encode(obj))
      },
      setenv = { args <- list(req$value); names(args) <- req$name; do.call(Sys.setenv, args); list(id = id, ok = TRUE) },
      ping = list(id = id, ok = TRUE, value = "pong"),
      shutdown = { .rpx_state$stop <- TRUE; list(id = id, ok = TRUE) },
      stop("unknown op: ", op))
  }, error = function(e) rpx_error_payload(id, e))
  rpx_send(res)
  invisible(res)
}

rpx_resolve_function <- function(spec) {
  if (is.list(spec) && !is.null(spec$handle)) return(rpx_get_handle(spec$handle))
  if (grepl("::", spec, fixed = TRUE)) {
    parts <- strsplit(spec, ":::?", perl = TRUE)[[1]]
    return(getExportedValue(parts[1], parts[2]))
  }
  get(spec, envir = rpx_user_env(), mode = "function")
}

rpx_eval_call <- function(fn, args, plots = TRUE) {
  r <- rpx_eval("NULL", plots = FALSE)  # placeholder structure
  msgs <- character(); warns <- character(); err <- NULL; tb <- NULL; value <- NULL
  if (plots) rpx_open_plot_device()
  out <- utils::capture.output({
    value <- withCallingHandlers(
      tryCatch(do.call(fn, args), error = function(e) { err <<- e; tb <<- tryCatch(paste(utils::limitedLabels(sys.calls()), collapse = "\n"), error = function(x) NULL); NULL }),
      message = function(m) { msgs <<- c(msgs, sub("
$", "", conditionMessage(m))); invokeRestart("muffleMessage") },
      warning = function(w) { warns <<- c(warns, conditionMessage(w)); invokeRestart("muffleWarning") })
    if (plots && (inherits(value, "ggplot") || inherits(value, "trellis"))) print(value)
  }, type = "output")
  plot_files <- if (plots) rpx_close_plot_device() else character()
  list(value = value, stdout = paste(out, collapse = "\n"), messages = msgs, warnings = warns, error = err, traceback = tb, plots = plot_files)
}

rpx_call_method <- function(obj, method, args, kwargs, plots = TRUE) {
  fn <- NULL
  if (inherits(obj, "R6") && is.function(obj[[method]])) fn <- obj[[method]]
  else if (is.environment(obj) && exists(method, envir = obj) && is.function(get(method, envir = obj))) fn <- get(method, envir = obj)
  if (!is.null(fn)) return(rpx_eval_call(fn, c(args, kwargs), plots = plots))
  # S3/S4 generic: method(obj, ...)
  generic <- tryCatch(get(method, mode = "function"), error = function(e) NULL)
  if (is.null(generic)) {
    # try namespaces of the object's class packages
    for (ns in loadedNamespaces()) {
      if (exists(method, envir = asNamespace(ns), inherits = FALSE)) { generic <- get(method, envir = asNamespace(ns)); break }
    }
  }
  if (is.null(generic)) stop("no function or method named '", method, "' for object of class ", paste(class(obj), collapse = "/"))
  rpx_eval_call(generic, c(list(obj), args, kwargs), plots = plots)
}

rpx_get_field <- function(obj, name) {
  if (isS4(obj) && name %in% methods::slotNames(obj)) return(methods::slot(obj, name))
  if (is.environment(obj)) return(get(name, envir = obj))
  if (is.list(obj) && !is.null(names(obj)) && name %in% names(obj)) return(obj[[name]])
  if (!is.null(attr(obj, name))) return(attr(obj, name))
  if (is.list(obj) && grepl("^[0-9]+$", name)) return(obj[[as.integer(name)]])
  stop("object of class ", paste(class(obj), collapse = "/"), " has no field '", name, "'")
}

rpx_install_code <- function(pk, source, repos = NULL) {
  repos <- repos %||% "https://cloud.r-project.org"
  switch(source,
         cran = sprintf("utils::install.packages(c(%s), repos = %s, quiet = TRUE)", paste(sprintf("'%s'", pk), collapse = ","), sprintf("'%s'", repos)),
         github = sprintf("if (!requireNamespace('remotes', quietly = TRUE)) utils::install.packages('remotes', repos = '%s', quiet = TRUE); remotes::install_github(c(%s), quiet = TRUE)", repos, paste(sprintf("'%s'", pk), collapse = ",")),
         bioc = sprintf("if (!requireNamespace('BiocManager', quietly = TRUE)) utils::install.packages('BiocManager', repos = '%s', quiet = TRUE); BiocManager::install(c(%s), ask = FALSE, update = FALSE, quiet = TRUE)", repos, paste(sprintf("'%s'", pk), collapse = ",")),
         local = sprintf("utils::install.packages(c(%s), repos = NULL, type = 'source', quiet = TRUE)", paste(sprintf("'%s'", pk), collapse = ",")),
         stop("unknown package source: ", source))
}

rpx_help_text <- function(spec) {
  tryCatch({
    parts <- strsplit(spec, ":::?", perl = TRUE)[[1]]
    if (length(parts) != 2) return(NULL)
    db <- tools::Rd_db(parts[1])
    tag_alias <- paste0(intToUtf8(92L), "alias")
    hit <- NULL
    for (nm in names(db)) {
      rd <- db[[nm]]
      aliases <- unlist(lapply(rd, function(el) if (identical(attr(el, "Rd_tag"), tag_alias)) as.character(el[[1]]) else NULL))
      if (parts[2] %in% aliases) { hit <- rd; break }
    }
    if (is.null(hit)) return(NULL)
    txt <- utils::capture.output(tools::Rd2txt(hit, options = list(underline_titles = FALSE)))
    paste(utils::head(txt, 60), collapse = intToUtf8(10L))
  }, error = function(e) NULL)
}

rpx_save_plot <- function(obj, path, width, height, dpi) {
  ext <- tolower(tools::file_ext(path))
  if (inherits(obj, "ggplot") && rpx_has("ggplot2")) { ggplot2::ggsave(path, obj, width = width, height = height, dpi = dpi); return(invisible(path)) }
  if (inherits(obj, "htmlwidget")) { rpx_require("htmlwidgets"); htmlwidgets::saveWidget(obj, path, selfcontained = TRUE); return(invisible(path)) }
  dev <- switch(ext, png = function() grDevices::png(path, width = width, height = height, units = "in", res = dpi),
                svg = function() grDevices::svg(path, width = width, height = height),
                pdf = function() grDevices::pdf(path, width = width, height = height),
                jpg = , jpeg = function() grDevices::jpeg(path, width = width, height = height, units = "in", res = dpi),
                stop("unsupported plot format: ", ext))
  dev(); on.exit(grDevices::dev.off())
  if (inherits(obj, "recordedplot")) grDevices::replayPlot(obj) else print(obj)
  invisible(path)
}

# ---------------------------------------------------------------------------
# entry points
# ---------------------------------------------------------------------------

#' Run the RPython worker loop over stdio (used by the Python package).
#' @export
rpython_worker <- function(port = NULL, host = "127.0.0.1") {
  if (is.null(port)) {
    .rpx_state$conn_in <- file("stdin", open = "rb", blocking = TRUE)
    .rpx_state$conn_out <- stdout()
  } else {
    con <- socketConnection(host = host, port = as.integer(port), server = FALSE, blocking = TRUE, open = "r+b", encoding = "UTF-8")
    .rpx_state$conn_in <- con
    .rpx_state$conn_out <- con
  }
  options(warn = 1, encoding = "UTF-8", device = "png")
  .rpx_state$stop <- FALSE
  rpx_send(list(op = "ready", pid = Sys.getpid()))
  repeat {
    req <- rpx_read()
    if (is.null(req)) break
    rpx_handle(req)
    if (isTRUE(.rpx_state$stop)) break
  }
  invisible(NULL)
}

#' Register a custom encoder / decoder for a class (extension API, section 55).
#' @export
rpx_register_encoder <- function(detect, encode) {
  .rpx_state$encoders <- c(.rpx_state$encoders, list(list(detect = detect, encode = encode)))
  invisible(NULL)
}

#' @export
rpx_register_decoder <- function(kind, decode) {
  .rpx_state$decoders[[kind]] <- decode
  invisible(NULL)
}
