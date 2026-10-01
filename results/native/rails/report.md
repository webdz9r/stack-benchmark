# Rails: benchmark results

[← All backends](../summary.md)

|  |  |
| --- | --- |
| **CPU** | Apple M5 Max |
| **Cores** | 18 physical / 18 logical (6 Super, 12 Performance) |
| **Memory** | 36.0 GB |
| **OS** | macOS 27.0 (kernel 27.0.0, arm64) |
| **Power** | AC power |
| **Date** | 2026-09-30 20:35:35 |
| **Profile** | standard: the published numbers: 6 user levels (~6 min per stack) |
| **Core budget** | 4 cores per server (the load generator runs on the same machine) |
| **Dataset** | 110,000 contacts |
| **Memory metric** | physical footprint (vmmap) |
| **Repo commit** | uncommitted (with uncommitted changes) |
| **Notes** | rails: 1 thread per Puma worker; rerun on a quiet machine |

**Other programs:** used up to 1.7 cores (threshold 1.8)

**Stack:** Rails 8.1 API, Puma, sqlite3 gem (direct SQL)  
**Concurrency:** 4 Puma workers x 1 thread  
**Versions:** ruby 4.0.1 (2026-01-13 revision e04267a14b) +PRISM [arm64-darwin27]; Rails 8.1.4  

## Summary

| Metric | Value |
| --- | ---: |
| Users at p99 ≈ 100 ms | ~3,000 |
| Startup to first response | 794 ms |
| Idle memory | 199 MB |
| Peak memory after a load level | 951 MB |
| Processes | 5 |
| Seed checksum (VER-1) | ✅ pass |
| API parity (VER-2) | ✅ pass (71 identical, 0 mismatched; 42/42 contract checks passed) |
| Seeding | 100,000 contacts in 4.2 s (24,042/s) |

## Simulated users

| Users | req/s | p50 | p95 | p99 | Errors | CPU cores | Memory after | Other programs |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 | 633 | 2.8 ms | 11.7 ms | 23.3 ms | 0 | 1.34 | 641 MB | 0.62 cores |
| 2,000 | 1,257 | 5.2 ms | 25.2 ms | 43.7 ms | 0 | 2.51 | 772 MB | 0.00 cores |
| 3,000 | 1,883 | 18.5 ms | 61.4 ms | 88.1 ms | 0 | 3.63 | 909 MB | 0.68 cores |
| 4,000 | 2,185 | 380 ms | 777 ms | 859 ms | 0 | 4.03 | 937 MB | 0.57 cores |
| 5,000 | 2,065 | 1,380 ms | 2,424 ms | 2,587 ms | 0 | 3.98 | 951 MB | 1.70 cores |

### p99 by request type

| Request type | 1,000 users | 2,000 users | 3,000 users | 4,000 users | 5,000 users |
| --- | ---: | ---: | ---: | ---: | ---: |
| Search (typed) | 18.7 ms | 44.4 ms | 87.6 ms | 863 ms | 2,599 ms |
| A–Z index for a search | 19.6 ms | 41.8 ms | 90.0 ms | 859 ms | 2,584 ms |
| List page | 29.7 ms | 44.0 ms | 90.0 ms | 857 ms | 2,589 ms |
| A–Z index | 23.3 ms | 46.0 ms | 89.7 ms | 860 ms | 2,558 ms |
| Open a contact | 16.5 ms | 42.9 ms | 86.6 ms | 855 ms | 2,591 ms |
| Save a contact | 11.1 ms | 35.2 ms | 78.5 ms | 860 ms | 2,599 ms |
| Tags | 22.5 ms | 42.1 ms | 86.4 ms | 847 ms | 2,532 ms |
| Stats | 21.2 ms | 42.1 ms | 82.6 ms | 853 ms | 2,553 ms |

Simulated users open the app, then act every ~3 s on average: scroll or jump letters (35%), type a search (30%), open a contact (25%), switch view (5%), edit and save (5%). Each level warms up for 10 s and is measured for 30 s. Capacity is where p99 latency crosses 100 ms, interpolated between tested levels. A level whose p99 passes 2,000 ms ends that stack's ramp. Single-endpoint tests use 50 clients with no pauses. CPU is CPU-seconds used during the measured window divided by its length (1.0 = one core).

## Single endpoints

| Request | req/s | p50 | p99 | Errors |
| --- | ---: | ---: | ---: | ---: |
| Single contact | 18,917 | 2.5 ms | 6.3 ms | 0 |
| List page 1 (uncached) | 11,224 | 4.5 ms | 6.4 ms | 0 |
| List page at offset 55,000 | 4,324 | 11.6 ms | 13.4 ms | 0 |
| Search `smith` (cached) | 18,602 | 2.7 ms | 4.1 ms | 0 |
| A–Z index (cached) | 20,629 | 2.5 ms | 3.6 ms | 0 |
| Stats (cached) | 21,864 | 2.3 ms | 3.7 ms | 0 |
