# rpx_encode.R -- R object  ->  portable envelope (RPX v1)
#
# The envelope is a plain R list that serialises to the JSON understood by
# the Python package (src/rpython/data/*.py).  Special values are explicit:
# double NA -> "NA", NaN -> "NaN", Inf -> "Inf"/"-Inf"; other NA -> NULL.
# Large payloads are written as Arrow IPC files when the arrow package is
# available and the receiver announced Arrow capability.


rpx_workdir <- function() {
  if (is.null(.rpx_state$workdir)) {
    .rpx_state$workdir <- file.path(tempdir(), "rpython")
    dir.create(.rpx_state$workdir, showWarnings = FALSE, recursive = TRUE)
  }
  .rpx_state$workdir
}

rpx_new_file <- function(ext) {
  file.path(rpx_workdir(), paste0(paste(sample(c(letters, 0:9), 16, TRUE), collapse = ""), ext))
}

# installed? (does NOT load the namespace -- loading happens lazily on first use via ::)
rpx_has <- function(pkg) nzchar(system.file(package = pkg))

rpx_use_arrow <- function(nrow) {
  if (identical(.rpx_state$transfer, "json")) return(FALSE)
  if (!rpx_has("arrow") || !isTRUE(.rpx_state$peer_arrow)) return(FALSE)
  if (identical(.rpx_state$transfer, "arrow")) return(TRUE)
  nrow >= .rpx_state$arrow_threshold_rows
}

# ---------------------------------------------------------------------------
# scalar / vector helpers
# ---------------------------------------------------------------------------

rpx_double_values <- function(x) {
  x <- as.double(x)
  if (!anyNA(x) && !any(is.infinite(x))) return(as.list(x))
  out <- as.list(x)
  na  <- is.na(x) & !is.nan(x)
  nan <- is.nan(x)
  pinf <- is.infinite(x) & x > 0
  ninf <- is.infinite(x) & x < 0
  out[na]   <- list("NA")
  out[nan]  <- list("NaN")
  out[pinf] <- list("Inf")
  out[ninf] <- list("-Inf")
  out
}

rpx_null_na <- function(x) {
  out <- as.list(x)
  out[is.na(x)] <- list(NULL)
  out
}

rpx_tz <- function(x) {
  tz <- attr(x, "tzone")
  if (isTRUE(attr(x, "rpython_naive"))) return("naive")
  if (is.null(tz) || identical(tz, "")) {
    return(Sys.timezone())
  }
  tz[1]
}

rpx_datetime_values <- function(x) {
  tz <- rpx_tz(x)
  if (identical(tz, "naive")) {
    s <- format(x, "%Y-%m-%dT%H:%M:%OS6", tz = "UTC")
  } else {
    s <- format(x, "%Y-%m-%dT%H:%M:%OS6%z", tz = tz)
    s <- sub("([+-]\\d{2})(\\d{2})$", "\\1:\\2", s)
  }
  out <- as.list(s)
  out[is.na(x)] <- list(NULL)
  out
}

rpx_atomic_type <- function(x) {
  if (inherits(x, "rpx_decimal")) return("decimal")
  if (inherits(x, "rpx_fraction")) return("fraction")
  if (inherits(x, "rpx_uuid")) return("uuid")
  if (inherits(x, "integer64")) return("int64")
  if (inherits(x, "Date")) return("date")
  if (inherits(x, "POSIXct")) return("datetime")
  if (inherits(x, "difftime")) return("timedelta")
  if (is.factor(x)) return("factor")
  switch(typeof(x),
         logical = "logical", integer = "integer", double = "double", complex = "complex",
         character = "character", raw = "raw", stop("unsupported atomic type: ", typeof(x)))
}

rpx_atomic_values <- function(x, type) {
  switch(type,
         logical = rpx_null_na(x),
         integer = rpx_null_na(x),
         int64 = { s <- as.character(x); rpx_null_na(ifelse(is.na(x), NA_character_, s)) },
         double = rpx_double_values(x),
         complex = lapply(seq_along(x), function(i) if (is.na(x[i])) NULL else list(rpx_double_values(Re(x[i]))[[1]], rpx_double_values(Im(x[i]))[[1]])),
         character = rpx_null_na(x),
         raw = list(jsonlite::base64_enc(x)),
         decimal = rpx_null_na(as.character(x)),
         fraction = rpx_null_na(as.character(x)),
         uuid = rpx_null_na(as.character(x)),
         date = rpx_null_na(format(x, "%Y-%m-%d")),
         datetime = rpx_datetime_values(x),
         timedelta = rpx_double_values(as.numeric(x, units = "secs")),
         factor = rpx_null_na(as.character(x)),
         stop("unsupported type ", type))
}

rpx_semantic_for <- function(x, type) {
  sem <- list()
  if (type == "factor") sem$categorical <- list(levels = as.list(levels(x)), ordered = is.ordered(x))
  if (type == "datetime") sem$datetime <- list(tz = rpx_tz(x))
  if (type == "timedelta") sem$timedelta <- list(units = attr(x, "units"))
  if (inherits(x, "haven_labelled") || !is.null(attr(x, "labels")) || !is.null(attr(x, "label"))) {
    sem$labelled <- TRUE
  }
  sem
}

rpx_user_attrs <- function(x, drop = c("names", "dim", "dimnames", "class", "row.names", "tzone", "levels", "units",
                                       "comment", "index", "tsp", "sf_column", "agr", "rpython_naive", "label", "labels",
                                       "na_values", "na_range", ".internal.selfref", "sorted")) {
  a <- attributes(x)
  a <- a[setdiff(names(a), drop)]
  a <- a[!startsWith(names(a), "rpython")]
  if (!length(a)) return(list())
  a <- Filter(function(v) is.atomic(v) && length(v) <= 1000, a)
  lapply(a, function(v) if (length(v) == 1) unname(v) else as.list(v))
}

# ---------------------------------------------------------------------------
# main dispatcher
# ---------------------------------------------------------------------------

# Forced conversion (proxy$to_python()): S3 objects built on lists become plain lists
# recursively; the class vector travels in meta so nothing is silently lost.
rpx_encode_force <- function(x) {
  if (is.list(x) && !is.data.frame(x) && !is.null(attr(x, "class")) && !inherits(x, c("sf", "igraph", "Surv", "ts", "xts", "zoo", "R6"))) {
    cls <- class(x)
    y <- unclass(x)
    attr(y, "rpython_class") <- paste(cls, collapse = "/")
    items <- lapply(seq_along(y), function(i) rpx_encode_force(y[[i]]))
    nm <- names(y)
    return(list(rpx = 1L, kind = "list", items = items, names = if (is.null(nm)) NULL else as.list(nm),
                meta = list(source_class = paste(cls, collapse = "/"), r_class = as.list(cls), forced = TRUE)))
  }
  if (is.function(x) || is.environment(x) || isS4(x)) return(rpx_encode_proxy(x))
  if (is.language(x)) return(list(rpx = 1L, kind = "vector", type = "character", values = as.list(paste(deparse(x), collapse = " ")),
                                  names = NULL, scalar = TRUE, meta = list(source_class = "language")))
  rpx_encode(x, top = FALSE)
}

rpx_encode <- function(x, top = TRUE) {
  if (is.null(x)) return(list(rpx = 1L, kind = "null"))
  if (inherits(x, "rpx_pyfunction")) return(list(rpx = 1L, kind = "proxy", runtime = "python", handle = attr(x, "handle"),
                                                callable = TRUE, class = list("function"), meta = list(source_class = "python callable (returned)")))
  if (inherits(x, "rpx_pyproxy")) return(list(rpx = 1L, kind = "proxy", runtime = "python", handle = attr(x, "handle"),
                                             class = as.list(attr(x, "pyclass")), module = attr(x, "module"),
                                             meta = list(source_class = "python proxy (returned)")))
  # ---- registered custom encoders (rpx_register_encoder) ----
  for (enc in .rpx_state$encoders) {
    if (isTRUE(tryCatch(enc$detect(x), error = function(e) FALSE))) return(enc$encode(x))
  }
  # ---- domain objects (checked before generic classes) ----
  if (inherits(x, "sf")) return(rpx_encode_sf(x))
  if (inherits(x, "sfc") || inherits(x, "sfg")) return(rpx_encode_sfc(x))
  if (inherits(x, "SpatRaster")) return(rpx_encode_spatraster(x))
  if (inherits(x, "RasterLayer") || inherits(x, "RasterBrick") || inherits(x, "RasterStack")) return(rpx_encode_raster_legacy(x))
  if (inherits(x, "stars") || inherits(x, "stars_proxy")) return(rpx_encode_stars(x))
  if (inherits(x, "igraph")) return(rpx_encode_igraph(x))
  if (inherits(x, "tbl_graph")) return(rpx_encode_igraph(x))
  if (inherits(x, "network")) return(rpx_encode_network_pkg(x))
  if (inherits(x, "Surv")) return(rpx_encode_surv(x))
  if (inherits(x, "dfm")) return(rpx_encode_dfm(x))
  if (inherits(x, "corpus")) return(rpx_encode_corpus(x))
  if (inherits(x, "listw")) return(rpx_encode_listw(x))
  if (inherits(x, "pdata.frame")) return(rpx_encode_pdata(x))
  if (inherits(x, "tbl_ts")) return(rpx_encode_tsibble(x))
  if (inherits(x, "ts")) return(rpx_encode_ts(x))
  if (inherits(x, "xts") || inherits(x, "zoo")) return(rpx_encode_xts(x))
  if (inherits(x, "rpython_db_relation")) return(unclass(x))
  if (inherits(x, "rpython_mixed_frequency")) return(list(rpx = 1L, kind = "mixed_frequency", series = lapply(unclass(x)[names(x) != ""], rpx_encode, top = FALSE),
                                                           target = attr(x, "rpython.target"), meta = list(source_class = "rpython_mixed_frequency")))
  if (!is.null(attr(x, "rpython.economic"))) return(rpx_encode_economic_matrix(x))
  if (!is.null(attr(x, "rpython.weights")) && !inherits(x, "listw")) return(rpx_encode_weights_matrix(x))
  if (inherits(x, "rpx_dataset")) return(rpx_encode_dataset(x))
  if (inherits(x, "ArrowObject")) return(rpx_encode_arrow(x))
  if (inherits(x, "tbl_lazy")) return(rpx_encode_lazy_tbl(x))
  if (inherits(x, "sparseMatrix")) return(rpx_encode_sparse(x))
  if (inherits(x, "rpython_raster_ref")) return(rpx_encode_raster_ref(x))
  if (inherits(x, "rpython_labeled_array")) return(rpx_encode_labeled_array(x))
  if (is.data.frame(x)) return(rpx_encode_table(x))
  if (is.factor(x)) return(rpx_encode_column(x))
  if (is.atomic(x) && !is.null(dim(x))) return(rpx_encode_array(x))
  if (is.atomic(x)) return(rpx_encode_vector(x))
  if (is.function(x)) return(rpx_encode_proxy(x))
  if (is.environment(x) && inherits(x, "R6")) return(rpx_encode_proxy(x))
  if (is.environment(x)) return(rpx_encode_proxy(x))
  if (isS4(x)) return(rpx_encode_proxy(x))
  if (is.list(x) && (is.null(attr(x, "class")) || identical(class(x), "list") || inherits(x, "rpx_plain_list"))) return(rpx_encode_list(x))
  if (is.list(x)) {
    # S3 object built on a list: keep it native (model objects etc.)
    return(rpx_encode_proxy(x))
  }
  rpx_encode_proxy(x)
}

# ---------------------------------------------------------------------------
# vectors / arrays / lists
# ---------------------------------------------------------------------------

rpx_encode_vector <- function(x) {
  type <- rpx_atomic_type(x)
  nm <- names(x)
  meta <- list(source_class = paste(class(x), collapse = "/"))
  if (type == "datetime") meta$tz <- rpx_tz(x)
  if (type == "timedelta") meta$units <- attr(x, "units")
  if (!is.null(attr(x, "rpython_container"))) meta$container <- attr(x, "rpython_container")
  sem <- rpx_semantic_for(x, type)
  if (length(sem)) meta$semantic <- sem
  if (type == "raw") {
    return(list(rpx = 1L, kind = "vector", type = "raw", values = list(jsonlite::base64_enc(x)), names = NULL,
                scalar = TRUE, meta = meta))
  }
  list(rpx = 1L, kind = "vector", type = type, values = rpx_atomic_values(x, type),
       names = if (is.null(nm)) NULL else as.list(nm),
       scalar = (length(x) == 1L && is.null(nm) && is.null(meta$container)), meta = meta)
}

rpx_encode_column <- function(x, name = "") {
  type <- rpx_atomic_type(x)
  col <- list(name = name, type = type, semantic = rpx_semantic_for(x, type), values = rpx_atomic_values(x, type))
  if (type == "factor") col$type <- "factor"
  if (inherits(x, "haven_labelled")) {
    col$semantic$labels <- list(variable = attr(x, "label"), values = as.list(setNames(as.character(attr(x, "labels")), names(attr(x, "labels")))))
  }
  list(rpx = 1L, kind = "column", column = col, names = if (is.null(names(x))) NULL else as.list(names(x)),
       nrow = length(x), meta = list(source_class = paste(class(x), collapse = "/"), series_name = if (nzchar(name)) name else NULL))
}

rpx_encode_array <- function(x) {
  type <- rpx_atomic_type(x)
  dn <- dimnames(x)
  vals <- as.vector(x)
  attributes(vals) <- NULL
  if (type %in% c("date", "datetime", "timedelta", "factor")) {
    y <- x; attributes(y) <- attributes(x)[c("class", "tzone", "units", "levels")]
    vals <- y
  }
  n <- length(vals)
  env <- list(rpx = 1L, kind = "array", dtype = type, shape = as.list(dim(x)), order = "F",
              dimnames = if (is.null(dn)) NULL else lapply(dn, function(d) if (is.null(d)) NULL else as.list(d)),
              mask = NULL, meta = list(source_class = paste(class(x), collapse = "/")))
  if (n >= 50000 && rpx_use_arrow(n) && type %in% c("double", "integer", "logical")) {
    path <- rpx_new_file(".arrow")
    arrow::write_feather(data.frame(values = vals), path, compression = "uncompressed")
    env$values <- NULL
    env$arrow <- path
  } else {
    env$values <- rpx_atomic_values(vals, type)
  }
  env
}

rpx_encode_list <- function(x) {
  nm <- names(x)
  items <- lapply(seq_along(x), function(i) rpx_encode(x[[i]], top = FALSE))
  meta <- list(source_class = "list")
  if (!is.null(attr(x, "rpython_container"))) meta$container <- attr(x, "rpython_container")
  if (!is.null(attr(x, "rpython_class"))) meta$class <- attr(x, "rpython_class")
  list(rpx = 1L, kind = "list", items = items, names = if (is.null(nm)) NULL else as.list(nm), meta = meta)
}

# ---------------------------------------------------------------------------
# tables
# ---------------------------------------------------------------------------

rpx_column_spec <- function(x, name, inline = TRUE) {
  if (is.data.frame(x)) {
    col <- list(name = name, type = "struct", semantic = list(), values = if (inline) lapply(seq_len(nrow(x)), function(i) rpx_encode_table(x[i, , drop = FALSE])) else NULL)
    return(col)
  }
  if (is.list(x) && !is.data.frame(x)) {
    col <- list(name = name, type = "list", semantic = list(), values = if (inline) lapply(x, function(v) if (is.null(v)) NULL else rpx_encode(v, top = FALSE)) else NULL)
    return(col)
  }
  if (!is.null(dim(x))) {
    col <- list(name = name, type = "list", semantic = list(matrix_column = TRUE), values = if (inline) lapply(seq_len(nrow(x)), function(i) rpx_encode(x[i, ], top = FALSE)) else NULL)
    return(col)
  }
  type <- rpx_atomic_type(x)
  sem <- rpx_semantic_for(x, type)
  if (inherits(x, "haven_labelled") || inherits(x, "haven_labelled_spss")) {
    labs <- attr(x, "labels")
    sem$labels <- list(variable = attr(x, "label"),
                       values = if (is.null(labs)) NULL else as.list(setNames(as.list(names(labs)), as.character(unname(labs)))),
                       na_values = if (is.null(attr(x, "na_values"))) NULL else as.list(attr(x, "na_values")),
                       na_range = if (is.null(attr(x, "na_range"))) NULL else as.list(attr(x, "na_range")))
    type <- if (is.numeric(unclass(x))) (if (is.integer(unclass(x))) "integer" else "double") else "character"
    x <- unclass(x); attributes(x) <- NULL
  } else if (!is.null(attr(x, "label"))) {
    sem$labels <- list(variable = attr(x, "label"))
  }
  if (type == "factor") sem$categorical <- list(levels = as.list(levels(x)), ordered = is.ordered(x))
  col <- list(name = name, type = type, semantic = sem, values = NULL)
  if (inline) col$values <- rpx_atomic_values(x, type)
  col
}

rpx_table_labels_block <- function(df) {
  vars <- list(); vals <- list(); miss <- list(); ranges <- list(); code_type <- list()
  for (nm in names(df)) {
    x <- df[[nm]]
    if (!is.null(attr(x, "label"))) vars[[nm]] <- attr(x, "label")
    labs <- attr(x, "labels")
    if (!is.null(labs)) {
      vals[[nm]] <- as.list(setNames(as.list(names(labs)), as.character(unname(labs))))
      code_type[[nm]] <- if (is.character(labs)) "character" else "double"
    }
    if (!is.null(attr(x, "na_values"))) miss[[nm]] <- as.list(attr(x, "na_values"))
    if (!is.null(attr(x, "na_range"))) ranges[[nm]] <- list(as.list(attr(x, "na_range")))
  }
  design <- attr(df, "rpython.survey")
  if (!length(vars) && !length(vals) && !length(miss) && is.null(design)) return(NULL)
  list(variables = vars, values = vals, value_code_type = code_type, missing = miss, missing_ranges = ranges, tagged = list(),
       design = if (is.null(design)) list(weight = NULL, strata = NULL, psu = NULL, fpc = NULL, replicate_weights = list(), method = NULL) else design,
       source_format = attr(df, "rpython.source_format"))
}

rpx_encode_table <- function(df, semantics = NULL, kind = "table", class_hint = NULL) {
  if (is.null(class_hint)) {
    class_hint <- if (inherits(df, "data.table")) "data.table" else if (inherits(df, "tbl_df")) "tibble" else "data.frame"
  }
  df <- as.data.frame(df, stringsAsFactors = FALSE)
  n <- nrow(df)
  use_arrow <- rpx_use_arrow(n) && rpx_arrow_encodable(df)
  cols <- lapply(names(df), function(nm) rpx_column_spec(df[[nm]], nm, inline = !use_arrow))
  rn <- attr(df, "row.names")
  row_names <- if (is.character(rn)) as.list(rn) else NULL
  attrs <- rpx_user_attrs(df)
  labels <- rpx_table_labels_block(df)
  sem <- if (is.null(semantics)) list() else semantics
  if (!is.null(labels) && is.null(sem$labels)) { sem$labels <- labels; if (kind == "table") kind <- "labelled" }
  for (block in c("panel", "timeseries", "spatial", "spatiotemporal", "text", "dyadic", "experiment", "simulation", "vintages", "roles")) {
    a <- attr(df, paste0("rpython.", block))
    if (!is.null(a) && is.null(sem[[block]])) sem[[block]] <- a
  }
  if (!is.null(sem$panel) && kind == "table") kind <- "panel"
  if (!is.null(sem$timeseries) && kind == "table") kind <- "timeseries"
  for (k in c("dyadic", "experiment", "simulation", "vintages")) if (!is.null(sem[[k]]) && kind == "table") kind <- k
  if (!is.null(sem$spatiotemporal) && kind == "spatial") kind <- "spatiotemporal"
  env <- list(rpx = 1L, kind = kind, nrow = n, columns = cols, arrow = NULL, index = NULL, row_names = row_names,
              attrs = attrs, semantics = sem,
              meta = list(source_class = paste(class(df), collapse = "/"), class_hint = class_hint, names = list()))
  if (use_arrow) {
    path <- rpx_new_file(".arrow")
    plain <- df
    for (nm in names(plain)) {
      v <- plain[[nm]]
      if (inherits(v, "haven_labelled")) { v <- unclass(v); attributes(v) <- NULL; plain[[nm]] <- v }
      if (inherits(v, "integer64")) plain[[nm]] <- as.character(v)
    }
    arrow::write_feather(plain, path, compression = "uncompressed")
    env$arrow <- path
  }
  env
}

rpx_arrow_encodable <- function(df) {
  for (nm in names(df)) {
    v <- df[[nm]]
    if (is.list(v) && !is.data.frame(v)) return(FALSE)
    if (is.complex(v) || is.raw(v) || inherits(v, "rpx_decimal") || !is.null(dim(v))) return(FALSE)
  }
  TRUE
}

# ---------------------------------------------------------------------------
# domain families
# ---------------------------------------------------------------------------

rpx_encode_sparse <- function(x) {
  if (!inherits(x, "dMatrix") && !inherits(x, "lMatrix")) x <- methods::as(x, "dMatrix")
  sym <- inherits(x, "symmetricMatrix")
  tri <- if (inherits(x, "triangularMatrix")) x@uplo else NULL
  g <- if (sym || !is.null(tri)) methods::as(x, "generalMatrix") else x
  dtype <- if (inherits(x, "lMatrix")) "logical" else "double"
  dn <- dimnames(x)
  base <- list(rpx = 1L, kind = "sparse", shape = as.list(dim(x)), dtype = dtype,
               dimnames = if (is.null(dn)) NULL else lapply(dn, function(d) if (is.null(d)) NULL else as.list(d)),
               symmetric = FALSE, triangular = tri, meta = list(source_class = class(x)[1], nnz = Matrix::nnzero(x)))
  if (inherits(g, "CsparseMatrix")) {
    base$format <- "csc"; base$indptr <- as.list(g@p); base$indices <- as.list(g@i)
  } else if (inherits(g, "RsparseMatrix")) {
    base$format <- "csr"; base$indptr <- as.list(g@p); base$indices <- as.list(g@j)
  } else {
    g <- methods::as(g, "TsparseMatrix")
    base$format <- "coo"; base$row <- as.list(g@i); base$col <- as.list(g@j)
  }
  base$data <- if (dtype == "logical") rpx_null_na(g@x) else rpx_double_values(g@x)
  base
}

rpx_encode_ts <- function(x) {
  tsp <- stats::tsp(x)
  freq <- tsp[3]
  is_mts <- !is.null(dim(x))
  df <- if (is_mts) as.data.frame(unclass(x)) else data.frame(value = as.numeric(x))
  if (!is_mts && !is.null(attr(x, "rpython_name"))) names(df) <- attr(x, "rpython_name")
  start <- stats::start(x)
  sem <- list(time = "time", value_columns = as.list(names(df)), ids = list(), frequency = NULL,
              r_frequency = freq, regular = TRUE, tz = "naive", r_start = as.list(start), r_ts = TRUE, mts = is_mts,
              n_periods = nrow(df), missing_periods = 0L, duplicate_timestamps = 0L,
              seasonal_period = if (freq > 1) freq else NULL, r_class = if (is_mts) "mts" else "ts", declared = TRUE,
              index_kind = if (freq %in% c(1, 4, 12)) "period" else "numeric")
  sem$frequency <- switch(as.character(freq), "1" = "Y", "4" = "Q", "12" = "M", NULL)
  orig <- attr(x, "rpython.timeseries")
  if (!is.null(orig)) for (k in names(orig)) sem[[k]] <- orig[[k]]   # restore the Python-side index semantics
  env <- rpx_encode_table(df, semantics = list(timeseries = sem), kind = "timeseries")
  env$meta$source_class <- if (is_mts) "mts" else "ts"
  env
}

rpx_encode_xts <- function(x) {
  idx <- zoo::index(x)
  cls <- if (inherits(x, "xts")) "xts" else "zoo"
  core <- zoo::coredata(x)
  df <- if (is.null(dim(core))) data.frame(value = core) else as.data.frame(core)
  if (ncol(df) == 1 && !is.null(attr(x, "rpython_name"))) names(df) <- attr(x, "rpython_name")
  if (ncol(df) == 1 && is.null(colnames(core)) && is.null(attr(x, "rpython_name"))) names(df) <- "value"
  tz <- if (inherits(idx, "POSIXct")) rpx_tz(idx) else "naive"
  if (inherits(idx, "Date")) idx <- as.POSIXct(format(idx), tz = "UTC")
  if (is.numeric(idx) && !inherits(idx, "POSIXct")) {
    df <- cbind(time = idx, df)
    sem <- list(time = "time", value_columns = as.list(setdiff(names(df), "time")), ids = list(), frequency = NULL,
                regular = FALSE, tz = "naive", r_class = cls, index_kind = "numeric", declared = TRUE,
                n_periods = length(idx), missing_periods = 0L, duplicate_timestamps = sum(duplicated(idx)))
  } else {
    if (identical(tz, "naive")) attr(idx, "rpython_naive") <- TRUE
    df <- cbind(time = idx, df)
    sem <- list(time = "time", value_columns = as.list(setdiff(names(df), "time")), ids = list(), frequency = NULL,
                regular = FALSE, tz = tz, r_class = cls, index_kind = "datetime", declared = TRUE, from_index = TRUE,
                n_periods = length(unique(idx)), missing_periods = 0L, duplicate_timestamps = sum(duplicated(idx)))
  }
  env <- rpx_encode_table(df, semantics = list(timeseries = sem), kind = "timeseries")
  env$meta$source_class <- cls
  env
}

rpx_encode_tsibble <- function(x) {
  idx <- as.character(tsibble::index_var(x))
  keys <- as.character(tsibble::key_vars(x))
  df <- as.data.frame(x)
  sem <- list(time = idx, value_columns = as.list(setdiff(names(df), c(idx, keys))), ids = as.list(keys),
              frequency = NULL, regular = tsibble::is_regular(x), tz = "naive", r_class = "tsibble", declared = TRUE,
              index_kind = "datetime", n_periods = length(unique(df[[idx]])), missing_periods = 0L, duplicate_timestamps = 0L)
  env <- rpx_encode_table(df, semantics = list(timeseries = sem), kind = "timeseries")
  env$meta$source_class <- "tbl_ts"
  env
}

rpx_encode_pdata <- function(x) {
  idx <- attr(x, "index")
  ids <- names(idx)
  df <- as.data.frame(x)
  for (nm in names(df)) { v <- df[[nm]]; if (inherits(v, "pseries")) { attr(v, "index") <- NULL; class(v) <- setdiff(class(v), "pseries"); df[[nm]] <- v } }
  for (nm in ids) if (!nm %in% names(df)) df[[nm]] <- idx[[nm]]
  for (nm in ids) if (is.factor(df[[nm]])) { lv <- levels(df[[nm]]); num <- suppressWarnings(as.numeric(lv)); df[[nm]] <- if (!anyNA(num)) num[as.integer(df[[nm]])] else as.character(df[[nm]]) }
  df <- df[c(ids, setdiff(names(df), ids))]
  bal <- tryCatch(plm::is.pbalanced(x), error = function(e) NA)
  sem <- list(kind = "panel", id = ids[1], time = ids[2], balanced = bal, n_entities = length(unique(df[[ids[1]]])),
              n_periods = length(unique(df[[ids[2]]])), duplicates = sum(duplicated(df[ids])), gaps = NULL,
              frequency = NULL, sorted = TRUE, r_class = "pdata.frame", roles = list())
  env <- rpx_encode_table(df, semantics = list(panel = sem), kind = "panel", class_hint = "data.frame")
  env$meta$source_class <- "pdata.frame"
  env
}

rpx_encode_sf <- function(x) {
  active <- attr(x, "sf_column")
  geom_cols <- names(x)[vapply(x, function(v) inherits(v, "sfc"), logical(1))]
  crs_by <- lapply(geom_cols, function(g) rpx_crs_block(sf::st_crs(x[[g]])))
  names(crs_by) <- geom_cols
  df <- as.data.frame(x)
  for (g in geom_cols) {
    wkb <- sf::st_as_binary(sf::st_geometry(x[[g]]))
    df[[g]] <- vapply(seq_along(wkb), function(i) if (sf::st_is_empty(x[[g]][i]) && is.na(sf::st_geometry_type(x[[g]][i]))) NA_character_ else jsonlite::base64_enc(wkb[[i]]), character(1))
  }
  types <- as.character(unique(sf::st_geometry_type(x[[active]])))
  bb <- tryCatch(as.list(unname(sf::st_bbox(x[[active]]))), error = function(e) NULL)
  sem <- list(geometry_column = active, geometry_columns = as.list(geom_cols), crs = crs_by[[active]], crs_by_column = crs_by,
              encoding = "wkb-base64", geometry_types = as.list(types), dimension = sf::st_crs(x)$IsGeographic %||% "XY",
              n_empty = sum(sf::st_is_empty(x[[active]])), n_missing = 0L, bbox = bb)
  sem$dimension <- if (any(grepl("Z", class(x[[active]][[1]])))) "XYZ" else "XY"
  env <- rpx_encode_table(df, semantics = list(spatial = sem, roles = setNames(list("geometry"), active)), kind = "spatial", class_hint = "sf")
  for (i in seq_along(env$columns)) if (env$columns[[i]]$name %in% geom_cols) {
    env$columns[[i]]$type <- "geometry"; env$columns[[i]]$semantic$geometry <- list(encoding = "wkb-base64", crs = crs_by[[env$columns[[i]]$name]])
  }
  env$meta$source_class <- "sf"
  env
}

rpx_encode_sfc <- function(x) {
  if (inherits(x, "sfg")) x <- sf::st_sfc(x)
  if (length(x) == 1) {
    return(list(rpx = 1L, kind = "geometry", wkb = jsonlite::base64_enc(sf::st_as_binary(x)[[1]]), crs = rpx_crs_block(sf::st_crs(x)),
                geometry_type = as.character(sf::st_geometry_type(x)), meta = list(source_class = "sfc")))
  }
  rpx_encode_sf(sf::st_sf(geometry = x))
}

rpx_crs_block <- function(crs) {
  if (is.null(crs) || is.na(crs)) return(NULL)
  epsg <- tryCatch(crs$epsg, error = function(e) NA)
  list(wkt = crs$wkt, epsg = if (is.na(epsg)) NULL else epsg, input = crs$input, name = tryCatch(crs$Name, error = function(e) NULL),
       is_geographic = tryCatch(isTRUE(sf::st_is_longlat(crs)), error = function(e) NULL), axis_order = "authority")
}

rpx_encode_spatraster <- function(x) {
  src <- terra::sources(x)
  src <- src[nzchar(src)]
  hdr <- list(driver = NULL, width = terra::ncol(x), height = terra::nrow(x), bands = terra::nlyr(x),
              dtype = "double", crs = rpx_crs_block(sf::st_crs(terra::crs(x))),
              transform = { e <- terra::ext(x); r <- terra::res(x); list(e[1], r[1], 0, e[4], 0, -r[2]) },
              resolution = as.list(terra::res(x)), extent = as.list(as.vector(terra::ext(x))),
              nodata = tryCatch(terra::NAflag(x)[1], error = function(e) NULL), band_names = as.list(names(x)),
              time = tryCatch(if (terra::has.time(x)) as.list(format(terra::time(x))) else NULL, error = function(e) NULL))
  if (length(src) == 1 && file.exists(src) && !terra::inMemory(x)[1]) {
    return(list(rpx = 1L, kind = "raster_ref", path = normalizePath(src), driver = NULL, header = hdr, lazy = TRUE,
                meta = list(source_class = "SpatRaster")))
  }
  vals <- terra::values(x, mat = TRUE)
  arr <- array(as.vector(vals), dim = c(terra::nrow(x), terra::ncol(x), terra::nlyr(x)))
  # terra values are row-major (cell order): reorder into rows x cols
  arr <- aperm(array(as.vector(vals), dim = c(terra::ncol(x), terra::nrow(x), terra::nlyr(x))), c(2, 1, 3))
  arr <- aperm(arr, c(3, 1, 2))
  a_env <- rpx_encode_array(arr)
  list(rpx = 1L, kind = "raster", array = a_env, geotransform = hdr$transform, crs = hdr$crs, nodata = hdr$nodata,
       bands = hdr$band_names, units = NULL, time = hdr$time, extent = hdr$extent, resolution = hdr$resolution,
       layout = "bands,rows,cols", meta = list(source_class = "SpatRaster"))
}

rpx_encode_raster_legacy <- function(x) rpx_encode_spatraster(terra::rast(x))

rpx_encode_stars <- function(x) {
  if (inherits(x, "stars_proxy")) {
    p <- unlist(x)[1]
    return(list(rpx = 1L, kind = "raster_ref", path = normalizePath(p), driver = NULL, header = list(), lazy = TRUE,
                meta = list(source_class = "stars_proxy")))
  }
  rpx_encode_spatraster(terra::rast(x))
}

rpx_encode_raster_ref <- function(x) {
  list(rpx = 1L, kind = "raster_ref", path = normalizePath(x$path), driver = x$driver, header = x$header %||% list(),
       lazy = TRUE, meta = list(source_class = "rpython_raster_ref"))
}

rpx_encode_igraph <- function(g) {
  if (inherits(g, "tbl_graph")) g <- tidygraph::as.igraph(g)
  vdf <- igraph::as_data_frame(g, what = "vertices")
  edf <- igraph::as_data_frame(g, what = "edges")
  walias <- attr(g, "rpython_weight_attr")
  if (!is.null(walias) && "weight" %in% names(edf)) edf$weight <- NULL
  if (!"name" %in% names(vdf)) vdf <- cbind(name = as.character(seq_len(igraph::vcount(g))), vdf)
  id_type <- attr(g, "rpython_id_type") %||% "character"
  if (id_type == "character" && all(grepl("^-?[0-9]+$", vdf$name))) id_type <- "integer"
  wattr <- if (!is.null(walias)) walias else if (igraph::is_weighted(g)) "weight" else NULL
  features <- list(n_nodes = igraph::vcount(g), n_edges = igraph::ecount(g),
                   weighted = !is.null(wattr), weight_attr = wattr,
                   self_loops = sum(igraph::which_loop(g)), parallel_edges = sum(igraph::which_multiple(g)),
                   bipartite = igraph::is_bipartite(g), bipartite_attr = if (igraph::is_bipartite(g)) "type" else NULL,
                   layers = if ("layer" %in% names(edf)) "layer" else NULL, temporal = if ("time" %in% names(edf)) "time" else NULL,
                   signed = if ("sign" %in% names(edf)) "sign" else NULL,
                   tree = if (igraph::ecount(g) > 0) igraph::is_tree(g) else FALSE, dag = if (igraph::is_directed(g)) igraph::is_dag(g) else NULL,
                   node_types = NULL, edge_types = NULL)
  gattr <- igraph::graph_attr(g)
  gattr <- Filter(function(v) is.atomic(v) && length(v) == 1, gattr)
  list(rpx = 1L, kind = "network", directed = igraph::is_directed(g), multigraph = igraph::any_multiple(g),
       nodes = rpx_encode_table(vdf), edges = rpx_encode_table(edf), node_id_type = id_type, id_map = NULL,
       graph_attrs = gattr, features = features,
       columns = list(source = "source", target = "target", node_id = "id", weight = features$weight_attr,
                      bipartite = features$bipartite_attr, layer = features$layers, time = features$temporal, signed = features$signed),
       meta = list(source_class = "igraph"))
}

rpx_encode_network_pkg <- function(x) {
  rpx_encode_igraph(igraph::graph_from_adjacency_matrix(as.matrix(x), mode = if (network::is.directed(x)) "directed" else "undirected"))
}

rpx_encode_surv <- function(s) {
  type <- attr(s, "type")
  m <- unclass(s)
  cols <- colnames(m)
  py_type <- switch(type, right = "right", left = "left", interval = "interval", interval2 = "interval", counting = "counting", mstate = "mstate", type)
  cols <- attr(s, "rpython.columns") %||% list(time = if (ncol(m) == 3) "start" else "time", time2 = if (ncol(m) == 3) "time2" else NULL, event = "status", id = NULL, strata = NULL)
  cov <- attr(s, "rpython.covariates")
  env <- list(rpx = 1L, kind = "survival", type = py_type, time = rpx_double_values(m[, 1]), time2 = NULL,
              event = rpx_double_values(m[, ncol(m)]), event_levels = NULL,
              id = if (is.null(attr(s, "rpython.id"))) NULL else as.list(attr(s, "rpython.id")),
              strata = if (is.null(attr(s, "rpython.strata"))) NULL else as.list(attr(s, "rpython.strata")),
              columns = cols, covariates = if (is.null(cov)) NULL else rpx_encode_table(cov),
              meta = list(source_class = "Surv", n = nrow(m)))
  if (ncol(m) == 3) env$time2 <- rpx_double_values(m[, 2])
  if (type == "mstate") {
    st <- attr(s, "states"); env$event_levels <- as.list(c("censored", st))
    env$event <- as.list(c("censored", st)[m[, ncol(m)] + 1])
  }
  env
}

rpx_encode_dfm <- function(x) {
  m <- methods::as(x, "dgCMatrix")
  env <- rpx_encode_sparse(m)
  env$dimnames <- list(as.list(rownames(x)), as.list(colnames(x)))
  list(rpx = 1L, kind = "dtm", matrix = env, docs = as.list(rownames(x)), terms = as.list(colnames(x)),
       weighting = tryCatch(x@meta$object$weight_tf$scheme %||% "count", error = function(e) "count"), orientation = "dtm",
       vocabulary = NULL, language = NULL, meta = list(source_class = "dfm"))
}

rpx_encode_corpus <- function(x) {
  df <- data.frame(doc_id = quanteda::docnames(x), text = as.character(x), stringsAsFactors = FALSE)
  dv <- quanteda::docvars(x)
  if (ncol(dv)) df <- cbind(df, dv)
  env <- rpx_encode_table(df, semantics = list(text = list(text_column = "text", doc_id = "doc_id", language = NULL, tokens = NULL,
                                                           docvars = as.list(names(dv)))), kind = "corpus")
  env$meta$source_class <- "corpus"
  env
}

rpx_encode_listw <- function(w) {
  m <- spdep::listw2mat(w)
  ids <- attr(w$neighbours, "region.id") %||% as.character(seq_len(nrow(m)))
  sm <- methods::as(Matrix::Matrix(m, sparse = TRUE), "dgCMatrix")
  env <- rpx_encode_sparse(sm)
  env$dimnames <- list(as.list(ids), as.list(ids))
  info <- attr(w, "rpython.weights") %||% list()
  list(rpx = 1L, kind = "spatial_weights", matrix = env, ids = as.list(ids), style = w$style, weights_kind = info$weights_kind %||% "custom",
       k = info$k, bandwidth = info$bandwidth, directed = !isSymmetric(m), zero_policy = isTRUE(attr(w, "zero.policy")),
       islands = as.list(ids[rowSums(m) == 0]), meta = list(source_class = "listw"))
}

rpx_encode_economic_matrix <- function(x) {
  info <- attr(x, "rpython.economic")
  y <- x; attr(y, "rpython.economic") <- NULL
  m_env <- rpx_encode(y, top = FALSE)
  list(rpx = 1L, kind = "economic_matrix", matrix = m_env, rows = as.list(rownames(x)), cols = as.list(colnames(x)),
       matrix_kind = info$matrix_kind, orientation = info$orientation, units = info$units, year = info$year,
       row_entity = info$row_entity %||% "sector", col_entity = info$col_entity %||% "sector", metadata = info$metadata %||% list(),
       meta = list(source_class = "matrix+rpython.economic"))
}

rpx_encode_weights_matrix <- function(x) {
  info <- attr(x, "rpython.weights")
  y <- x; attr(y, "rpython.weights") <- NULL
  ids <- rownames(x) %||% as.character(seq_len(nrow(x)))
  m_env <- rpx_encode(y, top = FALSE)
  rs <- if (inherits(x, "sparseMatrix")) Matrix::rowSums(x) else rowSums(x)
  list(rpx = 1L, kind = "spatial_weights", matrix = m_env, ids = as.list(ids), style = info$style %||% "B", weights_kind = info$weights_kind %||% "custom",
       k = info$k, bandwidth = info$bandwidth, directed = isTRUE(info$directed), zero_policy = isTRUE(info$zero_policy),
       islands = as.list(ids[rs == 0]), meta = list(source_class = "matrix+rpython.weights"))
}

rpx_encode_labeled_array <- function(x) {
  coords <- attr(x, "rpython.coords") %||% list()
  dims <- attr(x, "rpython.dims") %||% names(dimnames(x)) %||% paste0("dim_", seq_along(dim(x)))
  a <- x; attributes(a) <- list(dim = dim(x), dimnames = dimnames(x))
  data <- rpx_encode_array(a)
  list(rpx = 1L, kind = "labeled_array", name = attr(x, "rpython.name"), dims = as.list(dims),
       coords = lapply(coords, function(cc) list(dims = as.list(cc$dims), values = rpx_encode(cc$values, top = FALSE), attrs = cc$attrs %||% list(), dtype = cc$dtype %||% "")),
       attrs = attr(x, "rpython.attrs") %||% list(), data = data, encoding = list(), chunks = NULL,
       meta = list(source_class = "rpython_labeled_array"))
}

rpx_encode_arrow <- function(x) {
  if (inherits(x, "Dataset")) {
    files <- tryCatch(x$files, error = function(e) character())
    return(list(rpx = 1L, kind = "dataset", format = tryCatch(x$format$type, error = function(e) "parquet"), files = as.list(files),
                schema = x$schema$ToString(), meta = list(source_class = "arrow Dataset")))
  }
  if (inherits(x, "RecordBatch")) x <- arrow::arrow_table(x)
  if (inherits(x, "Table")) {
    env <- rpx_encode_table(as.data.frame(x), class_hint = "tibble")
    env$meta$source_class <- "arrow Table"
    return(env)
  }
  if (inherits(x, "ChunkedArray") || inherits(x, "Array")) return(rpx_encode(x$as_vector()))
  rpx_encode_proxy(x)
}

rpx_encode_lazy_tbl <- function(x) {
  n <- tryCatch(dplyr::pull(dplyr::count(x)), error = function(e) NA)
  src <- tryCatch(dbplyr::remote_con(x), error = function(e) NULL)
  list(rpx = 1L, kind = "lazy_relation", sql = tryCatch(as.character(dbplyr::sql_render(x)), error = function(e) NULL),
       n_rows = if (is.na(n)) NULL else n, columns = as.list(colnames(x)), backend = if (is.null(src)) "dbplyr" else class(src)[1],
       connection = rpx_connection_ref(src), lazy = TRUE, meta = list(source_class = "tbl_lazy"))
}

rpx_encode_dataset <- function(x) {
  list(rpx = 1L, kind = "dataset", format = x$format, files = as.list(x$files), schema = NULL, meta = list(source_class = "rpx_dataset"))
}

# ---------------------------------------------------------------------------
# proxies
# ---------------------------------------------------------------------------

rpx_new_handle <- function(x) {
  .rpx_state$handle_counter <- .rpx_state$handle_counter + 1L
  h <- sprintf("r_%06d", .rpx_state$handle_counter)
  assign(h, x, envir = .rpx_state$handles)
  h
}

rpx_get_handle <- function(h) {
  if (!exists(h, envir = .rpx_state$handles, inherits = FALSE)) stop("unknown R proxy handle: ", h)
  get(h, envir = .rpx_state$handles, inherits = FALSE)
}

rpx_methods_for <- function(x) {
  cls <- class(x)
  out <- character()
  for (cl in cls) {
    m <- tryCatch(suppressWarnings(as.character(utils::methods(class = cl))), error = function(e) character())
    out <- c(out, sub(paste0("\\.", cl, "$"), "", m))
  }
  if (inherits(x, "R6")) out <- c(out, setdiff(ls(x), c(".__enclos_env__", "clone")))
  if (isS4(x)) out <- c(out, methods::slotNames(x))
  unique(out)
}

rpx_encode_proxy <- function(x) {
  h <- rpx_new_handle(x)
  cls <- class(x)
  pkg <- tryCatch({ e <- environment(if (is.function(x)) x else NULL); if (!is.null(e) && isNamespace(e)) getNamespaceName(e) else attr(cls, "package") %||% NULL }, error = function(e) NULL)
  if (is.null(pkg) && isS4(x)) pkg <- attr(class(x), "package")
  if (is.null(pkg)) pkg <- tryCatch({ f <- utils::getAnywhere(paste0("print.", cls[1])); if (length(f$where)) sub("^namespace:", "", grep("^namespace:", f$where, value = TRUE)[1]) else NULL }, error = function(e) NULL)
  summary_txt <- tryCatch(paste(utils::capture.output(utils::str(x, max.level = 1, give.attr = FALSE, list.len = 20)), collapse = "\n"), error = function(e) "")
  repr <- tryCatch(paste(utils::head(utils::capture.output(print(x)), 30), collapse = "\n"), error = function(e) summary_txt)
  fields <- if (is.list(x) && !is.null(names(x))) names(x) else if (is.environment(x)) ls(x) else character()
  list(rpx = 1L, kind = "proxy", runtime = "r", handle = h, class = as.list(cls), package = pkg,
       is_s4 = isS4(x), is_r6 = inherits(x, "R6"), is_function = is.function(x),
       methods = as.list(rpx_methods_for(x)), fields = as.list(fields), slots = if (isS4(x)) as.list(methods::slotNames(x)) else list(),
       repr = repr, summary = summary_txt, meta = list(source_class = paste(cls, collapse = "/")))
}
