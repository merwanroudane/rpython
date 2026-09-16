\name{rpx_encode}
\alias{rpx_encode}
\alias{rpx_decode}
\alias{rpx_explain}
\alias{rpx_register_encoder}
\alias{rpx_register_decoder}
\title{The portable semantic envelope}
\description{
\code{rpx_encode()} turns an R object into the language-neutral RPython envelope (a list that
serialises to JSON plus optional Arrow IPC files); \code{rpx_decode()} does the reverse.
\code{rpx_explain()} prints which representation would be used.  Package authors can add support
for their own classes with \code{rpx_register_encoder()} / \code{rpx_register_decoder()} without
modifying the package.
}
\usage{
rpx_encode(x, top = TRUE)
rpx_decode(env)
rpx_explain(x)
rpx_register_encoder(detect, encode)
rpx_register_decoder(kind, decode)
}
\arguments{
\item{x}{an R object.}
\item{top}{internal; whether this is the top-level object.}
\item{env}{an envelope list as produced by \code{rpx_encode()} (or received from Python).}
\item{detect}{function(x) returning TRUE when \code{encode} applies.}
\item{encode}{function(x) returning an envelope list with a unique \code{kind}.}
\item{kind}{the envelope kind handled by \code{decode}.}
\item{decode}{function(env) returning an R object.}
}
\value{\code{rpx_encode()} returns a list; \code{rpx_decode()} returns an R object.}
\examples{
env <- rpx_encode(data.frame(x = c(1, NA), f = factor(c("a", "b"))))
env$kind
identical(rpx_decode(env)$f, factor(c("a", "b")))
}
