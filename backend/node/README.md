# Node

Node 26, Fastify 5, `better-sqlite3`, and `@fastify/compress`. It runs as one
process: the event loop does HTTP, the response cache and gzip, and SQLite runs
on `worker_threads` (one writer plus `DB_READERS` readers).

## Run

```sh
npm install
node src/seed.js 110000                      # optional: fake contacts
DB_READERS=4 node src/main.js                # :7880
```

| Variable | Default | |
| --- | --- | --- |
| `DATABASE_PATH` | `data/address-book.db` | SQLite file |
| `HOST` / `PORT` | `127.0.0.1` / `7880` | listen address |
| `STATIC_DIR` | `../../frontend/dist` | built frontend |
| `DB_READERS` | CPU count | reader threads, one read-only connection each (the core budget) |

## Design

- `src/pool.js` starts the writer thread (it runs the migrations and the WAL
  checkpoint), then the reader threads. Reads go to the next idle reader, oldest
  first; writes go to the writer, each in its own `BEGIN IMMEDIATE` transaction.
- `src/dbthread.js` runs the `repo.js` functions on its connection and returns
  the result as JSON text, so serialization happens off the event loop too.
- One process means one response cache for every request. The previous version
  ran 4 cluster workers with a cache each, and each worker missed on about 58%
  of cached requests (C#, with one cache, misses on 18–24%). That's why it's one
  process.

## Notes and deviations

- **Why `better-sqlite3` rather than the built-in `node:sqlite`:** Node's own
  SQLite is built with memory statistics and `SQLITE_ENABLE_MEMORY_MANAGEMENT`,
  so every allocation and page fetch takes a process-wide lock, and the reader
  threads serialize on it (DB-2). With `node:sqlite` on threads, p99 at 2,000
  users was over 600 ms. `better-sqlite3` bundles the same SQLite version built
  with `SQLITE_DEFAULT_MEMSTATUS=0`, without memory management, and in
  multi-thread mode.
- Change detection is an in-process write counter, as in the Rust reference;
  writes from other processes (a seeder run) are covered by the 30 s TTL.
- A wrong method on a known path returns 404 (Fastify's default), which the spec
  allows.

## Optimizing

- **One process, not a cluster** (see Design): 4 cluster workers meant 4 caches
  and ~58% misses each. Capacity went from ~2,900 to ~5,050 users.
- **The driver's SQLite build decides whether threads help.** With the built-in
  `node:sqlite` (memory statistics and `ENABLE_MEMORY_MANAGEMENT` on, no API to
  change them), reader threads made things *worse* than the cluster: p99 630 ms
  at 2,000 users. Check any new driver with `PRAGMA compile_options` before
  building on it.
- **Trade-off:** every uncached request is a message to a thread and back, so
  the single-contact throughput test fell from ~70k to ~39k req/s.
- **Tools:**
  - `node --cpu-prof --cpu-prof-dir=DIR src/main.js` writes one profile per
    thread on a clean exit. Add a temporary `process.on('SIGTERM', () =>
    process.exit(0))`, and aggregate `.cpuprofile` self time per function.
  - `performance.eventLoopUtilization()` plus the pool's queue length, logged
    once a second, show whether the event loop or the readers are the limit.
    At 2,000 users the loop was only ~13% busy.
  - Lock waits don't appear in `--cpu-prof`: threads blocked on a mutex look
    idle. See [`docs/optimizing.md`](../../docs/optimizing.md).

## Docker

`Dockerfile` builds this stack on Debian 13 slim with the same settings as
native ([07-containers.md](../../docs/requirements/07-containers.md)).
Run it with `docker compose --profile node up --build` from the repo root, or
benchmark it with `python3 bench/run.py --stacks node` (Docker is the default; add `--mode native` to use the toolchain on your machine).

## Verify and benchmark

```sh
python3 bench/run.py --stacks node --profile quick   # from the repo root
```

The report must show **pass** for the seed checksum (VER-1) and API parity
(VER-2). The spec is in [`docs/requirements/`](../../docs/requirements/README.md).
