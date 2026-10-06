# Optimization log

Every performance change made to a stack, in order, with what it did. This
includes what didn't help: a dead end recorded here is one nobody repeats.

Each stack's README has the full story in its **Optimizing** section (how it was
found, tools, open leads); this log is the dated index across all of them. For
the method, see [`optimizing.md`](optimizing.md).

**How to add an entry:** one row per change, newest last. Give the date, the
mode the effect was measured in (Docker or native), before → after with the
metric, and the status:
- **kept:** in the code now
- **reverted:** tried, then undone
- **no effect:** tried and measured, didn't help
- **open:** found, not acted on yet

Capacity is simulated users at p99 ≈ 100 ms (the suite's headline). Numbers
from a run the suite flagged busy are marked *(busy)*.

Entries dated "before 2026-09-30" predate the repo's history, so their exact
dates weren't recorded.

## Rust (reference)

| When | Change | Effect | Status |
| --- | --- | --- | --- |
| before 2026-09-30 | moka cache: LRU instead of TinyLFU, which rejected fresh entries after each generation bump | hit rate ~50% → ~65%; the biggest of the first three fixes | kept |
| before 2026-09-30 | SQLite built with `DEFAULT_MEMSTATUS=0`, without `ENABLE_MEMORY_MANAGEMENT` (`.cargo/config.toml`) | removes two global mutexes from the read path | kept |
| before 2026-09-30 | `flate2` on the `zlib-rs` backend instead of pure-Rust `miniz_oxide` | native: p99 at 4,000 users 117 → 48 ms; capacity (all three fixes) ~3,800 → ~5,100 | kept |
| before 2026-09-30 | semaphore in front of `spawn_blocking`; 8 async workers instead of 4 | native: neither moved p99 | no effect |
| 2026-10-06 | blocking pool capped at `DB_READERS` threads (was up to 512; ~80 in use, 3.2 context switches per query) | Docker: single contact 35,000 → 64,000–66,000 req/s; write p99 at 6,000 users ~11 → 44–61 ms | kept |
| 2026-10-06 | semaphore of `DB_READERS` in front of reads, instead of the cap | Docker: single contact ~46,000 req/s, but never throttled (list p99 at saturation 4 ms vs 46 ms) | no effect (cap kept) |
| 2026-10-06 | jemalloc as the global allocator | Docker: list page 16,200 → 21,400 req/s; with the cap, single contact 35,000 → 73,600, list 14,400 → 20,900; capacity ~5,250 *(busy)* → ~5,150 | kept |
| open | dedicated write thread, so writes don't queue behind reads in the capped pool | | open |
| open | gzip each cache entry once when stored, instead of on every hit | | open |

## Python

| When | Change | Effect | Status |
| --- | --- | --- | --- |
| before 2026-09-30 | SQLite memory statistics off via `sqlite3_config` through `ctypes`, before `import sqlite3` | native: ~2,050 → ~3,050 users; p99 at 3,000 users 690 → 36 ms | kept |
| before 2026-09-30 | one free-threaded process (Python 3.14t, no GIL, `msgspec`) | topped out at ~1,500 req/s: one event loop running Starlette | no effect |
| 2026-10-05 | reads `async def` on the event loop instead of a 4-thread pool per worker (sqlite3 trades the GIL on every row) | Docker: ~2,050 *(busy)* → ~2,450 users; single contact 5,800 → 59,000 req/s; list page 1,400 → 14,900; p99 at 1,000 users 11 → 29 ms | kept |
| 2026-10-05 | `DB_READERS=1` only (one thread, same hop) | Docker: single contact 13,200, list 6,100 req/s | superseded |
| 2026-10-05 | cache misses on a 2-thread pool, hits on the loop | Docker: p99 at 1,000 users 13 ms, but searches queued for the GIL (p50 ~700 ms at 3,000 users) | no effect |
| 2026-10-05 | writes on the event loop too | Docker: busy-handler sleeps stall the loop; p99 297 ms at 2,000 users | no effect |
| 2026-10-05 | `sys.setswitchinterval(0.0005)` | Docker: write p99 at 1,000 users ~45 → ~22 ms | kept |
| 2026-10-05 | uvicorn `--timeout-keep-alive 120` (was 5 s; the load generator pools for 90 s) | Docker: connection resets 2 in 12 runs → 0 in 5 | kept |

## Node

| When | Change | Effect | Status |
| --- | --- | --- | --- |
| before 2026-09-30 | one process with reader threads instead of 4 cluster workers (4 caches missed ~58% each) | native: ~2,900 → ~5,050 users; single contact ~70,000 → ~39,000 req/s (a message hop per uncached request) | kept |
| before 2026-09-30 | reader threads on the built-in `node:sqlite` (global locks on) | native: p99 630 ms at 2,000 users, worse than the cluster; switched to `better-sqlite3`, whose SQLite has no global locks | reverted |

## Rails

| When | Change | Effect | Status |
| --- | --- | --- | --- |
| before 2026-09-30 | one thread per Puma worker (`RAILS_MAX_THREADS=1`); the sqlite3 gem holds the GVL during queries | native, raw SQL: ~2,250 → ~3,000 users; p99 at 3,000 users ~590 → ~140 ms. ActiveRecord: neutral | kept |
| before 2026-09-30 | GC tuning (`RUBY_GC_HEAP_*_INIT_SLOTS`, malloc limits) | ~1,430 req/s either way | no effect |
| before 2026-09-30 | removing unneeded middleware (`Rack::Runtime`, `RequestId`, `RemoteIp`, `Sendfile`, logger) | ~1,430 req/s either way | no effect |
| open | a driver that releases the GVL (e.g. `extralite`), raw data layer only | | open |

## Go

| When | Change | Effect | Status |
| --- | --- | --- | --- |
| before 2026-09-30 | keep `-O2` in `CGO_CFLAGS` (setting it had dropped the default) | native: ~1,500 → ~5,500 users | kept |
| open | p99 at 6,000 users (~133 ms) | | open |

## C#

| When | Change | Effect | Status |
| --- | --- | --- | --- |
| before 2026-09-30 | SQLite memory statistics off at startup (`Db.cs`) | native: ~3,250 → 6,000+ users | kept |
| before 2026-09-30 | cache subtracts the size of entries dropped for TTL (~20% of the 64 MiB was dead) | | kept |
| before 2026-09-30 | `DOTNET_ThreadPool_ForceMinWorkerThreads=0x10` | p99 worse | no effect |
| before 2026-09-30 | GC ruled out: Server GC paused 53 ms over a full ramp | | no effect |

## C

| When | Change | Effect | Status |
| --- | --- | --- | --- |
| before 2026-09-30 | SQLite on worker threads, not the libmicrohttpd I/O threads | native: resets at 6,000 users → 0 errors, p99 77 ms; single contact ~91,000 → ~48,000 req/s | kept |
| before 2026-09-30 | `MHD_OPTION_LISTEN_BACKLOG_SIZE 1024` | macOS caps the backlog at 128 | no effect |

## Java (Spring Boot)

| When | Change | Effect | Status |
| --- | --- | --- | --- |
| before 2026-09-30 | Parallel GC instead of G1 | native: p99 at 5,000 users 84 → 71 ms and 172 → 77 ms (two A/Bs); at 6,000, 429 → 170 ms; capacity ~5,250 → ~5,600 | kept |
| before 2026-09-30 | generational ZGC | p99 126 ms at 5,000 users, worse than G1 | no effect |
| open | virtual threads, `-Xmx`, AppCDS for startup | | open |

## Rails + ActiveRecord

Shares the Rails app and its `puma.rb`; see Rails above.
