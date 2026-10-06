# Rust: benchmark results

[← All backends](../summary.md)

|  |  |
| --- | --- |
| **CPU** | Apple M5 Max |
| **Cores** | 18 physical / 18 logical (6 Super, 12 Performance) |
| **Memory** | 36.0 GB |
| **OS** | macOS 27.0 (kernel 27.0.0, arm64) |
| **Power** | AC power |
| **Date** | 2026-09-30 12:29:17 |
| **Profile** | standard: the published numbers: 6 user levels (~6 min per stack) |
| **Core budget** | 4 cores per server (the load generator runs on the same machine) |
| **Dataset** | 110,000 contacts |
| **Memory metric** | physical footprint (vmmap) |
| **Repo commit** | uncommitted (with uncommitted changes) |
| **Notes** | rust: zlib-rs gzip, moka LRU, no SQLITE_ENABLE_MEMORY_MANAGEMENT |

**Other programs:** used up to 1.4 cores (threshold 1.8)

**Stack:** Axum, rusqlite (bundled SQLite), moka cache  
**Concurrency:** 1 process, 4 Tokio threads, 4 read connections  
**Versions:** rustc 1.96.0 (ac68faa20 2026-05-25) (Homebrew)  

## Summary

| Metric | Value |
| --- | ---: |
| Users at p99 ≈ 100 ms | ~5,100 |
| Startup to first response | 204 ms |
| Idle memory | 3 MB |
| Peak memory after a load level | 210 MB |
| Processes | 1 |
| Seed checksum (VER-1) | ✅ pass |
| API parity (VER-2) | — (reference stack) |
| Seeding | 100,000 contacts in 2.6 s (37,775/s) |

## Simulated users

| Users | req/s | p50 | p95 | p99 | Errors | CPU cores | Memory after | Other programs |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 | 633 | 0.7 ms | 6.9 ms | 11.1 ms | 0 | 1.04 | 119 MB | 0.80 cores |
| 2,000 | 1,261 | 0.5 ms | 6.7 ms | 11.1 ms | 0 | 1.65 | 147 MB | 1.18 cores |
| 3,000 | 1,902 | 0.5 ms | 8.1 ms | 13.1 ms | 0 | 2.27 | 170 MB | 1.03 cores |
| 4,000 | 2,553 | 0.5 ms | 14.2 ms | 26.8 ms | 0 | 2.81 | 184 MB | 0.75 cores |
| 5,000 | 3,171 | 0.6 ms | 38.0 ms | 57.8 ms | 0 | 3.41 | 196 MB | 1.25 cores |
| 6,000 | 3,699 | 5.5 ms | 246 ms | 486 ms | 0 | 4.07 | 210 MB | 1.37 cores |

### p99 by request type

| Request type | 1,000 users | 2,000 users | 3,000 users | 4,000 users | 5,000 users | 6,000 users |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Search (typed) | 9.0 ms | 9.2 ms | 11.9 ms | 25.9 ms | 55.6 ms | 476 ms |
| A–Z index for a search | 7.1 ms | 7.6 ms | 10.4 ms | 25.0 ms | 53.8 ms | 449 ms |
| List page | 26.1 ms | 25.2 ms | 25.5 ms | 29.7 ms | 61.5 ms | 495 ms |
| A–Z index | 10.4 ms | 10.8 ms | 12.9 ms | 24.5 ms | 57.8 ms | 483 ms |
| Open a contact | 3.2 ms | 5.6 ms | 8.6 ms | 24.3 ms | 59.9 ms | 497 ms |
| Save a contact | 10.6 ms | 9.3 ms | 8.4 ms | 9.0 ms | 9.2 ms | 16.2 ms |
| Tags | 7.9 ms | 9.4 ms | 11.7 ms | 25.0 ms | 62.2 ms | 500 ms |
| Stats | 9.7 ms | 11.0 ms | 13.3 ms | 26.2 ms | 61.3 ms | 502 ms |

Simulated users open the app, then act every ~3 s on average: scroll or jump letters (35%), type a search (30%), open a contact (25%), switch view (5%), edit and save (5%). Each level warms up for 10 s and is measured for 30 s. Capacity is where p99 latency crosses 100 ms, interpolated between tested levels. A level whose p99 passes 2,000 ms ends that stack's ramp. Single-endpoint tests use 50 clients with no pauses. CPU is CPU-seconds used during the measured window divided by its length (1.0 = one core).

## Single endpoints

| Request | req/s | p50 | p99 | Errors |
| --- | ---: | ---: | ---: | ---: |
| Single contact | 71,548 | 0.6 ms | 3.1 ms | 0 |
| List page 1 (uncached) | 27,252 | 1.8 ms | 6.0 ms | 0 |
| List page at offset 55,000 | 5,297 | 9.4 ms | 18.0 ms | 0 |
| Search `smith` (cached) | 70,403 | 0.7 ms | 1.2 ms | 0 |
| A–Z index (cached) | 115,735 | 0.4 ms | 0.7 ms | 0 |
| Stats (cached) | 133,054 | 0.4 ms | 0.7 ms | 0 |

## Optimization history

Every change tried on this stack, oldest first, from [the optimization log](../../../docs/optimization-log.md).

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
