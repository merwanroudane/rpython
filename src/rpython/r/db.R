# db.R -- database connection references shared between R and Python.
#
# A connection reference NEVER carries a secret.  It carries the backend,
# host/port/database/user and, optionally, the *name* of an environment
# variable holding the password (``secret_env``).  Both runtimes open
# their own native connection from the same reference and push queries
# down instead of copying tables.

rpx_connection_ref <- function(con) {
  if (is.null(con)) return(NULL)
  cls <- class(con)[1]
  backend <- switch(cls,
                    SQLiteConnection = "sqlite", duckdb_connection = "duckdb", PqConnection = "postgresql",
                    MariaDBConnection = "mysql", "Microsoft SQL Server" = "mssql", OdbcConnection = "odbc", tolower(cls))
  info <- tryCatch(DBI::dbGetInfo(con), error = function(e) list())
  ref <- list(backend = backend, database = info$dbname %||% info$db.version %||% NULL, host = info$host %||% NULL,
              port = info$port %||% NULL, user = info$username %||% info$user %||% NULL, secret_env = NULL)
  if (backend == "sqlite") ref$database <- info$dbname
  if (backend == "duckdb") {
    ref$database <- tryCatch(con@driver@dbdir, error = function(e) ":memory:")
    ref$read_only <- tryCatch(isTRUE(con@driver@read_only), error = function(e) FALSE)
  }
  ref
}

rpx_db_connect <- function(ref) {
  if (is.null(ref) || is.null(ref$backend)) return(NULL)
  key <- paste(ref$backend, ref$host %||% "", ref$port %||% "", ref$database %||% "", ref$user %||% "", sep = "|")
  if (exists(key, envir = .rpx_state$db_connections, inherits = FALSE)) {
    con <- get(key, envir = .rpx_state$db_connections)
    if (tryCatch(DBI::dbIsValid(con), error = function(e) FALSE)) return(con)
  }
  pw <- if (!is.null(ref$secret_env)) Sys.getenv(ref$secret_env, unset = NA) else NA
  if (!is.null(ref$secret_env) && is.na(pw)) stop("environment variable ", ref$secret_env, " (database password) is not set in the R process")
  con <- switch(ref$backend,
                sqlite = { rpx_require("RSQLite"); DBI::dbConnect(RSQLite::SQLite(), ref$database %||% ":memory:") },
                duckdb = { rpx_require("duckdb"); DBI::dbConnect(duckdb::duckdb(), dbdir = ref$database %||% ":memory:", read_only = isTRUE(ref$read_only)) },
                postgresql = { rpx_require("RPostgres"); DBI::dbConnect(RPostgres::Postgres(), dbname = ref$database, host = ref$host, port = ref$port %||% 5432, user = ref$user, password = if (is.na(pw)) NULL else pw) },
                mysql = , mariadb = { rpx_require("RMariaDB"); DBI::dbConnect(RMariaDB::MariaDB(), dbname = ref$database, host = ref$host, port = ref$port %||% 3306, username = ref$user, password = if (is.na(pw)) NULL else pw) },
                mssql = , odbc = { rpx_require("odbc"); DBI::dbConnect(odbc::odbc(), .connection_string = ref$connection_string %||% NULL, dsn = ref$dsn %||% NULL, driver = ref$driver %||% NULL, server = ref$host %||% NULL, database = ref$database %||% NULL, uid = ref$user %||% NULL, pwd = if (is.na(pw)) NULL else pw) },
                stop("no R adapter for database backend '", ref$backend, "'"))
  assign(key, con, envir = .rpx_state$db_connections)
  con
}

rpx_require <- function(pkg) {
  if (!requireNamespace(pkg, quietly = TRUE)) stop("R package '", pkg, "' is required for this database backend: install.packages('", pkg, "')")
}

#' Share a DBI connection with Python as a lazy relation (no data copied).
#' @export
rpx_relation <- function(con, table = NULL, sql = NULL) {
  structure(list(rpx = 1L, kind = "db_relation", connection = rpx_connection_ref(con), table = table, sql = sql, lazy = TRUE,
                 columns = if (!is.null(table)) as.list(DBI::dbListFields(con, table)) else NULL,
                 meta = list(source_class = "DBIConnection")), class = "rpython_db_relation")
}
