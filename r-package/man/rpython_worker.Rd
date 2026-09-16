\name{rpython_worker}
\alias{rpython_worker}
\alias{rpx_relation}
\title{Serve R to Python}
\description{
\code{rpython_worker()} runs the request loop used by the Python package (\code{rpython.R()});
it is normally started by Python and not called by users.  \code{rpx_relation()} wraps a DBI
connection and table/query as a lazy relation that Python can open on the same data source
without copying rows (secrets are never serialised; use the \code{secret_env} convention).
}
\usage{
rpython_worker(port = NULL, host = "127.0.0.1")
rpx_relation(con, table = NULL, sql = NULL)
}
\arguments{
\item{port}{listen on a TCP port instead of stdin/stdout.}
\item{host}{host to bind.}
\item{con}{a DBI connection.}
\item{table}{table name.}
\item{sql}{SQL text (alternative to \code{table}).}
}
\value{\code{rpython_worker()} returns nothing; \code{rpx_relation()} returns an object of class
\code{rpython_db_relation}.}
