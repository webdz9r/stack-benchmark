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
| `DB_READERS` | CPU count | read connections, and the size of Tokio's blocking pool |
| `TOKIO_WORKER_THREADS` | CPU count | async worker threads (the core budget) |
| `RUST_LOG` | `address_book=info,tower_http=info` | log filter |

## Notes

- Migrations are compiled in from `../migrations/` (`include_str!`).
- `.cargo/config.toml` sets `SQLITE_DEFAULT_MEMSTATUS=0` and undefines
  `SQLITE_ENABLE_MEMORY_MANAGEMENT` (DB-2); changing it rebuilds `libsqlite3-sys`.
- The global allocator is jemalloc (`tikv-jemallocator`); its build needs
  `make`, which the Dockerfile installs. SQLite keeps the system malloc.
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
- **Blocking pool capped at `DB_READERS` threads** (`main.rs`). Tokio grows
  the pool to 512 threads, and with 50 busy connections ~80 of them queued for
  the 4 read connections, so each query woke and parked several threads (3.2
  context switches per request). Cheap natively, expensive in Docker's VM:
  single contact went from 35,000 to 64,000–66,000 req/s in Docker (1.0
  switch per request, 13 threads instead of 87). Writes, the checkpoint and
  static files queue in the same pool, which is the cost: write p99 at 6,000
  users rose from ~11 ms to 44–61 ms, while overall p99 fell from 61–72 ms to
  41–53 ms (A/B against the old build, two rounds). A dedicated write thread
  is the next thing to try. Natively (spot check, not a suite run) cap +
  jemalloc gave 99,900 single-contact and 28,600 list-page req/s, against
  71,500 and 27,300 in the last native suite run.
- **jemalloc** (`tikv-jemallocator`): glibc's malloc cost ~25% on list pages
  in Docker. Measured by preloading allocators into the same image, pool
  capped, two rounds: list page 16,200 → 21,400 req/s with jemalloc (mimalloc
  18,000), single contact 66,000 → 75,600.
- **Semaphore vs. cap:** a semaphore of `DB_READERS` in front of
  `spawn_blocking` (reads wait on the async side) didn't move native p99. In
  Docker it reached only ~46,000 single-contact req/s (threads still park,
  2.3 switches per request), but it never hit the CPU quota, so list-page p99
  at saturation was 4 ms against ~46 ms with the cap. On the mixed user ramp
  the two were level, so the cap won on throughput.
- **Didn't help:** 8 async workers instead of 4.
- **Mixed load moved less:** on a quiet machine the old build already held
  6,000 users at p99 ~55–72 ms in Docker; the published ~5,250 came from a run
  flagged busy. Cap + jemalloc, A/B over two rounds: p99 at 5,000 users
  37–57 → 23–25 ms, at 6,000 61–72 → 41–53 ms. The cap alone was worse at
  6,000 (92–98 ms): jemalloc carries the mixed-load gain.
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
