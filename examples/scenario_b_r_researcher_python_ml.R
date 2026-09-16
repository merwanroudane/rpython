# Scenario B -- an R researcher using Python machine learning (design spec §61).
#
# 1. open R          2. load a data.frame             3. access scikit-learn
# 4. split / train   5. receive predictions          6. return them to R
# 7. plot / save     8. factor / date semantics preserved
library(rpython)

df <- data.frame(
  x1 = rnorm(200), x2 = runif(200),
  g  = factor(sample(c("north", "south"), 200, TRUE), levels = c("south", "north"), ordered = TRUE),
  d  = as.Date("2024-01-01") + 0:199
)
df$y <- 2 * df$x1 - df$x2 + as.integer(df$g) + rnorm(200, sd = 0.3)

py <- python()                                         # 1./3. Python worker with the same envelope
py$assign("df", df)                                    # 8. ordered factor -> ordered categorical, Date -> date
cat("dtypes in pandas:\n"); print(py$run("df.dtypes.astype(str).to_dict()"))
stopifnot(isTRUE(py$run("df['g'].cat.ordered")))

sk_ms <- py$package("sklearn.model_selection")
sk_lm <- py$package("sklearn.linear_model")
X <- as.matrix(df[, c("x1", "x2")]); yv <- df$y
split <- sk_ms$train_test_split(X, yv, test_size = 0.25, random_state = 1L)   # 4.
m <- sk_lm$LinearRegression()
m$fit(split[[1]], split[[3]])
pred <- m$predict(split[[2]])                            # 5./6. numpy -> R numeric vector
cat("R2 on test:", cor(pred, split[[4]])^2, "\n")
png("scenario_b_pred.png"); plot(split[[4]], pred, xlab = "observed", ylab = "predicted"); abline(0, 1); dev.off()   # 7.
back <- py$get("df")
stopifnot(identical(back$g, df$g), identical(back$d, df$d))                 # 8. round trip
rpx_explain(df)
py$close()
