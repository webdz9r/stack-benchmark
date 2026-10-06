# Go: benchmark results

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

**Other programs:** used up to 2.9 cores (threshold 1.8) — BUSY: treat these numbers as noisy

> **Warning:** other programs were using the CPU while this ran, so these results are noisy.

**Stack:** net/http, mattn/go-sqlite3, klauspost gzip  
**Concurrency:** 1 process, GOMAXPROCS=4, 4 read connections  

## Summary

| Metric | Value |
| --- | ---: |
| Users at p99 ≈ 100 ms | ~5,300 |
| Startup to first response | 16.0 ms |
| Idle memory | 15 MB |
| Peak memory after a load level | 273 MB |
| Processes | 3 |
| Seed checksum (VER-1) | ✅ pass |
| API parity (VER-2) | ✅ pass (71 identical, 0 mismatched; 42/42 contract checks passed) |
| Seeding | 100,000 contacts in 4.7 s (21,277/s) |
| Image | debian:trixie-slim runtime, 180MB |
| SQLite in the image | 3.53.4 |

## Simulated users

| Users | req/s | p50 | p95 | p99 | Errors | CPU cores | Memory after | Other programs |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 | 633 | 0.8 ms | 6.9 ms | 11.1 ms | 0 | 1.01 | 165 MB | 2.86 cores |
| 2,000 | 1,260 | 0.6 ms | 6.3 ms | 10.3 ms | 0 | 1.48 | 233 MB | 0.00 cores |
| 3,000 | 1,902 | 0.6 ms | 6.9 ms | 12.8 ms | 0 | 1.98 | 244 MB | 1.55 cores |
| 4,000 | 2,552 | 0.7 ms | 10.1 ms | 25.5 ms | 0 | 2.45 (throttled 1%) | 256 MB | 0.21 cores |
| 5,000 | 3,172 | 1.1 ms | 28.5 ms | 64.8 ms | 0 | 2.94 (throttled 14%) | 266 MB | 0.31 cores |
| 6,000 | 3,766 | 1.9 ms | 101 ms | 191 ms | 0 | 3.46 (throttled 42%) | 273 MB | 0.24 cores |

### p99 by request type

| Request type | 1,000 users | 2,000 users | 3,000 users | 4,000 users | 5,000 users | 6,000 users |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Search (typed) | 9.2 ms | 8.9 ms | 11.6 ms | 23.2 ms | 49.4 ms | 130 ms |
| A–Z index for a search | 7.1 ms | 6.6 ms | 7.8 ms | 13.6 ms | 29.9 ms | 78.3 ms |
| List page | 24.7 ms | 23.4 ms | 23.9 ms | 26.7 ms | 54.1 ms | 150 ms |
| A–Z index | 10.4 ms | 10.3 ms | 10.3 ms | 15.9 ms | 29.6 ms | 90.6 ms |
| Open a contact | 4.9 ms | 7.3 ms | 12.4 ms | 43.5 ms | 105 ms | 285 ms |
| Save a contact | 13.8 ms | 10.9 ms | 10.9 ms | 11.0 ms | 11.5 ms | 12.2 ms |
| Tags | 7.0 ms | 7.1 ms | 7.6 ms | 13.8 ms | 31.9 ms | 91.8 ms |
| Stats | 8.2 ms | 7.6 ms | 9.6 ms | 13.4 ms | 36.1 ms | 97.9 ms |

Simulated users open the app, then act every ~3 s on average: scroll or jump letters (35%), type a search (30%), open a contact (25%), switch view (5%), edit and save (5%). Each level warms up for 10 s and is measured for 30 s. Capacity is where p99 latency crosses 100 ms, interpolated between tested levels. A level whose p99 passes 2,000 ms ends that stack's ramp. Single-endpoint tests use 50 clients with no pauses. CPU is CPU-seconds used during the measured window divided by its length (1.0 = one core).

## Single endpoints

| Request | req/s | p50 | p99 | Errors |
| --- | ---: | ---: | ---: | ---: |
| Single contact | 58,360 | 0.7 ms | 2.9 ms | 0 |
| List page 1 (uncached) | 19,324 | 2.4 ms | 6.8 ms | 0 |
| List page at offset 55,000 | 5,225 | 8.8 ms | 26.6 ms | 0 |
| Search `smith` (cached) | 78,616 | 0.5 ms | 1.8 ms | 0 |
| A–Z index (cached) | 156,978 | 0.3 ms | 1.1 ms | 0 |
| Stats (cached) | 218,021 | 0.2 ms | 0.9 ms | 0 |

## Optimization history

Every change tried on this stack, oldest first, from [the optimization log](../../docs/optimization-log.md).

| When | Change | Effect | Status |
| --- | --- | --- | --- |
| before 2026-09-30 | keep `-O2` in `CGO_CFLAGS` (setting it had dropped the default) | native: ~1,500 → ~5,500 users | kept |
| open | p99 at 6,000 users (~133 ms) |  | open |
