# pyproxy.R -- Python objects living in the peer Python process, seen from R.
#
# rpx_pyproxy : an object kept alive in Python (handle).  `$` fetches
#               attributes; callables come back as R functions.
# Works identically whether R is the worker (Python drives) or the client
# (R drives Python via python()): both go through rpx_peer_call().

rpx_peer_call <- function(msg) {
  if (!is.null(.rpx_state$py) && isTRUE(.rpx_state$py$alive)) return(py_request(.rpx_state$py, msg))
  rpx_callback(msg)
}

rpx_make_pyfunction <- function(handle, name = NULL) {
  f <- function(...) {
    args <- list(...)
    nms <- names(args)
    if (is.null(nms)) nms <- rep("", length(args))
    pos <- unname(args[nms == ""])
    kw <- args[nms != ""]
    rpx_peer_call(list(what = "call", handle = handle, args = lapply(pos, rpx_encode, top = FALSE),
                       kwargs = lapply(kw, rpx_encode, top = FALSE)))
  }
  attr(f, "handle") <- handle
  attr(f, "pyname") <- name
  class(f) <- c("rpx_pyfunction", "function")
  f
}

rpx_decode_proxy <- function(env) {
  if (identical(env$runtime, "r")) return(rpx_get_handle(env$handle))
  if (isTRUE(env$callable)) return(rpx_make_pyfunction(env$handle, env$repr))
  structure(list(), handle = env$handle, pyclass = unlist(env$class), module = env$module,
            methods = unlist(env$methods), attributes = unlist(env$attributes), properties = unlist(env$properties),
            repr = env$repr, lazy = isTRUE(env$lazy), class = "rpx_pyproxy")
}

#' @export
`$.rpx_pyproxy` <- function(x, name) {
  res <- rpx_peer_call(list(what = "getattr", handle = attr(x, "handle"), name = name))
  res
}

#' @export
`[[.rpx_pyproxy` <- function(x, i, ...) {
  if (is.character(i)) return(`$.rpx_pyproxy`(x, i))
  rpx_peer_call(list(what = "call_method", handle = attr(x, "handle"), name = "__getitem__",
                     args = list(rpx_encode(i - 1L, top = FALSE)), kwargs = list()))
}

#' @export
print.rpx_pyproxy <- function(x, ...) {
  cat("<Python ", attr(x, "module"), ".", paste(attr(x, "pyclass"), collapse = "/"), " (proxy ", attr(x, "handle"), ")>\n", sep = "")
  if (!is.null(attr(x, "repr"))) cat(attr(x, "repr"), "\n")
  invisible(x)
}

#' @export
print.rpx_pyfunction <- function(x, ...) {
  cat("<Python callable ", attr(x, "pyname") %||% "", " (proxy ", attr(x, "handle"), ")>\n", sep = "")
  invisible(x)
}

#' @export
names.rpx_pyproxy <- function(x) c(attr(x, "attributes"), attr(x, "properties"), attr(x, "methods"))

#' @export
as.list.rpx_pyproxy <- function(x, ...) rpx_peer_call(list(what = "convert", handle = attr(x, "handle")))

#' Force conversion of a Python proxy into a native R object (semantics may be partial; reported).
#' @export
py_to_r <- function(x) {
  if (inherits(x, "rpx_pyproxy")) return(rpx_peer_call(list(what = "convert", handle = attr(x, "handle"))))
  x
}

#' Call a Python callable proxy with positional / named arguments.
#' @export
py_call <- function(f, ...) f(...)
