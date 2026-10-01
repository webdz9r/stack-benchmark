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
| **Date** | 2026-09-30 22:28:16 |
| **Profile** | standard: the published numbers: 6 user levels (~6 min per stack) |
| **Core budget** | 4 cores per server (the load generator runs on the same machine) |
| **Dataset** | 110,000 contacts |
| **Memory metric** | container working set (cgroup memory.current minus inactive_file) |
| **Repo commit** | 92b273d (with uncommitted changes) |
| **Notes** | Docker mode: Debian 13 images, network load generator, quiet-wait before each stack |

**Other programs:** used up to 2.4 cores (threshold 1.8) — BUSY: treat these numbers as noisy

> **Warning:** other programs were using the CPU while this ran, so these results are noisy.

**Stack:** Axum, rusqlite (bundled SQLite), moka cache  
**Concurrency:** 1 process, 4 Tokio threads, 4 read connections  

## Summary

| Metric | Value |
| --- | ---: |
| Users at p99 ≈ 100 ms | ~5,250 |
| Startup to first response | 16.0 ms |
| Idle memory | 4 MB |
| Peak memory after a load level | 450 MB |
| Processes | 3 |
| Seed checksum (VER-1) | ✅ pass |
| API parity (VER-2) | — (reference stack) |
| Seeding | 100,000 contacts in 2.6 s (37,964/s) |
| Image | debian:trixie-slim runtime, 155MB |
| SQLite in the image | 3.53.2 |

## Simulated users

| Users | req/s | p50 | p95 | p99 | Errors | CPU cores | Memory after | Other programs |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 | 633 | 0.7 ms | 6.6 ms | 10.3 ms | 0 | 0.98 | 132 MB | 0.34 cores |
| 2,000 | 1,260 | 0.5 ms | 6.2 ms | 9.7 ms | 0 | 1.50 | 177 MB | 0.33 cores |
| 3,000 | 1,902 | 0.5 ms | 6.8 ms | 11.2 ms | 0 | 2.02 | 214 MB | 1.34 cores |
| 4,000 | 2,552 | 0.5 ms | 9.9 ms | 20.0 ms | 0 | 2.54 (throttled 3%) | 283 MB | 0.31 cores |
| 5,000 | 3,172 | 0.6 ms | 32.3 ms | 52.3 ms | 0 | 3.09 (throttled 26%) | 413 MB | 1.67 cores |
| 6,000 | 3,733 | 3.4 ms | 191 ms | 243 ms | 0 | 3.69 (throttled 70%) | 450 MB | 2.43 cores |

### p99 by request type

| Request type | 1,000 users | 2,000 users | 3,000 users | 4,000 users | 5,000 users | 6,000 users |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Search (typed) | 8.6 ms | 8.4 ms | 10.1 ms | 18.7 ms | 49.1 ms | 235 ms |
| A–Z index for a search | 7.3 ms | 7.0 ms | 8.6 ms | 17.6 ms | 47.5 ms | 233 ms |
| List page | 24.0 ms | 22.3 ms | 22.5 ms | 24.6 ms | 56.0 ms | 249 ms |
| A–Z index | 10.3 ms | 9.8 ms | 11.2 ms | 18.0 ms | 50.6 ms | 237 ms |
| Open a contact | 3.7 ms | 4.8 ms | 6.9 ms | 17.4 ms | 54.4 ms | 255 ms |
| Save a contact | 14.9 ms | 12.5 ms | 11.1 ms | 10.9 ms | 11.9 ms | 13.5 ms |
| Tags | 8.0 ms | 8.2 ms | 9.5 ms | 17.5 ms | 53.5 ms | 273 ms |
| Stats | 8.3 ms | 8.9 ms | 10.1 ms | 19.3 ms | 55.3 ms | 263 ms |

Simulated users open the app, then act every ~3 s on average: scroll or jump letters (35%), type a search (30%), open a contact (25%), switch view (5%), edit and save (5%). Each level warms up for 10 s and is measured for 30 s. Capacity is where p99 latency crosses 100 ms, interpolated between tested levels. A level whose p99 passes 2,000 ms ends that stack's ramp. Single-endpoint tests use 50 clients with no pauses. CPU is CPU-seconds used during the measured window divided by its length (1.0 = one core).

## Single endpoints

| Request | req/s | p50 | p99 | Errors |
| --- | ---: | ---: | ---: | ---: |
| Single contact | 35,016 | 0.7 ms | 44.5 ms | 0 |
| List page 1 (uncached) | 14,450 | 1.9 ms | 49.8 ms | 0 |
| List page at offset 55,000 | 5,730 | 7.4 ms | 28.7 ms | 0 |
| Search `smith` (cached) | 78,446 | 0.6 ms | 1.5 ms | 0 |
| A–Z index (cached) | 139,121 | 0.3 ms | 0.7 ms | 0 |
| Stats (cached) | 184,112 | 0.3 ms | 0.5 ms | 0 |
