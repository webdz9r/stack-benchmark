# Python

Python 3.14, FastAPI, uvicorn (uvloop and httptools), the standard `sqlite3`
module, and orjson. It runs as several worker processes, each with a small
thread pool.

## Run

```sh
uv sync
uv run python seed.py 110000                  # optional: fake contacts
DB_READERS=4 uv run uvicorn app.main:app --port 7879 --workers 4 --loop uvloop --http httptools --no-access-log
```

| Setting | Default | |
| --- | --- | --- |
| `DATABASE_PATH` | `data/address-book.db` | SQLite file |
| `--port`, `--workers` | (uvicorn flags) | listen port and worker processes (the core budget); ARCH-6 allows a CLI flag |
| `STATIC_DIR` | `../../frontend/dist` | built frontend |
| `DB_READERS` | `4` | handler threads per worker, each with its own read connection |

## Notes and deviations

- **More than the core budget:** SQLite and gzip release the GIL, so a worker's
  threads can use more than one core. Keep this in mind when comparing results.
  (Before the DB-2 fix below, 4 workers reached about 13 cores under overload,
  most of it threads handing a SQLite mutex back and forth.)
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
- **Still over the core budget:** under overload (4,000+ users) the 4 workers
  use 11–15 cores. Most likely the remaining page-cache lock from
  `ENABLE_MEMORY_MANAGEMENT`, plus the GIL handing off between threads. A
  Python linked to a SQLite built without it is worth trying next: uv's
  free-threaded 3.14t build compiles in a SQLite 3.50.4 without it (its regular
  builds weren't checked).
- **Uneven workers:** uvicorn workers accept from a shared socket, and the load
  generator keeps ~70 keep-alive connections for 3,000 users, so some workers
  get far more connections than others (34 vs 9 seen). Check with
  `lsof -a -p <pid> -iTCP -sTCP:ESTABLISHED` per worker.
- **Tried, didn't help:** one free-threaded process (see Notes).
- **Tools:** macOS `sample <worker pid> 5` (pick the busiest worker with
  `ps -o pcpu`). `__psynch_mutexwait` high in the sample means lock
  contention. See [`docs/optimizing.md`](../../docs/optimizing.md).

## Verify and benchmark

```sh
python3 bench/run.py --stacks python --profile quick   # from the repo root
```

The report must show **pass** for the seed checksum (VER-1) and API parity
(VER-2). The spec is in [`docs/requirements/`](../../docs/requirements/README.md).
