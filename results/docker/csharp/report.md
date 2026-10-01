# C#: benchmark results

[← All backends](../summary.md)

|  |  |
| --- | --- |
| **CPU** | Apple M5 Max |
| **Cores** | 18 physical / 18 logical (6 Super, 12 Performance) |
| **Memory** | 36.0 GB |
| **OS** | macOS 27.0 (kernel 27.0.0, arm64) |
| **Power** | AC power |
| **Mode** | Docker 29.2.1 (Docker Desktop, 18 CPUs / 7.7 GB for containers); each server in a container limited to 4 CPUs / 4g, load generator on the Docker network |
| **Date** | 2026-09-30 22:28:16 |
| **Profile** | standard: the published numbers: 6 user levels (~6 min per stack) |
| **Core budget** | 4 cores per server (the load generator runs on the same machine) |
| **Dataset** | 110,000 contacts |
| **Memory metric** | container working set (cgroup memory.current minus inactive_file) |
| **Repo commit** | 92b273d (with uncommitted changes) |
| **Notes** | Docker mode: Debian 13 images, network load generator, quiet-wait before each stack |

**Other programs:** used up to 3.2 cores (threshold 1.8) — BUSY: treat these numbers as noisy

> **Warning:** other programs were using the CPU while this ran, so these results are noisy.

**Stack:** ASP.NET Core minimal APIs, Microsoft.Data.Sqlite, source-generated JSON  
**Concurrency:** 1 process, DOTNET_PROCESSOR_COUNT=4, 4 read connections  

## Summary

| Metric | Value |
| --- | ---: |
| Users at p99 ≈ 100 ms | ≥ 6,000 |
| Startup to first response | 174 ms |
| Idle memory | 41 MB |
| Peak memory after a load level | 379 MB |
| Processes | 3 |
| Seed checksum (VER-1) | ✅ pass |
| API parity (VER-2) | ✅ pass (71 identical, 0 mismatched; 42/42 contract checks passed) |
| Seeding | 100,000 contacts in 3.5 s (28,383/s) |
| Image | debian:trixie-slim runtime, 433MB |
| SQLite in the image | 3.53.3 |

## Simulated users

| Users | req/s | p50 | p95 | p99 | Errors | CPU cores | Memory after | Other programs |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 | 633 | 0.4 ms | 6.6 ms | 12.4 ms | 0 | 0.77 | 161 MB | 2.87 cores |
| 2,000 | 1,261 | 0.3 ms | 5.4 ms | 10.1 ms | 0 | 1.18 | 227 MB | 2.36 cores |
| 3,000 | 1,902 | 0.4 ms | 5.2 ms | 9.8 ms | 0 | 1.57 | 261 MB | 2.27 cores |
| 4,000 | 2,554 | 0.4 ms | 5.2 ms | 9.6 ms | 0 | 1.91 | 301 MB | 2.45 cores |
| 5,000 | 3,178 | 0.5 ms | 8.0 ms | 13.3 ms | 0 | 2.71 (throttled 1%) | 347 MB | 2.17 cores |
| 6,000 | 3,802 | 0.5 ms | 10.9 ms | 20.4 ms | 0 | 3.17 (throttled 12%) | 379 MB | 3.20 cores |

### p99 by request type

| Request type | 1,000 users | 2,000 users | 3,000 users | 4,000 users | 5,000 users | 6,000 users |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Search (typed) | 9.8 ms | 8.1 ms | 7.4 ms | 7.3 ms | 10.9 ms | 13.3 ms |
| A–Z index for a search | 6.2 ms | 4.8 ms | 4.4 ms | 4.4 ms | 8.0 ms | 10.3 ms |
| List page | 29.7 ms | 21.7 ms | 20.2 ms | 17.0 ms | 23.6 ms | 28.9 ms |
| A–Z index | 12.7 ms | 10.1 ms | 10.2 ms | 10.1 ms | 14.3 ms | 22.3 ms |
| Open a contact | 3.1 ms | 3.9 ms | 4.7 ms | 5.4 ms | 10.5 ms | 20.9 ms |
| Save a contact | 15.6 ms | 11.4 ms | 11.4 ms | 11.2 ms | 11.5 ms | 11.4 ms |
| Tags | 10.5 ms | 8.6 ms | 9.2 ms | 9.0 ms | 13.4 ms | 23.8 ms |
| Stats | 10.7 ms | 9.3 ms | 10.4 ms | 10.8 ms | 16.0 ms | 27.2 ms |

Simulated users open the app, then act every ~3 s on average: scroll or jump letters (35%), type a search (30%), open a contact (25%), switch view (5%), edit and save (5%). Each level warms up for 10 s and is measured for 30 s. Capacity is where p99 latency crosses 100 ms, interpolated between tested levels. A level whose p99 passes 2,000 ms ends that stack's ramp. Single-endpoint tests use 50 clients with no pauses. CPU is CPU-seconds used during the measured window divided by its length (1.0 = one core).

## Single endpoints

| Request | req/s | p50 | p99 | Errors |
| --- | ---: | ---: | ---: | ---: |
| Single contact | 62,127 | 0.6 ms | 1.3 ms | 0 |
| List page 1 (uncached) | 17,172 | 2.3 ms | 30.3 ms | 0 |
| List page at offset 55,000 | 3,835 | 11.8 ms | 34.1 ms | 0 |
| Search `smith` (cached) | 64,145 | 0.7 ms | 1.9 ms | 0 |
| A–Z index (cached) | 106,113 | 0.4 ms | 1.1 ms | 0 |
| Stats (cached) | 146,383 | 0.3 ms | 0.8 ms | 0 |
