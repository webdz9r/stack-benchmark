# Python

Python 3.14, FastAPI, uvicorn (uvloop and httptools), the standard `sqlite3`
module, and orjson. It runs as several worker processes. Each one serves reads
on its event loop and writes on a single thread.

## Run

```sh
uv sync
uv run python seed.py 110000                  # optional: fake contacts
uv run uvicorn app.main:app --port 7879 --workers 4 --loop uvloop --http httptools --no-access-log --timeout-keep-alive 120
```

| Setting | Default | |
| --- | --- | --- |
| `DATABASE_PATH` | `data/address-book.db` | SQLite file |
| `--port`, `--workers` | (uvicorn flags) | listen port and worker processes (the core budget); ARCH-6 allows a CLI flag |
| `STATIC_DIR` | `../../frontend/dist` | built frontend |

## Notes and deviations

- **No `DB_READERS` (ARCH-8):** read handlers are `async def` and run on the
  worker's event loop, on one read connection per worker. The pool is the
  worker processes. Write handlers are plain `def` on a one-thread pool, so a
  write waiting on another worker's lock (busy_timeout) doesn't stall the loop.
- Each worker has its own response cache, and detects writes by any process
  through `PRAGMA data_version` (CACHE-10).
- **DB-2 at runtime:** the `sqlite3` module uses the SQLite Python was built
  with, which keeps memory statistics on. `app/__init__.py` calls
  `sqlite3_config(SQLITE_CONFIG_MEMSTATUS, 0)` through `ctypes` before anything
  imports `sqlite3` (the import initializes SQLite, after which the setting is
  refused). This cut p99 at 3,000 users from about 690 ms to 36 ms. Homebrew's
  SQLite also has `SQLITE_ENABLE_MEMORY_MANAGEMENT`, which can't be undone at
  runtime.
- **Why not one free-threaded process:** tried on Python 3.14t (no GIL, one
  shared cache, `msgspec` in place of orjson, which has no free-threaded build).
  It topped out at about 1,500 req/s, because every request still passes through
  one asyncio event loop running Starlette in Python. Four processes means four
  event loops.
- Booleans and integers in request bodies are strict (`StrictBool`,
  `StrictInt`): `"yes"` is not a boolean (03-api.md §7).
- The seeder's `ContactInput` and `Repo` code is shared with the server.

## Optimizing

- **SQLite memory statistics** (see Notes): the biggest fix, ~2,050 to ~3,050
  users. The setting must be applied before `import sqlite3`; after the import
  `sqlite3_config` returns 21 (`SQLITE_MISUSE`). Confirm it took effect with
  `sqlite3_memory_used()`, which stays 0 when statistics are off.
- **Over the core budget (native, before reads moved to the event loop):**
  under overload (4,000+ users) the 4 workers used 11–15 cores. Most likely
  the remaining page-cache lock from `ENABLE_MEMORY_MANAGEMENT`, plus the GIL handing off between threads. A
  Python linked to a SQLite built without it is worth trying next: uv's
  free-threaded 3.14t build compiles in a SQLite 3.50.4 without it (its regular
  builds weren't checked).
- **Uneven workers:** uvicorn workers accept from a shared socket, and the load
  generator keeps ~70 keep-alive connections for 3,000 users, so some workers
  get far more connections than others (34 vs 9 seen). Check with
  `lsof -a -p <pid> -iTCP -sTCP:ESTABLISHED` per worker.
- **Tried, didn't help:** one free-threaded process (see Notes).
- **Reads on the event loop, not a thread pool:** the biggest fix in Docker.
  Reads used to be plain `def` on 4 threads per worker, on the theory that
  sqlite3 releases the GIL so queries overlap. But it drops and retakes the GIL
  on every row, so the handler threads and the event loop queued for it (up to
  the 5 ms switch interval each time), and under `--cpus=4` the 4 workers ×
  ~7 threads were throttled 100% from 3,000 users. Docker single endpoints, same
  machine: single contact 5,000 → 53,700 req/s, list page 1,250 → 13,100,
  cached A–Z index 15,200 → 46,500. Just `DB_READERS=1` (one thread) got
  13,200 / 6,100 / 15,700: the hop itself was the rest. In the suite (Docker,
  standard profile, 2026-10-05): ~2,050 → ~2,450 users at p99 ≈ 100 ms,
  single contact 5,800 → 59,000 req/s, list page 1,400 → 14,900. The cost:
  p99 at 1,000 users rose from 11 to 29 ms, since a slow search now holds up
  its worker, and past capacity it degrades more steeply than Rails.
- **Writes stay on a thread:** on the loop, a write that hits another
  worker's lock sleeps in SQLite's busy handler and stalls every request on that
  worker (p99 297 ms at 2,000 users). On a thread, it waits up to the GIL switch
  interval for each step while holding the write lock;
  `sys.setswitchinterval(0.0005)` cut write p99 at 1,000 users from ~45 ms to
  ~22 ms (A/B, two rounds).
- **Tried, didn't help: cache misses on a thread pool.** Keeping hits on the
  loop and sending misses (1–40 ms aggregates and searches) to 2 threads fixed
  the low-load tail (p99 13 ms at 1,000 users), but searches are mostly misses,
  and on threads they queued for the GIL: p50 ~700 ms at 3,000 users. Inline
  costs some fairness instead: a 30 ms search for a one-letter prefix holds up
  that worker, as it would a Rails worker.
- **Keep-alive 120 s:** uvicorn closes idle connections after 5 s, but the load
  generator's client pools them for 90 s, so a request sent as the server
  closed was reset (a few per run). Rare, so the evidence is thin: 0 resets
  in 5 runs after, 2 in 12 before.
- **Tools:** macOS `sample <worker pid> 5` (pick the busiest worker with
  `ps -o pcpu`). `__psynch_mutexwait` high in the sample means lock
  contention. See [`docs/optimizing.md`](../../docs/optimizing.md).

## Docker

`Dockerfile` builds this stack on Debian 13 slim with the same settings as
native ([07-containers.md](../../docs/requirements/07-containers.md)). Python's image links Debian's own SQLite (3.46.1), not the newer one Homebrew provides natively; the report shows the version.
Run it with `docker compose --profile python up --build` from the repo root, or
benchmark it with `python3 bench/run.py --stacks python` (Docker is the default; add `--mode native` to use the toolchain on your machine).

## Verify and benchmark

```sh
python3 bench/run.py --stacks python --profile quick   # from the repo root
```

The report must show **pass** for the seed checksum (VER-1) and API parity
(VER-2). The spec is in [`docs/requirements/`](../../docs/requirements/README.md).
