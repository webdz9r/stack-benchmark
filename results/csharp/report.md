# C#: benchmark results

[← All backends](../summary.md)

|  |  |
| --- | --- |
| **CPU** | Apple M5 Max |
| **Cores** | 18 physical / 18 logical (6 Super, 12 Performance) |
| **Memory** | 36.0 GB |
| **OS** | macOS 27.0 (kernel 27.0.0, arm64) |
| **Power** | AC power |
| **Date** | 2026-09-30 13:23:58 |
| **Profile** | standard: the published numbers: 6 user levels (~6 min per stack) |
| **Core budget** | 4 cores per server (the load generator runs on the same machine) |
| **Dataset** | 110,000 contacts |
| **Memory metric** | physical footprint (vmmap) |
| **Repo commit** | uncommitted (with uncommitted changes) |
| **Notes** | csharp: SQLITE_CONFIG_MEMSTATUS=0 at runtime, cache byte accounting fix, no build servers |

**Other programs:** used up to 2.6 cores (threshold 1.8) — BUSY: treat these numbers as noisy

> **Warning:** other programs were using the CPU while this ran, so these results are noisy.

**Stack:** ASP.NET Core minimal APIs, Microsoft.Data.Sqlite, source-generated JSON  
**Concurrency:** 1 process, DOTNET_PROCESSOR_COUNT=4, 4 read connections  
**Versions:** 10.0.401  

## Summary

| Metric | Value |
| --- | ---: |
| Users at p99 ≈ 100 ms | ≥ 6,000 |
| Startup to first response | 181 ms |
| Idle memory | 63 MB |
| Peak memory after a load level | 836 MB |
| Processes | 1 |
| Seed checksum (VER-1) | ✅ pass |
| API parity (VER-2) | ✅ pass (71 identical, 0 mismatched; 42/42 contract checks passed) |
| Seeding | 100,000 contacts in 3.2 s (30,978/s) |

## Simulated users

| Users | req/s | p50 | p95 | p99 | Errors | CPU cores | Memory after | Other programs |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 | 634 | 0.3 ms | 6.1 ms | 11.9 ms | 0 | 0.85 | 202 MB | 1.50 cores |
| 2,000 | 1,261 | 0.3 ms | 5.2 ms | 10.4 ms | 0 | 1.29 | 316 MB | 1.18 cores |
| 3,000 | 1,903 | 0.3 ms | 4.9 ms | 9.8 ms | 0 | 1.87 | 467 MB | 1.42 cores |
| 4,000 | 2,555 | 0.3 ms | 5.1 ms | 10.2 ms | 0 | 2.30 | 572 MB | 1.33 cores |
| 5,000 | 3,179 | 0.3 ms | 6.6 ms | 11.7 ms | 0 | 3.00 | 658 MB | 1.53 cores |
| 6,000 | 3,804 | 0.3 ms | 8.0 ms | 14.7 ms | 0 | 3.49 | 836 MB | 1.23 cores |

### p99 by request type

| Request type | 1,000 users | 2,000 users | 3,000 users | 4,000 users | 5,000 users | 6,000 users |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Search (typed) | 9.9 ms | 8.4 ms | 7.5 ms | 7.5 ms | 9.9 ms | 11.0 ms |
| A–Z index for a search | 6.1 ms | 5.3 ms | 4.6 ms | 4.8 ms | 6.9 ms | 7.8 ms |
| List page | 28.4 ms | 22.8 ms | 20.0 ms | 18.3 ms | 22.4 ms | 24.0 ms |
| A–Z index | 11.2 ms | 10.3 ms | 10.3 ms | 10.8 ms | 11.8 ms | 15.5 ms |
| Open a contact | 3.2 ms | 3.8 ms | 4.5 ms | 6.3 ms | 8.6 ms | 13.5 ms |
| Save a contact | 11.1 ms | 9.8 ms | 8.9 ms | 9.1 ms | 9.0 ms | 8.8 ms |
| Tags | 8.3 ms | 7.8 ms | 7.2 ms | 9.7 ms | 10.7 ms | 15.3 ms |
| Stats | 11.4 ms | 9.9 ms | 9.7 ms | 10.9 ms | 12.9 ms | 17.6 ms |

Simulated users open the app, then act every ~3 s on average: scroll or jump letters (35%), type a search (30%), open a contact (25%), switch view (5%), edit and save (5%). Each level warms up for 10 s and is measured for 30 s. Capacity is where p99 latency crosses 100 ms, interpolated between tested levels. A level whose p99 passes 2,000 ms ends that stack's ramp. Single-endpoint tests use 50 clients with no pauses. CPU is CPU-seconds used during the measured window divided by its length (1.0 = one core).

## Single endpoints

| Request | req/s | p50 | p99 | Errors |
| --- | ---: | ---: | ---: | ---: |
| Single contact | 79,135 | 0.6 ms | 1.0 ms | 0 |
| List page 1 (uncached) | 21,531 | 2.2 ms | 3.4 ms | 0 |
| List page at offset 55,000 | 4,926 | 9.9 ms | 17.3 ms | 0 |
| Search `smith` (cached) | 67,825 | 0.7 ms | 1.2 ms | 0 |
| A–Z index (cached) | 121,995 | 0.4 ms | 0.7 ms | 0 |
| Stats (cached) | 131,628 | 0.4 ms | 0.7 ms | 0 |
