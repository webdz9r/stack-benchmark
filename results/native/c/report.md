# C: benchmark results

[← All backends](../summary.md)

|  |  |
| --- | --- |
| **CPU** | Apple M5 Max |
| **Cores** | 18 physical / 18 logical (6 Super, 12 Performance) |
| **Memory** | 36.0 GB |
| **OS** | macOS 27.0 (kernel 27.0.0, arm64) |
| **Power** | AC power |
| **Date** | 2026-09-30 11:37:16 |
| **Profile** | standard: the published numbers: 6 user levels (~6 min per stack) |
| **Core budget** | 4 cores per server (the load generator runs on the same machine) |
| **Dataset** | 110,000 contacts |
| **Memory metric** | physical footprint (vmmap) |
| **Repo commit** | uncommitted (with uncommitted changes) |
| **Notes** | C rerun: worker pool (ARCH-11), cache hits on I/O threads |

**Other programs:** used up to 1.4 cores (threshold 1.8)

**Stack:** libmicrohttpd, SQLite amalgamation (compiled in), yyjson, zlib  
**Concurrency:** 1 process, 4 threads, one read connection each  
**Versions:** Apple clang version 21.0.0 (clang-2100.3.34.2); 1.0.10  

## Summary

| Metric | Value |
| --- | ---: |
| Users at p99 ≈ 100 ms | ≥ 6,000 |
| Startup to first response | 7.0 ms |
| Idle memory | 3 MB |
| Peak memory after a load level | 186 MB |
| Processes | 1 |
| Seed checksum (VER-1) | ✅ pass |
| API parity (VER-2) | ✅ pass (71 identical, 0 mismatched; 42/42 contract checks passed) |
| Seeding | 100,000 contacts in 2.6 s (38,945/s) |

## Simulated users

| Users | req/s | p50 | p95 | p99 | Errors | CPU cores | Memory after | Other programs |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 | 633 | 0.7 ms | 6.7 ms | 10.7 ms | 0 | 1.03 | 116 MB | 0.91 cores |
| 2,000 | 1,261 | 0.5 ms | 6.5 ms | 10.4 ms | 0 | 1.61 | 147 MB | 0.60 cores |
| 3,000 | 1,902 | 0.5 ms | 7.4 ms | 12.5 ms | 0 | 2.22 | 157 MB | 0.72 cores |
| 4,000 | 2,553 | 0.5 ms | 10.9 ms | 20.1 ms | 0 | 2.79 | 169 MB | 0.72 cores |
| 5,000 | 3,174 | 0.7 ms | 28.1 ms | 43.5 ms | 0 | 3.40 | 178 MB | 1.21 cores |
| 6,000 | 3,784 | 1.9 ms | 54.4 ms | 76.7 ms | 0 | 4.31 | 186 MB | 0.78 cores |

### p99 by request type

| Request type | 1,000 users | 2,000 users | 3,000 users | 4,000 users | 5,000 users | 6,000 users |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Search (typed) | 9.0 ms | 9.1 ms | 11.6 ms | 19.4 ms | 42.8 ms | 69.8 ms |
| A–Z index for a search | 6.8 ms | 6.9 ms | 9.5 ms | 17.5 ms | 40.9 ms | 67.6 ms |
| List page | 25.8 ms | 24.7 ms | 24.9 ms | 26.6 ms | 46.4 ms | 81.2 ms |
| A–Z index | 9.4 ms | 9.5 ms | 11.3 ms | 18.9 ms | 42.2 ms | 72.1 ms |
| Open a contact | 2.8 ms | 5.1 ms | 7.6 ms | 17.1 ms | 43.8 ms | 79.9 ms |
| Save a contact | 9.2 ms | 8.0 ms | 9.4 ms | 16.2 ms | 41.4 ms | 76.2 ms |
| Tags | 7.1 ms | 8.2 ms | 9.0 ms | 18.6 ms | 43.5 ms | 78.0 ms |
| Stats | 8.5 ms | 9.3 ms | 10.7 ms | 20.0 ms | 45.0 ms | 79.0 ms |

Simulated users open the app, then act every ~3 s on average: scroll or jump letters (35%), type a search (30%), open a contact (25%), switch view (5%), edit and save (5%). Each level warms up for 10 s and is measured for 30 s. Capacity is where p99 latency crosses 100 ms, interpolated between tested levels. A level whose p99 passes 2,000 ms ends that stack's ramp. Single-endpoint tests use 50 clients with no pauses. CPU is CPU-seconds used during the measured window divided by its length (1.0 = one core).

## Single endpoints

| Request | req/s | p50 | p99 | Errors |
| --- | ---: | ---: | ---: | ---: |
| Single contact | 48,475 | 1.0 ms | 1.4 ms | 0 |
| List page 1 (uncached) | 25,523 | 1.9 ms | 2.3 ms | 0 |
| List page at offset 55,000 | 5,200 | 9.6 ms | 11.9 ms | 0 |
| Search `smith` (cached) | 64,301 | 0.7 ms | 1.6 ms | 0 |
| A–Z index (cached) | 136,758 | 0.3 ms | 0.7 ms | 0 |
| Stats (cached) | 154,286 | 0.3 ms | 0.7 ms | 0 |

## Optimization history

Every change tried on this stack, oldest first, from [the optimization log](../../../docs/optimization-log.md).

| When | Change | Effect | Status |
| --- | --- | --- | --- |
| before 2026-09-30 | SQLite on worker threads, not the libmicrohttpd I/O threads | native: resets at 6,000 users → 0 errors, p99 77 ms; single contact ~91,000 → ~48,000 req/s | kept |
| before 2026-09-30 | `MHD_OPTION_LISTEN_BACKLOG_SIZE 1024` | macOS caps the backlog at 128 | no effect |
