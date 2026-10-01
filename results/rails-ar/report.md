# Rails + ActiveRecord: benchmark results

[← All backends](../summary.md)

|  |  |
| --- | --- |
| **CPU** | Apple M5 Max |
| **Cores** | 18 physical / 18 logical (6 Super, 12 Performance) |
| **Memory** | 36.0 GB |
| **OS** | macOS 27.0 (kernel 27.0.0, arm64) |
| **Power** | AC power |
| **Date** | 2026-09-30 20:26:08 |
| **Profile** | standard: the published numbers: 6 user levels (~6 min per stack) |
| **Core budget** | 4 cores per server (the load generator runs on the same machine) |
| **Dataset** | 110,000 contacts |
| **Memory metric** | physical footprint (vmmap) |
| **Repo commit** | uncommitted (with uncommitted changes) |
| **Notes** | rails-ar: 1 thread per Puma worker; rerun on a quiet machine |

**Other programs:** used up to 1.7 cores (threshold 1.8)

**Stack:** Same Rails app on ActiveRecord models  
**Concurrency:** 4 Puma workers x 1 thread  
**Versions:** ruby 4.0.1 (2026-01-13 revision e04267a14b) +PRISM [arm64-darwin27]; Rails 8.1.4  

## Summary

| Metric | Value |
| --- | ---: |
| Users at p99 ≈ 100 ms | ~1,950 |
| Startup to first response | 802 ms |
| Idle memory | 199 MB |
| Peak memory after a load level | 960 MB |
| Processes | 5 |
| Seed checksum (VER-1) | ✅ pass |
| API parity (VER-2) | ✅ pass (71 identical, 0 mismatched; 42/42 contract checks passed) |
| Seeding | 100,000 contacts in 42.1 s (2,376/s) |

## Simulated users

| Users | req/s | p50 | p95 | p99 | Errors | CPU cores | Memory after | Other programs |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 | 631 | 5.7 ms | 24.3 ms | 45.6 ms | 0 | 2.06 | 680 MB | 1.74 cores |
| 2,000 | 1,244 | 27.5 ms | 80.0 ms | 103 ms | 0 | 3.69 | 822 MB | 0.49 cores |
| 3,000 | 1,409 | 866 ms | 1,105 ms | 1,216 ms | 0 | 4.02 | 942 MB | 0.45 cores |
| 4,000 | 1,424 | 1,987 ms | 2,165 ms | 2,257 ms | 0 | 4.02 | 960 MB | 0.62 cores |

### p99 by request type

| Request type | 1,000 users | 2,000 users | 3,000 users | 4,000 users |
| --- | ---: | ---: | ---: | ---: |
| Search (typed) | 46.2 ms | 103 ms | 1,218 ms | 2,260 ms |
| A–Z index for a search | 42.2 ms | 104 ms | 1,211 ms | 2,251 ms |
| List page | 51.6 ms | 104 ms | 1,216 ms | 2,262 ms |
| A–Z index | 43.8 ms | 104 ms | 1,224 ms | 2,258 ms |
| Open a contact | 41.4 ms | 102 ms | 1,215 ms | 2,245 ms |
| Save a contact | 33.0 ms | 93.9 ms | 1,212 ms | 2,230 ms |
| Tags | 34.7 ms | 98.5 ms | 1,210 ms | 2,257 ms |
| Stats | 42.3 ms | 104 ms | 1,210 ms | 2,227 ms |

Simulated users open the app, then act every ~3 s on average: scroll or jump letters (35%), type a search (30%), open a contact (25%), switch view (5%), edit and save (5%). Each level warms up for 10 s and is measured for 30 s. Capacity is where p99 latency crosses 100 ms, interpolated between tested levels. A level whose p99 passes 2,000 ms ends that stack's ramp. Single-endpoint tests use 50 clients with no pauses. CPU is CPU-seconds used during the measured window divided by its length (1.0 = one core).

## Single endpoints

| Request | req/s | p50 | p99 | Errors |
| --- | ---: | ---: | ---: | ---: |
| Single contact | 5,719 | 6.8 ms | 22.7 ms | 0 |
| List page 1 (uncached) | 1,633 | 27.6 ms | 44.4 ms | 0 |
| List page at offset 55,000 | 1,432 | 34.8 ms | 39.9 ms | 0 |
| Search `smith` (cached) | 18,363 | 2.7 ms | 4.5 ms | 0 |
| A–Z index (cached) | 20,287 | 2.4 ms | 3.9 ms | 0 |
| Stats (cached) | 21,497 | 2.3 ms | 4.0 ms | 0 |
