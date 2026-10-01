# Rust (reference implementation)

Axum + rusqlite (SQLite bundled and compiled in) + moka. This is the
**reference**: the spec in `docs/requirements/` was derived from it, and every
other stack is checked against it.

## Run

```sh
cargo run --release --bin seed -- 110000     # optional: fake contacts
cargo run --release                          # API + built UI on :7878
```

| Variable | Default | |
| --- | --- | --- |
| `DATABASE_PATH` | `data/address-book.db` | SQLite file |
| `BIND_ADDR` | `127.0.0.1:7878` | listen address |
| `STATIC_DIR` | `../../frontend/dist` | built frontend |
| `DB_READERS` | CPU count | read connections |
| `TOKIO_WORKER_THREADS` | CPU count | async worker threads (the core budget) |
| `RUST_LOG` | `address_book=info,tower_http=info` | log filter |

## Notes

- Migrations are compiled in from `../migrations/` (`include_str!`).
- `.cargo/config.toml` sets `SQLITE_DEFAULT_MEMSTATUS=0` and undefines
  `SQLITE_ENABLE_MEMORY_MANAGEMENT` (DB-2); changing it rebuilds `libsqlite3-sys`.
- The search tokenizer uses the `unicode-general-category` crate (DB-12), since
  the standard library has no general-category lookup.

## Optimizing

Findings so far (see also [`docs/optimizing.md`](../../docs/optimizing.md)):

- **Gzip backend:** `flate2` is set to the `zlib-rs` backend in `Cargo.toml`.
  The default `miniz_oxide` is pure Rust and slower, and tower-http compresses
  on the async workers, so every other connection on that worker waits. The
  switch took p99 at 4,000 users from ~117 ms to ~48 ms. Check with
  `cargo tree -i flate2 -e features`.
- **SQLite build (`.cargo/config.toml`):** `libsqlite3-sys` compiles SQLite with
  memory statistics and `SQLITE_ENABLE_MEMORY_MANAGEMENT` on. Both are global
  mutexes that serialize the read pool, so the config sets
  `-DSQLITE_DEFAULT_MEMSTATUS=0 -USQLITE_ENABLE_MEMORY_MANAGEMENT`.
- **Cache eviction:** moka is set to `EvictionPolicy::lru()`. Its default
  TinyLFU admission rejected new entries after each generation bump, and the
  hit rate fell from ~65% to ~50% once the 64 MiB filled. This was the biggest
  of the three fixes.
- **Didn't help:** a semaphore in front of `spawn_blocking` (so waiting reads
  queue on the async side), and 8 async workers instead of 4. Neither moved
  p99.
- **Open lead:** at 6,000 users Rust (~490 ms p99) now trails Go and C#. gzip
  still runs on the async workers for every response, cache hits included.
  Compressing each cache entry once when it's stored, or compressing on the
  blocking pool, is the next thing to try.
- **Tools:** macOS `sample <pid> 8` for native CPU; a temporary probe in
  `Db::read` timing `pool.get()` wait against query time showed the read pool
  was the queue.

## Docker

`Dockerfile` builds this stack on Debian 13 slim with the same settings as
native ([07-containers.md](../../docs/requirements/07-containers.md)).
Run it with `docker compose --profile rust up --build` from the repo root, or
benchmark it with `python3 bench/run.py --stacks rust` (Docker is the default; add `--mode native` to use the toolchain on your machine).

## Verify and benchmark

```sh
python3 bench/run.py --stacks rust --profile quick   # from the repo root
```

The report must show **pass** for the seed checksum (VER-1) and API parity
(VER-2). The spec is in [`docs/requirements/`](../../docs/requirements/README.md).
