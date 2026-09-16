# Envelope round trips inside R (no Python needed): encode -> JSON -> decode.
rt <- function(x) rpython:::rpx_decode(jsonlite::fromJSON(rpython:::rpx_json(rpython:::rpx_encode(x)), simplifyVector = FALSE))

test_that("atomic vectors keep NA / NaN / Inf / names", {
  x <- c(a = 1, b = NA, c = NaN, d = Inf, e = -Inf)
  y <- rt(x)
  expect_identical(names(y), names(x))
  expect_true(is.na(y[2]) && !is.nan(y[2]) && is.nan(y[3]) && y[4] == Inf && y[5] == -Inf)
  expect_identical(rt(c(TRUE, NA)), c(TRUE, NA))
  expect_identical(rt(1:3), 1:3)
  expect_identical(rt(c("é", NA, "عربي")), c("é", NA, "عربي"))
  expect_identical(rt(as.raw(c(1, 255))), as.raw(c(1, 255)))
  expect_identical(rt(1 + 2i), 1 + 2i)
})

test_that("data frames keep factors, dates, times and row names", {
  df <- data.frame(x = c(1.5, NA, 3), f = factor(c("lo", "hi", "lo"), levels = c("lo", "hi"), ordered = TRUE),
                   d = as.Date("2024-01-01") + 0:2, t = as.POSIXct("2024-01-01 12:00:00", tz = "Europe/Paris") + 0:2 * 3600,
                   s = c("a", NA, "c"), stringsAsFactors = FALSE)
  rownames(df) <- c("r1", "r2", "r3")
  y <- rt(df)
  expect_identical(y$f, df$f)
  expect_identical(y$d, df$d)
  expect_equal(as.numeric(y$t), as.numeric(df$t))
  expect_identical(attr(y$t, "tzone"), "Europe/Paris")
  expect_identical(rownames(y), rownames(df))
  expect_identical(y$s, df$s)
  expect_true(is.na(y$x[2]))
})

test_that("matrices and arrays keep dims and dimnames", {
  m <- matrix(1:6, 2, dimnames = list(c("a", "b"), c("x", "y", "z")))
  expect_identical(rt(m), m)
  a <- array(1:24, c(2, 3, 4))
  expect_identical(rt(a), a)
})

test_that("ts / xts keep frequency and index", {
  x <- ts(1:8, start = c(2020, 1), frequency = 4)
  y <- rt(x)
  expect_equal(frequency(y), 4)
  expect_equal(start(y), c(2020, 1))
  skip_if_not_installed("xts")
  idx <- as.POSIXct(c("2020-01-01", "2020-01-05", "2020-02-01"), tz = "UTC")
  z <- xts::xts(1:3, order.by = idx)
  w <- rt(z)
  expect_s3_class(w, "xts")
  expect_equal(as.numeric(zoo::index(w)), as.numeric(idx))
})

test_that("sparse matrices keep format and values", {
  skip_if_not_installed("Matrix")
  m <- Matrix::sparseMatrix(i = c(1, 3), j = c(2, 1), x = c(5, 7), dims = c(3, 3))
  y <- rt(m)
  expect_s4_class(y, "dgCMatrix")
  expect_equal(as.matrix(y), as.matrix(m))
})

test_that("igraph keeps direction, multi-edges and attributes", {
  skip_if_not_installed("igraph")
  g <- igraph::graph_from_data_frame(data.frame(from = c("a", "a", "b"), to = c("b", "b", "b"), w = 1:3), directed = TRUE)
  y <- rt(g)
  expect_equal(igraph::ecount(y), 3)
  expect_true(igraph::is_directed(y) && igraph::any_multiple(y) && any(igraph::which_loop(y)))
  expect_equal(igraph::edge_attr(y, "w"), 1:3)
})

test_that("sf keeps geometry and CRS", {
  skip_if_not_installed("sf")
  pts <- sf::st_sf(id = 1:2, geometry = sf::st_sfc(sf::st_point(c(1, 2)), sf::st_point(c(3, 4)), crs = 4326))
  y <- rt(pts)
  expect_s3_class(y, "sf")
  expect_equal(sf::st_crs(y)$epsg, 4326)
  expect_equal(sf::st_coordinates(y)[2, ], c(X = 3, Y = 4))
})

test_that("Surv and labelled columns survive", {
  skip_if_not_installed("survival")
  s <- survival::Surv(c(1, 2, 3), c(1, 0, 1))
  y <- rt(s)
  expect_s3_class(y, "Surv")
  expect_equal(unclass(y)[, 1], c(1, 2, 3))
  skip_if_not_installed("haven")
  df <- data.frame(sex = haven::labelled(c(1, 2), labels = c(male = 1, female = 2), label = "Sex"))
  z <- rt(df)
  expect_s3_class(z$sex, "haven_labelled")
  expect_identical(attr(z$sex, "label"), "Sex")
  expect_identical(attr(z$sex, "labels"), c(male = 1, female = 2))
})

test_that("unknown objects become proxies with class information", {
  fit <- lm(mpg ~ wt, data = mtcars)
  env <- rpython:::rpx_encode(fit)
  expect_identical(env$kind, "proxy")
  expect_identical(unlist(env$class), "lm")
  expect_true("predict" %in% unlist(env$methods))
  expect_identical(rpython:::rpx_decode(env), fit)
})
