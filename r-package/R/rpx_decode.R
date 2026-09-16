# rpx_decode.R -- portable envelope (RPX v1)  ->  R object

rpx_decode <- function(env) {
  if (is.null(env) || !is.list(env) || is.null(env$kind)) return(env)
  # registered custom decoders first
  dec <- .rpx_state$decoders[[env$kind]]
  if (!is.null(dec)) return(dec(env))
  switch(env$kind,
         "null" = NULL,
         vector = rpx_decode_vector(env),
         column = rpx_decode_column_env(env),
         list = rpx_decode_list(env),
         ref = structure(list(ref = env$ref), class = "rpx_ref"),
         array = rpx_decode_array(env),
         sparse = rpx_decode_sparse(env),
         table = rpx_decode_table(env),
         dataset = rpx_decode_dataset(env),
         timeseries = rpx_decode_timeseries(env),
         panel = rpx_decode_panel(env),
         labelled = rpx_decode_labelled(env),
         survival = rpx_decode_survival(env),
         spatial = rpx_decode_spatial(env),
         spatiotemporal = rpx_decode_spatial(env),
         geometry = rpx_decode_geometry(env),
         raster = rpx_decode_raster(env),
         raster_ref = rpx_decode_raster_ref(env),
         network = rpx_decode_network(env),
         dtm = rpx_decode_dtm(env),
         corpus = rpx_decode_corpus(env),
         image = rpx_decode_image(env),
         audio = rpx_decode_audio(env),
         video_ref = rpx_decode_media_ref(env),
         image_ref = rpx_decode_media_ref(env),
         audio_ref = rpx_decode_media_ref(env),
         labeled_array = rpx_decode_labeled_array(env),
         labeled_dataset = rpx_decode_labeled_dataset(env),
         netcdf_ref = rpx_decode_netcdf_ref(env),
         economic_matrix = rpx_decode_economic_matrix(env),
         spatial_weights = rpx_decode_spatial_weights(env),
         dyadic = rpx_decode_semantic_table(env, "dyadic"),
         vintages = rpx_decode_semantic_table(env, "vintages"),
         experiment = rpx_decode_semantic_table(env, "experiment"),
         simulation = rpx_decode_semantic_table(env, "simulation"),
         mixed_frequency = rpx_decode_mixed_frequency(env),
         proxy = rpx_decode_proxy(env),
         lazy_relation = rpx_decode_lazy_relation(env),
         db_relation = rpx_decode_db_relation(env),
         structure(env, class = "rpx_unknown"))
}

# ---------------------------------------------------------------------------
# atomic values
# ---------------------------------------------------------------------------

rpx_decode_values <- function(values, type, tz = NULL) {
  n <- length(values)
  if (type == "double") {
    out <- vapply(values, function(v) {
      if (is.null(v)) return(NA_real_)
      if (is.character(v)) return(switch(v, "NA" = NA_real_, "NaN" = NaN, "Inf" = Inf, "-Inf" = -Inf, as.numeric(v)))
      as.numeric(v)
    }, numeric(1))
    return(out)
  }
  if (type == "integer") return(vapply(values, function(v) if (is.null(v)) NA_integer_ else as.integer(v), integer(1)))
  if (type == "int64") {
    s <- vapply(values, function(v) if (is.null(v)) NA_character_ else as.character(v), character(1))
    if (rpx_has("bit64")) return(bit64::as.integer64(s))
    num <- suppressWarnings(as.numeric(s))
    if (any(abs(num) >= 2^53, na.rm = TRUE)) warning("int64 values beyond 2^53 and bit64 not installed: kept as character to avoid rounding")
    if (any(abs(num) >= 2^53, na.rm = TRUE)) return(structure(s, class = c("rpx_int64", "character")))
    return(num)
  }
  if (type == "logical") return(vapply(values, function(v) if (is.null(v)) NA else as.logical(v), logical(1)))
  if (type == "character") return(vapply(values, function(v) if (is.null(v)) NA_character_ else as.character(v), character(1)))
  if (type == "complex") return(vapply(values, function(v) if (is.null(v)) NA_complex_ else complex(real = rpx_decode_values(list(v[[1]]), "double"), imaginary = rpx_decode_values(list(v[[2]]), "double")), complex(1)))
  if (type == "raw") return(jsonlite::base64_dec(values[[1]]))
  if (type == "decimal") return(structure(vapply(values, function(v) if (is.null(v)) NA_character_ else as.character(v), character(1)), class = c("rpx_decimal", "character")))
  if (type == "fraction") return(structure(vapply(values, function(v) if (is.null(v)) NA_character_ else as.character(v), character(1)), class = c("rpx_fraction", "character")))
  if (type == "uuid") return(structure(vapply(values, function(v) if (is.null(v)) NA_character_ else as.character(v), character(1)), class = c("rpx_uuid", "character")))
  if (type == "date") return(as.Date(vapply(values, function(v) if (is.null(v)) NA_character_ else as.character(v), character(1))))
  if (type == "datetime") return(rpx_decode_datetime(values, tz))
  if (type == "timedelta") return(as.difftime(rpx_decode_values(values, "double"), units = "secs"))
  if (type == "period") return(vapply(values, function(v) if (is.null(v)) NA_character_ else as.character(v), character(1)))
  if (type == "factor") return(vapply(values, function(v) if (is.null(v)) NA_character_ else as.character(v), character(1)))
  stop("cannot decode values of type ", type)
}

rpx_decode_datetime <- function(values, tz = NULL) {
  s <- vapply(values, function(v) if (is.null(v)) NA_character_ else as.character(v), character(1))
  naive <- is.null(tz) || identical(tz, "naive")
  # strip offset for parsing; ISO strings from Python carry +HH:MM when aware
  has_off <- grepl("([+-]\\d{2}:?\\d{2}|Z)$", s)
  base <- sub("([+-]\\d{2}:?\\d{2}|Z)$", "", s)
  base <- sub("T", " ", base)
  out <- as.POSIXct(base, tz = "UTC", format = "%Y-%m-%d %H:%M:%OS")
  if (any(has_off, na.rm = TRUE)) {
    off <- sub("^.*([+-]\\d{2}):?(\\d{2})$", "\\1\\2", s)
    off[!has_off | is.na(s)] <- "+0000"
    off[grepl("Z$", s)] <- "+0000"
    secs <- as.numeric(substr(off, 1, 3)) * 3600 + sign(as.numeric(substr(off, 1, 3))) * as.numeric(substr(off, 4, 5)) * 60
    secs[is.na(secs)] <- 0
    out <- out - secs
  }
  if (naive) {
    attr(out, "tzone") <- "UTC"
    attr(out, "rpython_naive") <- TRUE
  } else {
    attr(out, "tzone") <- tz
  }
  out
}

rpx_decode_vector <- function(env) {
  type <- env$type
  meta <- env$meta %||% list()
  x <- rpx_decode_values(env$values, type, meta$tz)
  if (!is.null(env$names)) names(x) <- vapply(env$names, function(n) if (is.null(n)) "" else as.character(n), character(1))
  if (!is.null(meta$container) && !meta$container %in% c("dict", "OrderedDict", "defaultdict")) attr(x, "rpython_container") <- meta$container
  x
}

rpx_decode_list <- function(env) {
  items <- lapply(env$items, rpx_decode)
  if (!is.null(env$keys)) {
    keys <- lapply(env$keys, rpx_decode)
    names(items) <- vapply(keys, function(k) paste(format(k), collapse = ","), character(1))
    attr(items, "rpython_keys") <- keys
  } else if (!is.null(env$names)) {
    names(items) <- vapply(env$names, function(n) if (is.null(n)) "" else as.character(n), character(1))
  }
  meta <- env$meta %||% list()
  if (!is.null(meta$container) && !meta$container %in% c("list", "dict")) attr(items, "rpython_container") <- meta$container
  if (!is.null(meta$class) && !meta$class %in% c("builtins.list", "builtins.dict", "builtins.tuple", "builtins.set")) attr(items, "rpython_class") <- meta$class
  items
}

rpx_decode_array <- function(env) {
  type <- env$dtype
  shape <- unlist(env$shape)
  if (!is.null(env$arrow)) {
    vals <- arrow::read_feather(env$arrow)$values
  } else {
    vals <- rpx_decode_values(env$values, type, (env$meta %||% list())$tz)
  }
  if (!is.null(env$mask) && length(env$mask)) {
    m <- vapply(env$mask, isTRUE, logical(1))
    vals[m] <- NA
  }
  if (length(shape) == 0) return(vals)
  if (length(shape) == 1) {   # 1-d arrays are plain vectors in R (names kept if any)
    dn <- env$dimnames
    if (!is.null(dn) && !is.null(dn[[1]]) && length(dn[[1]])) names(vals) <- vapply(dn[[1]], as.character, character(1))
    return(vals)
  }
  if (identical(env$order, "C")) {
    a <- array(vals, dim = rev(shape))
    a <- aperm(a, rev(seq_along(shape)))
  } else {
    a <- array(vals, dim = shape)
  }
  if (!is.null(env$dimnames)) {
    dn <- lapply(env$dimnames, function(d) if (is.null(d) || !length(d)) NULL else vapply(d, as.character, character(1)))
    if (any(!vapply(dn, is.null, logical(1)))) dimnames(a) <- dn
  }
  if (type == "datetime" || type == "date" || type == "timedelta") {
    attrs <- attributes(vals); attrs$dim <- dim(a); attrs$dimnames <- dimnames(a); attributes(a) <- attrs
  }
  a
}

rpx_decode_sparse <- function(env) {
  if (!rpx_has("Matrix")) stop("the Matrix package is required to receive sparse matrices: install.packages('Matrix')")
  shape <- unlist(env$shape)
  x <- rpx_decode_values(env$data, env$dtype %||% "double")
  dn <- if (is.null(env$dimnames)) NULL else lapply(env$dimnames, function(d) if (is.null(d) || !length(d)) NULL else vapply(d, as.character, character(1)))
  if (env$format == "csc") {
    m <- Matrix::sparseMatrix(i = unlist(env$indices), p = unlist(env$indptr), x = x, dims = shape, index1 = FALSE, dimnames = dn)
  } else if (env$format == "csr") {
    m <- Matrix::sparseMatrix(j = unlist(env$indices), p = unlist(env$indptr), x = x, dims = shape, index1 = FALSE, dimnames = dn)
    m <- methods::as(methods::as(m, "RsparseMatrix"), "generalMatrix")
  } else {
    m <- Matrix::sparseMatrix(i = unlist(env$row), j = unlist(env$col), x = x, dims = shape, index1 = FALSE, dimnames = dn, repr = "T")
  }
  if (isTRUE(env$symmetric)) m <- Matrix::forceSymmetric(m)
  m
}

# ---------------------------------------------------------------------------
# tables
# ---------------------------------------------------------------------------

rpx_decode_column <- function(col, arrow_col = NULL) {
  type <- col$type
  sem <- col$semantic %||% list()
  if (!is.null(arrow_col)) {
    x <- arrow_col
    if (type == "factor") {
      cat_ <- sem$categorical
      x <- factor(as.character(x), levels = unlist(cat_$levels), ordered = isTRUE(cat_$ordered))
    } else if (type == "datetime") {
      tz <- (sem$datetime %||% list())$tz %||% "naive"
      if (!inherits(x, "POSIXct")) x <- as.POSIXct(x, tz = "UTC")
      if (identical(tz, "naive")) { attr(x, "tzone") <- "UTC"; attr(x, "rpython_naive") <- TRUE } else attr(x, "tzone") <- tz
    } else if (type == "date") {
      if (!inherits(x, "Date")) x <- as.Date(x)
    } else if (type == "timedelta") {
      if (!inherits(x, "difftime")) x <- as.difftime(as.numeric(x), units = "secs")
    } else if (type == "int64") {
      if (rpx_has("bit64")) x <- bit64::as.integer64(x) else x <- as.numeric(x)
    } else if (type == "integer" && !is.integer(x)) {
      x <- as.integer(x)
    } else if (type == "geometry") {
      x <- rpx_decode_wkb_column(x)
    } else if (type == "list" && is.list(x)) {
      x <- lapply(x, function(v) if (is.null(v)) NULL else v)
    }
  } else {
    if (type == "factor") {
      cat_ <- sem$categorical
      x <- factor(rpx_decode_values(col$values, "factor"), levels = unlist(cat_$levels), ordered = isTRUE(cat_$ordered))
    } else if (type == "datetime") {
      x <- rpx_decode_datetime(col$values, (sem$datetime %||% list())$tz %||% "naive")
    } else if (type %in% c("list", "struct")) {
      x <- lapply(col$values, function(v) if (is.null(v)) NULL else rpx_decode(v))
    } else if (type == "geometry") {
      x <- rpx_decode_wkb_column(vapply(col$values, function(v) if (is.null(v)) NA_character_ else v, character(1)))
    } else if (type == "interval") {
      x <- lapply(col$values, function(v) if (is.null(v)) NULL else unlist(v))
    } else {
      x <- rpx_decode_values(col$values, type)
    }
  }
  if (!is.null(sem$labels)) {
    lb <- sem$labels
    if (!is.null(lb$variable)) attr(x, "label") <- lb$variable
  }
  x
}

rpx_decode_wkb_column <- function(x) {
  if (!rpx_has("sf")) return(x)
  raw_list <- lapply(x, function(v) if (is.na(v)) NULL else if (is.raw(v)) v else jsonlite::base64_dec(v))
  geoms <- lapply(raw_list, function(r) if (is.null(r)) sf::st_geometrycollection() else sf::st_as_sfc(list(r))[[1]])
  sf::st_sfc(geoms)
}

rpx_decode_table <- function(env, keep_class = TRUE) {
  cols <- env$columns %||% list()
  n <- env$nrow %||% 0L
  if (!is.null(env$arrow)) {
    if (!rpx_has("arrow")) stop("the arrow package is required to receive this table: install.packages('arrow')")
    tbl <- arrow::read_feather(env$arrow, as_data_frame = TRUE)
    tbl <- as.data.frame(tbl)
    out <- lapply(cols, function(col) rpx_decode_column(col, tbl[[col$name]]))
  } else {
    out <- lapply(cols, function(col) rpx_decode_column(col))
  }
  names(out) <- vapply(cols, function(c) c$name, character(1))
  meta <- env$meta %||% list()
  renamed <- (meta$names %||% list())$renamed
  if (!is.null(renamed) && length(renamed)) names(out) <- vapply(names(out), function(nm) renamed[[nm]] %||% nm, character(1))
  if (!length(out)) {
    df <- data.frame(matrix(nrow = n, ncol = 0))
  } else {
    df <- structure(out, class = "data.frame", row.names = seq_len(n))
    if (any(vapply(out, function(v) is.list(v) && !is.data.frame(v), logical(1)))) {
      df <- structure(out, class = "data.frame", row.names = seq_len(n))
    }
  }
  # index -> row names when unique character
  idx <- env$index
  if (!is.null(idx) && isTRUE(idx$row_names) && length(idx$columns) == 1 && idx$columns[[1]] %in% names(df)) {
    rn <- df[[idx$columns[[1]]]]
    if (is.character(rn) && !anyDuplicated(rn) && !anyNA(rn)) {
      rownames(df) <- rn
    }
  }
  if (!is.null(env$row_names) && length(env$row_names) == n) rownames(df) <- unlist(env$row_names)
  if (!is.null(idx)) attr(df, "rpython.index") <- idx
  attrs <- env$attrs %||% list()
  for (nm in names(attrs)) attr(df, nm) <- attrs[[nm]]
  sem <- env$semantics %||% list()
  for (block in names(sem)) if (!block %in% c("roles")) attr(df, paste0("rpython.", block)) <- sem[[block]]
  if (!is.null(sem$roles) && length(sem$roles)) attr(df, "rpython.roles") <- sem$roles
  if (!is.null(sem$labels)) df <- rpx_apply_labels(df, sem$labels)
  if (keep_class) {
    hint <- meta$class_hint %||% "data.frame"
    if (hint == "tibble" && rpx_has("tibble")) df <- tibble::as_tibble(df)
    if (hint == "data.table" && rpx_has("data.table")) df <- data.table::as.data.table(df)
  }
  df
}

rpx_apply_labels <- function(df, lb) {
  vars <- lb$variables %||% list(); vals <- lb$values %||% list(); miss <- lb$missing %||% list(); rng <- lb$missing_ranges %||% list()
  ct <- lb$value_code_type %||% list()
  for (nm in names(df)) {
    x <- df[[nm]]
    labels <- NULL
    if (!is.null(vals[[nm]])) {
      codes <- names(vals[[nm]]); labs <- unlist(vals[[nm]])
      if (identical(ct[[nm]], "character")) labels <- setNames(codes, labs) else labels <- setNames(as.numeric(codes), labs)
    }
    if (rpx_has("haven") && (!is.null(labels) || !is.null(vars[[nm]]) || !is.null(miss[[nm]]))) {
      if (is.factor(x)) { attr(x, "label") <- vars[[nm]]; df[[nm]] <- x; next }
      if (!is.numeric(x) && !is.character(x)) { attr(x, "label") <- vars[[nm]]; df[[nm]] <- x; next }
      if (!is.null(labels) && is.numeric(x) && is.character(labels)) labels <- NULL
      if (!is.null(miss[[nm]]) || !is.null(rng[[nm]])) {
        na_values <- if (is.null(miss[[nm]])) NULL else unlist(miss[[nm]])
        na_range <- if (is.null(rng[[nm]])) NULL else unlist(rng[[nm]][[1]])
        if (is.numeric(x)) { if (!is.null(na_values)) na_values <- as.numeric(na_values); if (!is.null(na_range)) na_range <- as.numeric(na_range) }
        x <- haven::labelled_spss(x, labels = labels, na_values = na_values, na_range = na_range, label = vars[[nm]])
      } else {
        x <- haven::labelled(x, labels = labels, label = vars[[nm]])
      }
    } else {
      if (!is.null(vars[[nm]])) attr(x, "label") <- vars[[nm]]
      if (!is.null(labels)) attr(x, "labels") <- labels
    }
    df[[nm]] <- x
  }
  design <- lb$design
  if (!is.null(design) && any(!vapply(design, is.null, logical(1)))) attr(df, "rpython.survey") <- design
  attr(df, "rpython.labels") <- NULL
  df
}

rpx_decode_column_env <- function(env) {
  x <- rpx_decode_column(env$column)
  if (!is.null(env$names)) names(x) <- vapply(env$names, as.character, character(1))
  x
}

rpx_decode_labelled <- function(env) rpx_decode_table(env)

rpx_decode_dataset <- function(env) {
  files <- unlist(env$files)
  if (rpx_has("arrow")) return(arrow::open_dataset(files, format = env$format %||% "parquet"))
  structure(list(files = files, format = env$format), class = "rpx_dataset")
}

# ---------------------------------------------------------------------------
# time series / panel
# ---------------------------------------------------------------------------

rpx_decode_timeseries <- function(env) {
  sem <- (env$semantics %||% list())$timeseries %||% list()
  df <- rpx_decode_table(env, keep_class = FALSE)
  attr(df, "rpython.timeseries") <- NULL
  tcol <- sem$time
  ids <- unlist(sem$ids)
  cls <- sem$r_class %||% "data.frame"
  if (length(ids) && rpx_has("tsibble")) {
    out <- tryCatch(tsibble::as_tsibble(df, key = tidyselect::all_of(ids), index = tidyselect::all_of(tcol), regular = isTRUE(sem$regular)),
                    error = function(e) { attr(df, "rpython.timeseries") <- sem; df })
    return(out)
  }
  if (identical(cls, "ts") || identical(cls, "mts")) {
    vals <- df[setdiff(names(df), tcol)]
    freq <- sem$r_frequency %||% 1
    start <- unlist(sem$r_start) %||% c(1, 1)
    x <- if (ncol(vals) == 1) stats::ts(vals[[1]], start = start, frequency = freq) else stats::ts(as.matrix(vals), start = start, frequency = freq)
    if (ncol(vals) == 1) attr(x, "rpython_name") <- names(vals)[1]
    attr(x, "rpython.timeseries") <- sem[intersect(names(sem), c("index_kind", "frequency", "tz", "time", "from_index", "from_series", "series_name"))]
    return(x)
  }
  if (!is.null(tcol) && tcol %in% names(df)) {
    idx <- df[[tcol]]
    vals <- df[setdiff(names(df), tcol)]
    if (inherits(idx, "POSIXct") || inherits(idx, "Date")) {
      core <- as.matrix(vals)   # keeps column names even for a single series
      if (rpx_has("xts")) {
        x <- tryCatch(xts::xts(core, order.by = idx), error = function(e) NULL)
        if (!is.null(x)) {
          attr(x, "rpython_name") <- names(vals)[1]
          attr(x, "rpython.timeseries") <- sem
          return(x)
        }
      }
      if (rpx_has("zoo")) { x <- zoo::zoo(core, order.by = idx); attr(x, "rpython.timeseries") <- sem; return(x) }
    }
  }
  attr(df, "rpython.timeseries") <- sem
  df
}

rpx_decode_panel <- function(env) {
  sem <- (env$semantics %||% list())$panel %||% list()
  df <- rpx_decode_table(env, keep_class = FALSE)
  attr(df, "rpython.panel") <- sem
  ids <- if (is.list(sem$id)) unlist(sem$id) else sem$id
  time <- sem$time
  if (identical(sem$kind %||% "panel", "panel") && rpx_has("plm") && length(ids) == 1 && !is.null(time) &&
      all(c(ids, time) %in% names(df)) && !isTRUE(sem$duplicates > 0)) {
    out <- tryCatch({ p <- plm::pdata.frame(df, index = c(ids, time)); attr(p, "rpython.panel") <- sem; p },
                    error = function(e) df)
    return(out)
  }
  df
}

rpx_decode_survival <- function(env) {
  if (!rpx_has("survival")) stop("the survival package is required: install.packages('survival')")
  time <- rpx_decode_values(env$time, "double")
  ev <- if (identical(env$type, "mstate")) factor(unlist(env$event), levels = unlist(env$event_levels)) else rpx_decode_values(env$event, "double")
  s <- if (!is.null(env$time2)) {
    survival::Surv(time, rpx_decode_values(env$time2, "double"), ev, type = if (env$type == "interval") "interval2" else "counting")
  } else if (identical(env$type, "mstate")) survival::Surv(time, ev, type = "mstate")
  else if (identical(env$type, "left")) survival::Surv(time, ev, type = "left")
  else survival::Surv(time, ev)
  if (!is.null(env$covariates)) {
    cov <- rpx_decode_table(env$covariates)
    attr(s, "rpython.covariates") <- cov
  }
  if (!is.null(env$id)) attr(s, "rpython.id") <- unlist(env$id)
  if (!is.null(env$strata)) attr(s, "rpython.strata") <- unlist(env$strata)
  attr(s, "rpython.columns") <- env$columns
  s
}

# ---------------------------------------------------------------------------
# spatial / raster
# ---------------------------------------------------------------------------

rpx_crs_from_block <- function(b) {
  if (is.null(b)) return(sf::NA_crs_)
  if (!is.null(b$epsg)) return(sf::st_crs(as.integer(b$epsg)))
  if (!is.null(b$wkt)) return(sf::st_crs(b$wkt))
  if (!is.null(b$input)) return(sf::st_crs(b$input))
  sf::NA_crs_
}

rpx_decode_spatial <- function(env) {
  sem <- (env$semantics %||% list())$spatial %||% list()
  df <- rpx_decode_table(env, keep_class = FALSE)
  if (!rpx_has("sf")) { warning("sf not installed: geometry kept as WKB base64 strings"); return(df) }
  gcols <- unlist(sem$geometry_columns) %||% sem$geometry_column %||% "geometry"
  active <- sem$geometry_column %||% gcols[1]
  for (g in gcols) {
    if (!inherits(df[[g]], "sfc")) df[[g]] <- rpx_decode_wkb_column(df[[g]])
    crs_b <- if (g == active) sem$crs else (sem$crs_by_column %||% list())[[g]]
    sf::st_crs(df[[g]]) <- rpx_crs_from_block(crs_b)
  }
  attr(df, "rpython.spatial") <- NULL
  out <- sf::st_sf(df, sf_column_name = active)
  st <- (env$semantics %||% list())$spatiotemporal
  if (!is.null(st)) attr(out, "rpython.spatiotemporal") <- st
  out
}

rpx_decode_geometry <- function(env) {
  if (!rpx_has("sf")) return(env)
  g <- sf::st_as_sfc(list(jsonlite::base64_dec(env$wkb)))
  if (!is.null(env$crs)) sf::st_crs(g) <- rpx_crs_from_block(env$crs)
  g[[1]]
}

rpx_decode_raster_ref <- function(env) {
  if (rpx_has("terra")) return(terra::rast(env$path))
  if (rpx_has("stars")) return(stars::read_stars(env$path, proxy = TRUE))
  structure(list(path = env$path, driver = env$driver, header = env$header), class = "rpython_raster_ref")
}

rpx_decode_raster <- function(env) {
  a <- rpx_decode_array(env$array)
  if (length(dim(a)) == 2) a <- array(a, dim = c(1, dim(a)))
  gt <- unlist(env$geotransform)
  nb <- dim(a)[1]; nr <- dim(a)[2]; nc <- dim(a)[3]
  if (rpx_has("terra")) {
    ext <- terra::ext(gt[1], gt[1] + gt[2] * nc, gt[4] + gt[6] * nr, gt[4])
    layers <- lapply(seq_len(nb), function(b) terra::rast(matrix(a[b, , ], nrow = nr, ncol = nc), extent = ext))
    r <- do.call(c, layers)
    if (!is.null(env$crs)) terra::crs(r) <- rpx_crs_from_block(env$crs)$wkt %||% ""
    if (!is.null(env$nodata)) terra::NAflag(r) <- env$nodata
    if (!is.null(env$bands)) names(r) <- unlist(env$bands)
    return(r)
  }
  structure(list(array = a, geotransform = gt, crs = env$crs, nodata = env$nodata, bands = env$bands), class = "rpython_raster")
}

# ---------------------------------------------------------------------------
# networks / text / media / scientific / economics
# ---------------------------------------------------------------------------

rpx_decode_network <- function(env) {
  nodes <- rpx_decode_table(env$nodes, keep_class = FALSE)
  edges <- rpx_decode_table(env$edges, keep_class = FALSE)
  nodes$name <- as.character(nodes$name)
  edges$from <- as.character(edges$from); edges$to <- as.character(edges$to)
  if (!rpx_has("igraph")) return(structure(list(nodes = nodes, edges = edges, directed = env$directed, features = env$features), class = "rpython_network"))
  nodes <- nodes[c("name", setdiff(names(nodes), "name"))]
  g <- igraph::graph_from_data_frame(edges, directed = isTRUE(env$directed), vertices = nodes)
  for (nm in names(env$graph_attrs %||% list())) g <- igraph::set_graph_attr(g, nm, env$graph_attrs[[nm]])
  wcol <- (env$columns %||% list())$weight
  if (!is.null(wcol) && !identical(wcol, "weight") && wcol %in% igraph::edge_attr_names(g)) {
    igraph::E(g)$weight <- igraph::edge_attr(g, wcol)   # igraph convention; alias dropped on the way back
    attr(g, "rpython_weight_attr") <- wcol
  }
  bip <- (env$columns %||% list())$bipartite
  if (!is.null(bip) && bip %in% igraph::vertex_attr_names(g) && !identical(bip, "type")) igraph::V(g)$type <- as.logical(igraph::vertex_attr(g, bip))
  attr(g, "rpython_id_type") <- env$node_id_type
  attr(g, "rpython.features") <- env$features
  g
}

rpx_decode_dtm <- function(env) {
  m <- rpx_decode_sparse(env$matrix)
  dimnames(m) <- if (identical(env$orientation, "tdm")) list(unlist(env$terms), unlist(env$docs)) else list(unlist(env$docs), unlist(env$terms))
  if (rpx_has("quanteda") && identical(env$orientation %||% "dtm", "dtm")) return(quanteda::as.dfm(m))
  attr(m, "rpython.weighting") <- env$weighting
  m
}

rpx_decode_corpus <- function(env) {
  df <- rpx_decode_table(env, keep_class = FALSE)
  sem <- (env$semantics %||% list())$text %||% list()
  if (rpx_has("quanteda")) {
    return(quanteda::corpus(df, docid_field = sem$doc_id %||% NULL, text_field = sem$text_column %||% "text"))
  }
  attr(df, "rpython.text") <- sem
  df
}

rpx_decode_image <- function(env) {
  a <- rpx_decode_array(env$array)
  attr(a, "rpython.image") <- env[c("width", "height", "channels", "channel_order", "layout", "dtype", "bit_depth", "color_space", "alpha", "orientation")]
  class(a) <- c("rpython_image", class(a))
  a
}

rpx_decode_audio <- function(env) {
  a <- rpx_decode_array(env$array)
  attr(a, "sample_rate") <- env$sample_rate
  attr(a, "rpython.audio") <- env[c("sample_rate", "channels", "bit_depth", "duration", "channel_names")]
  if (rpx_has("tuneR")) {
    m <- if (is.null(dim(a))) matrix(a, ncol = 1) else a
    return(tryCatch(tuneR::Wave(left = as.numeric(m[, 1]), right = if (ncol(m) > 1) as.numeric(m[, 2]) else numeric(0), samp.rate = env$sample_rate, bit = env$bit_depth %||% 32, pcm = FALSE), error = function(e) a))
  }
  class(a) <- c("rpython_audio", class(a))
  a
}

rpx_decode_media_ref <- function(env) structure(list(path = env$path, kind = sub("_ref$", "", env$kind), metadata = env$metadata), class = "rpython_media_ref")

rpx_decode_labeled_array <- function(env) {
  a <- rpx_decode_array(env$data)
  dims <- unlist(env$dims)
  if (!is.null(dimnames(a))) names(dimnames(a)) <- dims
  coords <- lapply(env$coords %||% list(), function(cc) list(dims = unlist(cc$dims), values = rpx_decode(cc$values), attrs = cc$attrs, dtype = cc$dtype))
  attr(a, "rpython.dims") <- dims
  attr(a, "rpython.coords") <- coords
  attr(a, "rpython.attrs") <- env$attrs
  attr(a, "rpython.name") <- env$name
  # A labelled scientific array is a plain R array with dimnames + rpython.* attributes.
  # (It is deliberately NOT turned into a stars object: stars is for georeferenced rasters,
  # and an xarray round trip must come back as an xarray, not as a raster.)
  class(a) <- c("rpython_labeled_array", class(a))
  a
}

rpx_decode_labeled_dataset <- function(env) {
  vars <- lapply(env$variables %||% list(), rpx_decode_labeled_array)
  attr(vars, "rpython.attrs") <- env$attrs
  attr(vars, "rpython.dims") <- env$dims
  class(vars) <- c("rpython_labeled_dataset", "list")
  vars
}

rpx_decode_netcdf_ref <- function(env) {
  if (rpx_has("stars")) return(tryCatch(stars::read_ncdf(env$path, proxy = TRUE), error = function(e) structure(env, class = "rpython_netcdf_ref")))
  if (rpx_has("ncdf4")) return(ncdf4::nc_open(env$path))
  structure(list(path = env$path, engine = env$engine, metadata = env$metadata), class = "rpython_netcdf_ref")
}

rpx_decode_economic_matrix <- function(env) {
  m <- rpx_decode(env$matrix)
  if (is.null(dimnames(m)) || all(vapply(dimnames(m), is.null, logical(1)))) dimnames(m) <- list(unlist(env$rows), unlist(env$cols))
  attr(m, "rpython.economic") <- env[c("matrix_kind", "orientation", "units", "year", "row_entity", "col_entity", "metadata")]
  m
}

rpx_decode_spatial_weights <- function(env) {
  m <- rpx_decode(env$matrix)
  ids <- unlist(env$ids)
  dimnames(m) <- list(ids, ids)
  if (rpx_has("spdep")) {
    w <- tryCatch(spdep::mat2listw(as.matrix(m), style = env$style %||% "B", zero.policy = isTRUE(env$zero_policy), row.names = ids), error = function(e) NULL)
    if (!is.null(w)) { attr(w, "rpython.weights") <- env[c("weights_kind", "k", "bandwidth", "directed", "islands")]; return(w) }
  }
  attr(m, "rpython.weights") <- env[c("style", "weights_kind", "k", "bandwidth", "directed", "zero_policy", "islands")]
  m
}

rpx_decode_semantic_table <- function(env, block) {
  df <- rpx_decode_table(env)
  df
}

rpx_decode_mixed_frequency <- function(env) {
  out <- lapply(env$series, rpx_decode)
  attr(out, "rpython.target") <- env$target
  class(out) <- c("rpython_mixed_frequency", "list")
  out
}

# ---------------------------------------------------------------------------
# proxies
# ---------------------------------------------------------------------------

rpx_decode_lazy_relation <- function(env) {
  structure(env, class = "rpython_lazy_relation")
}

# Bind parameters into SQL text using the driver's own literal quoting (DBI::dbQuoteLiteral):
# values are never pasted raw.  Needed because dbplyr lazy tables cannot carry bound params.
rpx_bind_params <- function(con, sql, params) {
  if (is.null(params) || !length(params)) return(sql)
  if (!is.null(names(params)) && all(nzchar(names(params)))) {
    for (nm in names(params)) sql <- gsub(paste0(":", nm, "\b"), as.character(DBI::dbQuoteLiteral(con, params[[nm]])), sql, perl = TRUE)
    return(sql)
  }
  for (v in params) sql <- sub("?", as.character(DBI::dbQuoteLiteral(con, v)), sql, fixed = TRUE)
  sql
}

rpx_decode_db_relation <- function(env) {
  con <- rpx_db_connect(env$connection)
  if (is.null(con)) return(structure(env, class = "rpython_db_relation"))
  sql <- env$sql
  if (!is.null(sql)) sql <- rpx_bind_params(con, sql, env$params)
  out <- if (!is.null(sql)) {
    if (rpx_has("dbplyr")) dplyr::tbl(con, dbplyr::sql(sql)) else structure(c(env, list(con = con, sql = sql)), class = "rpython_db_relation")
  } else {
    if (rpx_has("dbplyr")) dplyr::tbl(con, env$table) else structure(c(env, list(con = con)), class = "rpython_db_relation")
  }
  attr(out, "rpython.connection") <- env$connection
  out
}
