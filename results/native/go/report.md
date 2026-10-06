# Go: benchmark results

[← All backends](../summary.md)

|  |  |
| --- | --- |
| **CPU** | Apple M5 Max |
| **Cores** | 18 physical / 18 logical (6 Super, 12 Performance) |
| **Memory** | 36.0 GB |
| **OS** | macOS 27.0 (kernel 27.0.0, arm64) |
| **Power** | AC power |
| **Date** | 2026-09-30 11:09:16 |
| **Profile** | standard: the published numbers: 6 user levels (~6 min per stack) |
| **Core budget** | 4 cores per server (the load generator runs on the same machine) |
| **Dataset** | 110,000 contacts |
| **Memory metric** | physical footprint (vmmap) |
| **Repo commit** | uncommitted (with uncommitted changes) |
| **Notes** | Go rerun: SQLite compiled with -O2 again |

**Other programs:** used up to 1.4 cores (threshold 1.8)

**Stack:** net/http, mattn/go-sqlite3, klauspost gzip  
**Concurrency:** 1 process, GOMAXPROCS=4, 4 read connections  
**Versions:** go version go1.27.1 darwin/arm64  

## Summary

| Metric | Value |
| --- | ---: |
| Users at p99 ≈ 100 ms | ~5,500 |
| Startup to first response | 235 ms |
| Idle memory | 4 MB |
| Peak memory after a load level | 259 MB |
| Processes | 1 |
| Seed checksum (VER-1) | ✅ pass |
| API parity (VER-2) | ✅ pass (71 identical, 0 mismatched; 42/42 contract checks passed) |
| Seeding | 100,000 contacts in 4.6 s (21,625/s) |

## Simulated users

| Users | req/s | p50 | p95 | p99 | Errors | CPU cores | Memory after | Other programs |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 | 633 | 0.7 ms | 6.9 ms | 11.5 ms | 0 | 1.09 | 154 MB | 0.65 cores |
| 2,000 | 1,261 | 0.5 ms | 6.6 ms | 11.0 ms | 0 | 1.66 | 215 MB | 0.69 cores |
| 3,000 | 1,902 | 0.6 ms | 7.9 ms | 14.5 ms | 0 | 2.22 | 229 MB | 0.65 cores |
| 4,000 | 2,552 | 0.8 ms | 12.8 ms | 29.3 ms | 0 | 2.74 | 240 MB | 0.62 cores |
| 5,000 | 3,170 | 1.9 ms | 35.4 ms | 68.7 ms | 0 | 3.23 | 245 MB | 0.62 cores |
| 6,000 | 3,776 | 5.1 ms | 71.5 ms | 133 ms | 0 | 3.69 | 259 MB | 0.93 cores |

### p99 by request type

| Request type | 1,000 users | 2,000 users | 3,000 users | 4,000 users | 5,000 users | 6,000 users |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Search (typed) | 9.5 ms | 9.3 ms | 12.4 ms | 27.2 ms | 61.5 ms | 105 ms |
| A–Z index for a search | 7.5 ms | 7.4 ms | 11.3 ms | 27.8 ms | 57.2 ms | 91.5 ms |
| List page | 26.6 ms | 25.9 ms | 25.8 ms | 32.0 ms | 69.7 ms | 125 ms |
| A–Z index | 10.3 ms | 10.8 ms | 13.7 ms | 25.9 ms | 55.0 ms | 84.6 ms |
| Open a contact | 4.1 ms | 6.3 ms | 11.8 ms | 31.1 ms | 95.6 ms | 189 ms |
| Save a contact | 10.3 ms | 9.2 ms | 9.1 ms | 18.0 ms | 45.8 ms | 54.5 ms |
| Tags | 7.3 ms | 9.1 ms | 11.0 ms | 20.2 ms | 46.5 ms | 71.1 ms |
| Stats | 8.0 ms | 9.2 ms | 11.5 ms | 25.2 ms | 55.2 ms | 79.5 ms |

Simulated users open the app, then act every ~3 s on average: scroll or jump letters (35%), type a search (30%), open a contact (25%), switch view (5%), edit and save (5%). Each level warms up for 10 s and is measured for 30 s. Capacity is where p99 latency crosses 100 ms, interpolated between tested levels. A level whose p99 passes 2,000 ms ends that stack's ramp. Single-endpoint tests use 50 clients with no pauses. CPU is CPU-seconds used during the measured window divided by its length (1.0 = one core).

## Single endpoints

| Request | req/s | p50 | p99 | Errors |
| --- | ---: | ---: | ---: | ---: |
| Single contact | 55,375 | 0.8 ms | 1.9 ms | 0 |
| List page 1 (uncached) | 20,110 | 2.3 ms | 6.4 ms | 0 |
| List page at offset 55,000 | 5,194 | 8.6 ms | 26.7 ms | 0 |
| Search `smith` (cached) | 89,986 | 0.5 ms | 1.6 ms | 0 |
| A–Z index (cached) | 150,869 | 0.3 ms | 0.9 ms | 0 |
| Stats (cached) | 165,132 | 0.3 ms | 0.7 ms | 0 |

## Optimization history

Every change tried on this stack, oldest first, from [the optimization log](../../../docs/optimization-log.md).

| When | Change | Effect | Status |
| --- | --- | --- | --- |
| before 2026-09-30 | keep `-O2` in `CGO_CFLAGS` (setting it had dropped the default) | native: ~1,500 → ~5,500 users | kept |
| open | p99 at 6,000 users (~133 ms) |  | open |
