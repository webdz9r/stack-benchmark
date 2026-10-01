# Python: benchmark results

[← All backends](../summary.md)

|  |  |
| --- | --- |
| **CPU** | Apple M5 Max |
| **Cores** | 18 physical / 18 logical (6 Super, 12 Performance) |
| **Memory** | 36.0 GB |
| **OS** | macOS 27.0 (kernel 27.0.0, arm64) |
| **Power** | AC power |
| **Date** | 2026-09-30 15:35:46 |
| **Profile** | standard: the published numbers: 6 user levels (~6 min per stack) |
| **Core budget** | 4 cores per server (the load generator runs on the same machine) |
| **Dataset** | 110,000 contacts |
| **Memory metric** | physical footprint (vmmap) |
| **Repo commit** | uncommitted (with uncommitted changes) |
| **Notes** | python: SQLITE_CONFIG_MEMSTATUS=0 via ctypes before import sqlite3 |

**Other programs:** used up to 1.3 cores (threshold 1.8)

**Stack:** FastAPI, uvicorn (uvloop, httptools), sqlite3, orjson  
**Concurrency:** 4 workers x 4 threads  
**Versions:** Python 3.14.6  

## Summary

| Metric | Value |
| --- | ---: |
| Users at p99 ≈ 100 ms | ~3,050 |
| Startup to first response | 285 ms |
| Idle memory | 211 MB |
| Peak memory after a load level | 905 MB |
| Processes | 6 |
| Seed checksum (VER-1) | ✅ pass |
| API parity (VER-2) | ✅ pass (71 identical, 0 mismatched; 42/42 contract checks passed) |
| Seeding | 100,000 contacts in 4.3 s (23,185/s) |

## Simulated users

| Users | req/s | p50 | p95 | p99 | Errors | CPU cores | Memory after | Other programs |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 | 633 | 1.6 ms | 7.2 ms | 11.6 ms | 0 | 1.42 | 371 MB | 0.81 cores |
| 2,000 | 1,260 | 1.6 ms | 9.1 ms | 19.8 ms | 0 | 3.08 | 584 MB | 1.09 cores |
| 3,000 | 1,899 | 2.0 ms | 13.9 ms | 50.9 ms | 0 | 4.18 | 717 MB | 1.01 cores |
| 4,000 | 2,342 | 73.2 ms | 663 ms | 752 ms | 0 | 10.84 | 787 MB | 1.33 cores |
| 5,000 | 2,249 | 920 ms | 1,427 ms | 1,571 ms | 0 | 14.85 | 836 MB | 0.54 cores |
| 6,000 | 1,964 | 2,251 ms | 3,087 ms | 3,341 ms | 0 | 14.72 | 905 MB | 0.61 cores |

### p99 by request type

| Request type | 1,000 users | 2,000 users | 3,000 users | 4,000 users | 5,000 users | 6,000 users |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Search (typed) | 9.4 ms | 20.7 ms | 55.4 ms | 752 ms | 1,577 ms | 3,345 ms |
| A–Z index for a search | 7.6 ms | 15.7 ms | 49.2 ms | 750 ms | 1,567 ms | 3,343 ms |
| List page | 28.6 ms | 30.5 ms | 52.7 ms | 753 ms | 1,569 ms | 3,337 ms |
| A–Z index | 9.8 ms | 18.2 ms | 47.1 ms | 748 ms | 1,570 ms | 3,348 ms |
| Open a contact | 1.3 ms | 5.3 ms | 42.0 ms | 753 ms | 1,563 ms | 3,332 ms |
| Save a contact | 10.1 ms | 10.3 ms | 32.2 ms | 739 ms | 1,557 ms | 3,326 ms |
| Tags | 4.1 ms | 6.8 ms | 41.0 ms | 744 ms | 1,584 ms | 3,260 ms |
| Stats | 8.5 ms | 24.0 ms | 56.7 ms | 759 ms | 1,567 ms | 3,343 ms |

Simulated users open the app, then act every ~3 s on average: scroll or jump letters (35%), type a search (30%), open a contact (25%), switch view (5%), edit and save (5%). Each level warms up for 10 s and is measured for 30 s. Capacity is where p99 latency crosses 100 ms, interpolated between tested levels. A level whose p99 passes 2,000 ms ends that stack's ramp. Single-endpoint tests use 50 clients with no pauses. CPU is CPU-seconds used during the measured window divided by its length (1.0 = one core).

## Single endpoints

| Request | req/s | p50 | p99 | Errors |
| --- | ---: | ---: | ---: | ---: |
| Single contact | 13,484 | 3.7 ms | 5.6 ms | 0 |
| List page 1 (uncached) | 2,758 | 18.1 ms | 23.3 ms | 0 |
| List page at offset 55,000 | 3,476 | 14.1 ms | 19.7 ms | 0 |
| Search `smith` (cached) | 19,407 | 2.1 ms | 5.0 ms | 0 |
| A–Z index (cached) | 26,281 | 1.9 ms | 3.1 ms | 0 |
| Stats (cached) | 33,646 | 1.5 ms | 2.1 ms | 0 |
