\name{python}
\alias{python}
\alias{python_start}
\alias{py_run}
\alias{py_eval}
\alias{py_package}
\alias{py_assign}
\alias{py_get}
\alias{py_install}
\alias{py_close}
\alias{py_call}
\alias{py_to_r}
\title{Drive Python from R}
\description{
\code{python()} starts an isolated Python worker (the \pkg{rpython} Python package must be
installed: \code{pip install rpython}) and returns a session object with \code{$run()},
\code{$eval()}, \code{$package()}, \code{$assign()}, \code{$get()}, \code{$install()} and
\code{$close()}.  Python objects with an R equivalent are converted through the semantic
envelope (factors, dates, time zones, missing values, sparse matrices, graphs, geometries ...
are preserved); everything else stays in Python behind a proxy whose attributes and methods
are reachable with \code{$}.
}
\usage{
python(python = NULL, timeout = 60)
python_start(python = NULL, timeout = 60)
py_run(s, code, convert = TRUE)
py_eval(s, code, convert = TRUE)
py_package(s, name)
py_assign(s, name, value)
py_get(s, name, convert = TRUE)
py_install(s, ..., source = "pip")
py_close(s)
py_call(f, ...)
py_to_r(x)
}
\arguments{
\item{python}{path to a Python executable; by default \env{RPYTHON_PYTHON}, \env{RETICULATE_PYTHON},
the active virtualenv/conda environment, then \code{python3}/\code{python} on the PATH.}
\item{timeout}{seconds to wait for the worker to start.}
\item{s}{a session returned by \code{python()}.}
\item{code}{Python source code; the value of the last expression is returned.}
\item{convert}{convert the result to R when a lossless mapping exists (\code{TRUE}) or always keep a proxy.}
\item{name}{a Python module name (\code{py_package}) or variable name.}
\item{value}{an R object to send.}
\item{...}{package names (\code{py_install}) or arguments (\code{py_call}).}
\item{source}{\code{"pip"}, \code{"uv"} or \code{"conda"}.}
\item{f}{a Python callable proxy.}
\item{x}{a Python proxy to convert (possibly partially; reported) to R.}
}
\value{\code{python()} returns an object of class \code{rpython_session}; the other functions return
converted R values or \code{rpx_pyproxy} objects.}
\examples{
\dontrun{
py <- python()
np <- py$package("numpy")
np$arange(3L)
sk <- py$package("sklearn.linear_model")
m <- sk$LinearRegression()
m$fit(matrix(1:4), c(2, 4, 6, 8))
m$coef_
py$close()
}
}
