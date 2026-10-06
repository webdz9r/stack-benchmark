# C: benchmark results

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

**Other programs:** used up to 2.8 cores (threshold 1.8) — BUSY: treat these numbers as noisy

> **Warning:** other programs were using the CPU while this ran, so these results are noisy.

**Stack:** libmicrohttpd, SQLite amalgamation (compiled in), yyjson, zlib  
**Concurrency:** 1 process, 4 threads, one read connection each  

## Summary

| Metric | Value |
| --- | ---: |
| Users at p99 ≈ 100 ms | ≥ 6,000 |
| Startup to first response | 17.0 ms |
| Idle memory | 3 MB |
| Peak memory after a load level | 177 MB |
| Processes | 3 |
| Seed checksum (VER-1) | ✅ pass |
| API parity (VER-2) | ✅ pass (71 identical, 0 mismatched; 42/42 contract checks passed) |
| Seeding | 100,000 contacts in 2.7 s (37,732/s) |
| Image | debian:trixie-slim runtime, 185MB |
| SQLite in the image | 3.53.2 |

## Simulated users

| Users | req/s | p50 | p95 | p99 | Errors | CPU cores | Memory after | Other programs |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 | 633 | 0.7 ms | 6.7 ms | 10.5 ms | 0 | 0.99 | 111 MB | 2.78 cores |
| 2,000 | 1,260 | 0.5 ms | 6.2 ms | 9.8 ms | 0 | 1.51 | 148 MB | 2.66 cores |
| 3,000 | 1,902 | 0.5 ms | 6.8 ms | 11.4 ms | 0 | 2.00 | 154 MB | 2.51 cores |
| 4,000 | 2,553 | 0.5 ms | 9.6 ms | 19.3 ms | 0 | 2.51 (throttled 1%) | 164 MB | 2.53 cores |
| 5,000 | 3,175 | 0.6 ms | 23.0 ms | 36.8 ms | 0 | 2.98 (throttled 10%) | 169 MB | 2.42 cores |
| 6,000 | 3,786 | 1.7 ms | 55.0 ms | 72.3 ms | 0 | 3.45 (throttled 33%) | 177 MB | 2.47 cores |

### p99 by request type

| Request type | 1,000 users | 2,000 users | 3,000 users | 4,000 users | 5,000 users | 6,000 users |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Search (typed) | 8.8 ms | 8.5 ms | 10.3 ms | 18.2 ms | 36.5 ms | 69.6 ms |
| A–Z index for a search | 6.8 ms | 6.7 ms | 8.2 ms | 16.6 ms | 34.9 ms | 67.2 ms |
| List page | 24.1 ms | 23.0 ms | 22.8 ms | 24.3 ms | 39.3 ms | 78.5 ms |
| A–Z index | 9.7 ms | 9.1 ms | 10.6 ms | 17.1 ms | 34.6 ms | 71.0 ms |
| Open a contact | 3.3 ms | 4.2 ms | 6.5 ms | 15.9 ms | 36.3 ms | 76.0 ms |
| Save a contact | 11.9 ms | 12.1 ms | 11.4 ms | 15.5 ms | 35.2 ms | 74.8 ms |
| Tags | 8.6 ms | 7.9 ms | 9.1 ms | 17.9 ms | 37.2 ms | 74.7 ms |
| Stats | 10.3 ms | 8.7 ms | 9.9 ms | 18.3 ms | 37.5 ms | 74.6 ms |

Simulated users open the app, then act every ~3 s on average: scroll or jump letters (35%), type a search (30%), open a contact (25%), switch view (5%), edit and save (5%). Each level warms up for 10 s and is measured for 30 s. Capacity is where p99 latency crosses 100 ms, interpolated between tested levels. A level whose p99 passes 2,000 ms ends that stack's ramp. Single-endpoint tests use 50 clients with no pauses. CPU is CPU-seconds used during the measured window divided by its length (1.0 = one core).

## Single endpoints

| Request | req/s | p50 | p99 | Errors |
| --- | ---: | ---: | ---: | ---: |
| Single contact | 88,013 | 0.5 ms | 0.8 ms | 0 |
| List page 1 (uncached) | 26,207 | 1.6 ms | 15.8 ms | 0 |
| List page at offset 55,000 | 5,279 | 9.2 ms | 17.3 ms | 0 |
| Search `smith` (cached) | 65,056 | 0.6 ms | 1.7 ms | 0 |
| A–Z index (cached) | 171,226 | 0.3 ms | 0.7 ms | 0 |
| Stats (cached) | 263,389 | 0.2 ms | 0.5 ms | 0 |

## Optimization history

Every change tried on this stack, oldest first, from [the optimization log](../../docs/optimization-log.md).

| When | Change | Effect | Status |
| --- | --- | --- | --- |
| before 2026-09-30 | SQLite on worker threads, not the libmicrohttpd I/O threads | native: resets at 6,000 users → 0 errors, p99 77 ms; single contact ~91,000 → ~48,000 req/s | kept |
| before 2026-09-30 | `MHD_OPTION_LISTEN_BACKLOG_SIZE 1024` | macOS caps the backlog at 128 | no effect |
