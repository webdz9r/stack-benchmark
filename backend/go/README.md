# Go

Standard `net/http` (Go 1.22+ routing patterns), `mattn/go-sqlite3` (cgo,
bundled SQLite), `klauspost/compress` for gzip, `singleflight` for the cache.

## Run

```sh
CGO_CFLAGS="-O2 -g -DSQLITE_DEFAULT_MEMSTATUS=0" go build -tags sqlite_fts5 -o server ./cmd/server
CGO_CFLAGS="-O2 -g -DSQLITE_DEFAULT_MEMSTATUS=0" go build -tags sqlite_fts5 -o seed ./cmd/seed
./seed 110000                                # optional: fake contacts
GOMAXPROCS=4 DB_READERS=4 ./server           # :7883
```

| Variable | Default | |
| --- | --- | --- |
| `DATABASE_PATH` | `data/address-book.db` | SQLite file |
| `BIND_ADDR` | `127.0.0.1:7883` | listen address |
| `STATIC_DIR` | `../../frontend/dist` | built frontend |
| `MIGRATIONS_DIR` | `../migrations` | shared migrations, read at runtime |
| `DB_READERS` | `GOMAXPROCS` | read connections |
| `GOMAXPROCS` | CPU count | the core budget |

## Notes

- The `sqlite_fts5` build tag is required: without it the driver's SQLite has no FTS5.
- `CGO_CFLAGS` applies DB-2 (`-DSQLITE_DEFAULT_MEMSTATUS=0`). **Keep `-O2 -g` in it:**
  setting `CGO_CFLAGS` replaces Go's default C flags. Without them, SQLite is
  compiled unoptimized and every query runs about 3x slower (1.8 ms against 0.62 ms
  for a deep list page). `PRAGMA compile_options` shows `DEFAULT_MEMSTATUS=0`
  when the flag took effect.
- A JSON body without a `Content-Type` is accepted, and a wrong method on a known
  path returns 404 (the `/api/` catch-all wins). Both are allowed by the spec
  (03-api.md §7).

## Optimizing

- **Keep `-O2 -g` in `CGO_CFLAGS`** (see Notes). This was the one big Go
  problem: an unoptimized SQLite held Go at ~1,500 users; fixed, it reached
  ~5,500.
- The mattn driver's SQLite is compiled without
  `SQLITE_ENABLE_MEMORY_MANAGEMENT`, and `CGO_CFLAGS` turns memory statistics
  off, so readers don't share a global lock.
- `database/sql` acquires a connection per statement and releases it before Go
  code processes the rows, which keeps connections busy for less time than
  holding one per request.
- **Tools:** `db.Stats()` (`WaitCount`, `WaitDuration`, `InUse`) logged once a
  second shows whether the read pool is the queue: at 4,000 users about 800
  waits a second averaging 1–4 ms. `net/http/pprof` isn't wired in; add it
  temporarily for CPU profiles. See [`docs/optimizing.md`](../../docs/optimizing.md).
- **Not investigated yet:** p99 at 6,000 users (~133 ms).

## Docker

`Dockerfile` builds this stack on Debian 13 slim with the same settings as
native ([07-containers.md](../../docs/requirements/07-containers.md)).
Run it with `docker compose --profile go up --build` from the repo root, or
benchmark it with `python3 bench/run.py --stacks go` (Docker is the default; add `--mode native` to use the toolchain on your machine).

## Verify and benchmark

```sh
python3 bench/run.py --stacks go --profile quick   # from the repo root
```

The report must show **pass** for the seed checksum (VER-1) and API parity
(VER-2). The spec is in [`docs/requirements/`](../../docs/requirements/README.md).
