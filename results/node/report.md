# Node: benchmark results

[← All backends](../summary.md)

|  |  |
| --- | --- |
| **CPU** | Apple M5 Max |
| **Cores** | 18 physical / 18 logical (6 Super, 12 Performance) |
| **Memory** | 36.0 GB |
| **OS** | macOS 27.0 (kernel 27.0.0, arm64) |
| **Power** | AC power |
| **Date** | 2026-09-30 15:07:18 |
| **Profile** | standard: the published numbers: 6 user levels (~6 min per stack) |
| **Core budget** | 4 cores per server (the load generator runs on the same machine) |
| **Dataset** | 110,000 contacts |
| **Memory metric** | physical footprint (vmmap) |
| **Repo commit** | uncommitted (with uncommitted changes) |
| **Notes** | node: one process, better-sqlite3 on 4 reader threads + writer thread, shared cache |

**Other programs:** used up to 1.2 cores (threshold 1.8)

**Stack:** Fastify, built-in node:sqlite on worker threads  
**Concurrency:** 1 process: event loop + 4 reader threads + 1 writer thread  
**Versions:** v26.7.0  

## Summary

| Metric | Value |
| --- | ---: |
| Users at p99 ≈ 100 ms | ~5,050 |
| Startup to first response | 175 ms |
| Idle memory | 102 MB |
| Peak memory after a load level | 1.00 GB |
| Processes | 1 |
| Seed checksum (VER-1) | ✅ pass |
| API parity (VER-2) | ✅ pass (71 identical, 0 mismatched; 42/42 contract checks passed) |
| Seeding | 100,000 contacts in 3.1 s (32,283/s) |

## Simulated users

| Users | req/s | p50 | p95 | p99 | Errors | CPU cores | Memory after | Other programs |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 | 633 | 0.8 ms | 7.2 ms | 11.0 ms | 0 | 1.11 | 633 MB | 0.92 cores |
| 2,000 | 1,261 | 0.6 ms | 6.8 ms | 10.9 ms | 0 | 1.74 | 798 MB | 0.61 cores |
| 3,000 | 1,902 | 0.5 ms | 8.1 ms | 14.1 ms | 0 | 2.40 | 896 MB | 0.89 cores |
| 4,000 | 2,552 | 0.6 ms | 15.8 ms | 31.7 ms | 0 | 3.06 | 969 MB | 0.69 cores |
| 5,000 | 3,163 | 1.4 ms | 55.9 ms | 80.2 ms | 0 | 3.84 | 1.00 GB | 1.15 cores |
| 6,000 | 3,688 | 8.0 ms | 303 ms | 376 ms | 0 | 4.32 | 945 MB | 0.68 cores |

### p99 by request type

| Request type | 1,000 users | 2,000 users | 3,000 users | 4,000 users | 5,000 users | 6,000 users |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Search (typed) | 9.3 ms | 9.5 ms | 13.2 ms | 31.8 ms | 69.6 ms | 358 ms |
| A–Z index for a search | 7.0 ms | 6.9 ms | 10.8 ms | 29.7 ms | 66.7 ms | 356 ms |
| List page | 26.4 ms | 24.9 ms | 25.1 ms | 35.4 ms | 87.1 ms | 385 ms |
| A–Z index | 9.8 ms | 10.0 ms | 12.5 ms | 27.9 ms | 78.5 ms | 368 ms |
| Open a contact | 3.5 ms | 5.1 ms | 9.4 ms | 30.9 ms | 85.6 ms | 387 ms |
| Save a contact | 8.4 ms | 8.8 ms | 8.8 ms | 9.3 ms | 10.1 ms | 6.7 ms |
| Tags | 7.3 ms | 7.8 ms | 11.9 ms | 31.7 ms | 86.0 ms | 383 ms |
| Stats | 10.1 ms | 9.8 ms | 13.8 ms | 34.2 ms | 88.6 ms | 385 ms |

Simulated users open the app, then act every ~3 s on average: scroll or jump letters (35%), type a search (30%), open a contact (25%), switch view (5%), edit and save (5%). Each level warms up for 10 s and is measured for 30 s. Capacity is where p99 latency crosses 100 ms, interpolated between tested levels. A level whose p99 passes 2,000 ms ends that stack's ramp. Single-endpoint tests use 50 clients with no pauses. CPU is CPU-seconds used during the measured window divided by its length (1.0 = one core).

## Single endpoints

| Request | req/s | p50 | p99 | Errors |
| --- | ---: | ---: | ---: | ---: |
| Single contact | 38,788 | 1.2 ms | 2.6 ms | 0 |
| List page 1 (uncached) | 16,639 | 2.9 ms | 4.3 ms | 0 |
| List page at offset 55,000 | 5,752 | 8.6 ms | 10.0 ms | 0 |
| Search `smith` (cached) | 20,635 | 2.3 ms | 3.7 ms | 0 |
| A–Z index (cached) | 44,729 | 1.0 ms | 2.1 ms | 0 |
| Stats (cached) | 57,754 | 0.7 ms | 2.1 ms | 0 |
