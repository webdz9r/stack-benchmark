# Rust: benchmark results

[← All backends](../summary.md)

|  |  |
| --- | --- |
| **CPU** | Apple M5 Max |
| **Cores** | 18 physical / 18 logical (6 Super, 12 Performance) |
| **Memory** | 36.0 GB |
| **OS** | macOS 27.0 (kernel 27.0.0, arm64) |
| **Power** | AC power |
| **Mode** | Docker 29.2.1 (Docker Desktop, 18 CPUs / 7.7 GB for containers); each server in a container limited to 4 CPUs / 4g, load generator on the Docker network |
| **Date** | 2026-10-06 10:01:47 |
| **Profile** | standard: the published numbers: 6 user levels (~6 min per stack) |
| **Core budget** | 4 cores per server (the load generator runs on the same machine) |
| **Dataset** | 110,000 contacts |
| **Memory metric** | container working set (cgroup memory.current minus inactive_file) |
| **Repo commit** | 0a9651a (with uncommitted changes) |

**Other programs:** used up to 1.6 cores (threshold 1.8)

**Stack:** Axum, rusqlite (bundled SQLite), moka cache  
**Concurrency:** 1 process, 4 Tokio threads, 4 read connections  

## Summary

| Metric | Value |
| --- | ---: |
| Users at p99 ≈ 100 ms | ~5,150 |
| Startup to first response | 15.0 ms |
| Idle memory | 13 MB |
| Peak memory after a load level | 258 MB |
| Processes | 3 |
| Seed checksum (VER-1) | ✅ pass |
| API parity (VER-2) | — (reference stack) |
| Seeding | 100,000 contacts in 2.9 s (34,582/s) |
| Image | debian:trixie-slim runtime, 156MB |
| SQLite in the image | 3.53.2 |

## Simulated users

| Users | req/s | p50 | p95 | p99 | Errors | CPU cores | Memory after | Other programs |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 | 633 | 0.8 ms | 7.1 ms | 12.0 ms | 0 | 1.05 | 158 MB | 1.55 cores |
| 2,000 | 1,261 | 0.5 ms | 6.4 ms | 10.2 ms | 0 | 1.56 | 188 MB | 1.15 cores |
| 3,000 | 1,902 | 0.5 ms | 7.2 ms | 11.9 ms | 0 | 2.14 | 208 MB | 0.91 cores |
| 4,000 | 2,552 | 0.6 ms | 15.0 ms | 34.0 ms | 0 | 2.74 (throttled 9%) | 224 MB | 0.93 cores |
| 5,000 | 3,168 | 1.3 ms | 39.5 ms | 62.0 ms | 0 | 3.31 (throttled 36%) | 228 MB | 1.00 cores |
| 6,000 | 3,697 | 5.4 ms | 281 ms | 352 ms | 0 | 3.73 (throttled 68%) | 258 MB | 1.01 cores |

### p99 by request type

| Request type | 1,000 users | 2,000 users | 3,000 users | 4,000 users | 5,000 users | 6,000 users |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Search (typed) | 10.0 ms | 8.7 ms | 10.7 ms | 33.3 ms | 58.8 ms | 345 ms |
| A–Z index for a search | 7.5 ms | 7.3 ms | 9.2 ms | 31.7 ms | 56.8 ms | 343 ms |
| List page | 25.4 ms | 24.2 ms | 23.6 ms | 36.1 ms | 65.0 ms | 360 ms |
| A–Z index | 11.3 ms | 10.3 ms | 11.6 ms | 33.5 ms | 59.9 ms | 347 ms |
| Open a contact | 3.8 ms | 4.9 ms | 7.0 ms | 33.6 ms | 64.0 ms | 359 ms |
| Save a contact | 11.6 ms | 11.3 ms | 11.4 ms | 32.9 ms | 62.1 ms | 356 ms |
| Tags | 9.2 ms | 7.9 ms | 9.3 ms | 34.5 ms | 63.5 ms | 358 ms |
| Stats | 11.8 ms | 9.1 ms | 10.7 ms | 35.0 ms | 65.0 ms | 360 ms |

Simulated users open the app, then act every ~3 s on average: scroll or jump letters (35%), type a search (30%), open a contact (25%), switch view (5%), edit and save (5%). Each level warms up for 10 s and is measured for 30 s. Capacity is where p99 latency crosses 100 ms, interpolated between tested levels. A level whose p99 passes 2,000 ms ends that stack's ramp. Single-endpoint tests use 50 clients with no pauses. CPU is CPU-seconds used during the measured window divided by its length (1.0 = one core).

## Single endpoints

| Request | req/s | p50 | p99 | Errors |
| --- | ---: | ---: | ---: | ---: |
| Single contact | 73,579 | 0.5 ms | 0.9 ms | 0 |
| List page 1 (uncached) | 20,916 | 1.3 ms | 45.1 ms | 0 |
| List page at offset 55,000 | 5,562 | 7.6 ms | 26.1 ms | 0 |
| Search `smith` (cached) | 74,205 | 0.6 ms | 1.5 ms | 0 |
| A–Z index (cached) | 141,566 | 0.3 ms | 0.7 ms | 0 |
| Stats (cached) | 184,014 | 0.3 ms | 0.5 ms | 0 |

## Optimization history

Every change tried on this stack, oldest first, from [the optimization log](../../docs/optimization-log.md).

| When | Change | Effect | Status |
| --- | --- | --- | --- |
| before 2026-09-30 | moka cache: LRU instead of TinyLFU, which rejected fresh entries after each generation bump | hit rate ~50% → ~65%; the biggest of the first three fixes | kept |
| before 2026-09-30 | SQLite built with `DEFAULT_MEMSTATUS=0`, without `ENABLE_MEMORY_MANAGEMENT` (`.cargo/config.toml`) | removes two global mutexes from the read path | kept |
| before 2026-09-30 | `flate2` on the `zlib-rs` backend instead of pure-Rust `miniz_oxide` | native: p99 at 4,000 users 117 → 48 ms; capacity (all three fixes) ~3,800 → ~5,100 | kept |
| before 2026-09-30 | semaphore in front of `spawn_blocking`; 8 async workers instead of 4 | native: neither moved p99 | no effect |
| 2026-10-06 | blocking pool capped at `DB_READERS` threads (was up to 512; ~80 in use, 3.2 context switches per query) | Docker: single contact 35,000 → 64,000–66,000 req/s; write p99 at 6,000 users ~11 → 44–61 ms | kept |
| 2026-10-06 | semaphore of `DB_READERS` in front of reads, instead of the cap | Docker: single contact ~46,000 req/s, but never throttled (list p99 at saturation 4 ms vs 46 ms) | no effect (cap kept) |
| 2026-10-06 | jemalloc as the global allocator | Docker: list page 16,200 → 21,400 req/s; with the cap, single contact 35,000 → 73,600, list 14,400 → 20,900; capacity ~5,250 *(busy)* → ~5,150 | kept |
| open | dedicated write thread, so writes don't queue behind reads in the capped pool |  | open |
| open | gzip each cache entry once when stored, instead of on every hit |  | open |
