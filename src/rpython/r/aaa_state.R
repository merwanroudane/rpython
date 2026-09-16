# aaa_state.R -- package-level state (sourced first: files are loaded in sorted order)

.rpx_state <- new.env(parent = emptyenv())
.rpx_state$workdir <- NULL
.rpx_state$peer_arrow <- FALSE
.rpx_state$arrow_threshold_rows <- 5000L
.rpx_state$handles <- new.env(parent = emptyenv())
.rpx_state$handle_counter <- 0L
.rpx_state$transfer <- "auto"
.rpx_state$conn_in <- NULL
.rpx_state$conn_out <- NULL
.rpx_state$user_env <- NULL
.rpx_state$encoders <- list()
.rpx_state$decoders <- list()
.rpx_state$db_connections <- new.env(parent = emptyenv())
.rpx_state$py <- NULL

`%||%` <- function(a, b) if (is.null(a)) b else a
