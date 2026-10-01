# 01 — Architecture and runtime

## 1. Repository placement

- **ARCH-1** The backend MUST live in `backend/<stack>/`, where `<stack>` is a short
  lowercase name (`go`, `csharp`, `elixir`, …).
- **ARCH-2** It MUST apply the shared migration files in `backend/migrations/`
  directly: read them at runtime, or embed them at build time. It MUST NOT keep its
  own copy of the schema. See [02-database.md](02-database.md).
- **ARCH-3** Build output, dependencies and the local database (`data/`) MUST be
  git-ignored in the stack folder, as the existing stacks do.
- **ARCH-4** The stack SHOULD contain two entry points:
  1. the **server**, and
  2. the **seeder** CLI (see [05-seeder.md](05-seeder.md)). The seeder MAY be a
     subcommand of the server binary, as in C# (`AddressBook.dll seed 100000`).

## 2. Configuration

All configuration comes from environment variables. There are no config files the
operator has to edit.

| Variable | Default | Meaning | Req |
| --- | --- | --- | --- |
| `DATABASE_PATH` | `data/address-book.db` (relative to the working directory, which is the stack folder) | SQLite file. The file and any missing parent directories MUST be created if absent. | **ARCH-5** MUST |
| `BIND_ADDR` or `PORT` (+ `HOST`) | `127.0.0.1:<stack port>` | Listen address. Default to loopback, not `0.0.0.0`. | **ARCH-6** MUST be configurable, **host included** (containers listen on `0.0.0.0`, CTR-10): by these variables, or by the server's own settings (uvicorn's `--host`/`--port` or `UVICORN_HOST`/`UVICORN_PORT`, for example) |
| `STATIC_DIR` | `../../frontend/dist` | Built frontend to serve, if `index.html` exists there | **ARCH-7** MUST |
| `DB_READERS` | CPU count | Size of the read connection pool | **ARCH-8** SHOULD, where the stack has a pool |
| stack-specific concurrency knob | CPU count | Worker threads/processes (e.g. `TOKIO_WORKER_THREADS`, `GOMAXPROCS`, `WORKERS`, `WEB_CONCURRENCY`) | **ARCH-9** MUST |

- **ARCH-10** The benchmark runs every stack on a **4-core budget**. The stack MUST
  expose environment variables that limit it to about 4 cores of parallel work, and
  its `bench.json` manifest (`env` with `{cores}`, see [`bench/README.md`](../../bench/README.md)) MUST apply them, and its README MUST document which
  ones.

## 3. Process and concurrency model

The reference is one process with an async runtime (Tokio). Blocking SQLite work
runs on a separate blocking-thread pool, so it never stalls the event loop.

- **ARCH-11** SQLite calls MUST NOT block an event-loop thread that is serving other
  connections. Either use a thread-per-request model, or move database work to a
  blocking pool (for example `spawn_blocking`, or a worker thread pool).
  *Exception:* a single-threaded runtime that scales by running worker processes
  MAY call synchronous SQLite on its event loop, since each worker only ever does
  one thing at a time. Prefer one process with a reader-thread pool where the
  runtime has threads (Node has `worker_threads`): each process has its own
  response cache, so N processes miss up to N times as often. With 4 cluster
  workers, each Node worker missed on about 58% of cached requests, against
  18–24% for C#'s single cache. The driver then needs a SQLite without global
  locks (DB-2), or the threads serialize on them.
- **ARCH-12** Access to the database MUST follow the **one writer, many readers**
  model:
  - **Writes** go through a **single write connection**, serialized in the process
    (by a mutex or a single-threaded queue). SQLite allows one writer at a time;
    serializing in the process avoids connections fighting over the database lock.
  - **Reads** use a **pool of read-only connections** (`DB_READERS` of them). Open
    them read-only, with `SQLITE_OPEN_READ_ONLY` or `?mode=ro`, and without SQLite's
    per-connection mutex (`SQLITE_OPEN_NO_MUTEX`) where the driver allows it.
  - Under WAL, readers never block the writer or each other.
  - A single-threaded worker process (the ARCH-11 exception) MAY use one
    connection for both its reads and its writes, since it can't run two queries
    at once. It still needs a separate connection for change detection (CACHE-10).
- **ARCH-13** Multi-process stacks (Puma workers, uvicorn workers)
  MUST give each process its own writer connection and readers, and SHOULD let
  SQLite's lock and the 5 s busy timeout arbitrate writes between processes. Each
  process has its own response cache. See [04-caching-and-http.md §
  Change detection](04-caching-and-http.md#3-change-detection-the-generation).
- **ARCH-14** The writer connection MUST be opened first, with its pragmas set and
  migrations run, **before** any reader connects. The readers then see a database
  that already exists, in WAL mode, at the current schema version.

## 4. Startup sequence

1. Initialize logging.
2. Resolve `DATABASE_PATH` and create its parent directories.
3. Open the writer connection, apply the pragmas ([02-database.md §3](02-database.md#3-connection-pragmas)),
   and run any pending migrations ([02-database.md §2](02-database.md#2-migrations)).
4. Open the read pool (every reader gets the same pragmas).
5. Start the **WAL checkpoint task**: every 5 s ([02-database.md §4](02-database.md#4-wal-checkpointing)).
6. Create the response cache: 64 MiB, 1 s maximum staleness, 30 s TTL.
7. Mount the API under `/api`.
8. If `STATIC_DIR/index.html` exists, mount the static SPA as the fallback.
9. Add gzip compression (and, optionally, request tracing).
10. Bind and serve, with graceful shutdown on SIGINT (Ctrl-C).

- **ARCH-15** The server MUST be ready to answer `GET /api/health` as soon as it is
  listening. The benchmark measures "startup to first response" by polling that
  URL.
- **ARCH-16** Startup MUST NOT do per-row work over the contacts, such as
  rebuilding the search index or warming caches. With 110k rows, that would distort
  the startup metric.

## 5. Static frontend serving

- **ARCH-17** When `STATIC_DIR/index.html` exists, any request that does not match
  an `/api` route MUST be served from `STATIC_DIR` if the file exists, and MUST
  otherwise get `index.html` (200) as the SPA fallback.
- **ARCH-18** Unknown paths **under `/api`** MUST return `404` with the JSON body
  `{"error":"not found"}`, and never `index.html`.
- **ARCH-19** When there is no frontend build, all non-API paths return a 404 (with
  a JSON body `{"error":"not found"}` preferred).
- **ARCH-20** The server MUST NOT add CORS headers. In development the Vite dev
  server proxies `/api` to the backend. In production the frontend has the same
  origin. Without CORS, other sites can't read the contacts.

## 6. Shutdown

- **ARCH-21** On SIGINT the server SHOULD stop accepting connections, let in-flight
  requests finish, and exit 0. On SIGTERM it MAY exit immediately. SQLite in WAL
  mode is crash-safe either way.

## 7. Logging

- **ARCH-22** SHOULD log a line at startup with the database path and the number
  of readers, one for each migration applied, one for the listen address, and one
  saying whether the frontend is being served.
- **ARCH-23** Internal errors (HTTP 500) MUST log the underlying message on the
  server side. The client only ever sees `internal server error`.
- **ARCH-24** Per-request access logging MUST be off by default, or cheap enough
  not to affect the benchmark (the Python run uses `--no-access-log`, for example).
  The reference uses `tower_http::trace` at the default filter level, which logs
  nothing per request at `info`.

## 8. Security posture (intentionally minimal)

This is a single-user benchmark app.

- No authentication and no authorization.
- No rate limiting.
- The API is bound to loopback by default.
- All SQL MUST use bound parameters for user-supplied values. The only strings
  interpolated into SQL are fixed table names, fixed ORDER BY clauses and
  WHERE clauses built from fixed fragments.
- Search input is converted to a sanitized FTS5 expression (see
  [02-database.md §6](02-database.md#6-full-text-search)) before it is bound. Raw
  user text MUST NOT be passed to `MATCH`.
