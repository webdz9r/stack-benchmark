# Node: benchmark results

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

**Other programs:** used up to 3.8 cores (threshold 1.8) — BUSY: treat these numbers as noisy

> **Warning:** other programs were using the CPU while this ran, so these results are noisy.

**Stack:** Fastify, better-sqlite3 on worker threads  
**Concurrency:** 1 process: event loop + 4 reader threads + 1 writer thread  
**Versions:** v26.10.0  

## Summary

| Metric | Value |
| --- | ---: |
| Users at p99 ≈ 100 ms | ~4,850 |
| Startup to first response | 155 ms |
| Idle memory | 91 MB |
| Peak memory after a load level | 1.04 GB |
| Processes | 3 |
| Seed checksum (VER-1) | ✅ pass |
| API parity (VER-2) | ✅ pass (71 identical, 0 mismatched; 42/42 contract checks passed) |
| Seeding | 100,000 contacts in 3.0 s (33,426/s) |
| Image | node:26-trixie-slim runtime, 444MB |
| SQLite in the image | 3.53.4 |

## Simulated users

| Users | req/s | p50 | p95 | p99 | Errors | CPU cores | Memory after | Other programs |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 | 633 | 0.8 ms | 6.9 ms | 10.8 ms | 0 | 1.06 | 586 MB | 2.49 cores |
| 2,000 | 1,260 | 0.6 ms | 6.5 ms | 10.1 ms | 0 | 1.64 | 785 MB | 2.44 cores |
| 3,000 | 1,902 | 0.6 ms | 7.3 ms | 12.2 ms | 0 | 2.21 (throttled 1%) | 848 MB | 2.54 cores |
| 4,000 | 2,551 | 0.7 ms | 14.0 ms | 30.2 ms | 0 | 2.80 (throttled 9%) | 905 MB | 2.22 cores |
| 5,000 | 3,153 | 2.9 ms | 90.7 ms | 113 ms | 0 | 3.59 (throttled 62%) | 963 MB | 3.83 cores |
| 6,000 | 3,633 | 24.0 ms | 415 ms | 500 ms | 0 | 3.90 (throttled 85%) | 1.04 GB | 2.39 cores |

### p99 by request type

| Request type | 1,000 users | 2,000 users | 3,000 users | 4,000 users | 5,000 users | 6,000 users |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Search (typed) | 9.0 ms | 9.0 ms | 11.3 ms | 29.2 ms | 110 ms | 480 ms |
| A–Z index for a search | 6.9 ms | 6.8 ms | 8.8 ms | 27.2 ms | 107 ms | 477 ms |
| List page | 25.1 ms | 23.4 ms | 23.8 ms | 33.6 ms | 116 ms | 509 ms |
| A–Z index | 9.9 ms | 9.5 ms | 10.6 ms | 27.4 ms | 112 ms | 492 ms |
| Open a contact | 3.6 ms | 5.2 ms | 7.5 ms | 31.3 ms | 114 ms | 509 ms |
| Save a contact | 14.8 ms | 11.5 ms | 11.8 ms | 12.1 ms | 12.8 ms | 11.3 ms |
| Tags | 9.0 ms | 8.7 ms | 10.4 ms | 30.2 ms | 114 ms | 507 ms |
| Stats | 9.6 ms | 9.8 ms | 11.4 ms | 32.0 ms | 116 ms | 508 ms |

Simulated users open the app, then act every ~3 s on average: scroll or jump letters (35%), type a search (30%), open a contact (25%), switch view (5%), edit and save (5%). Each level warms up for 10 s and is measured for 30 s. Capacity is where p99 latency crosses 100 ms, interpolated between tested levels. A level whose p99 passes 2,000 ms ends that stack's ramp. Single-endpoint tests use 50 clients with no pauses. CPU is CPU-seconds used during the measured window divided by its length (1.0 = one core).

## Single endpoints

| Request | req/s | p50 | p99 | Errors |
| --- | ---: | ---: | ---: | ---: |
| Single contact | 37,997 | 1.2 ms | 3.3 ms | 0 |
| List page 1 (uncached) | 14,745 | 3.3 ms | 5.0 ms | 0 |
| List page at offset 55,000 | 5,141 | 8.2 ms | 29.1 ms | 0 |
| Search `smith` (cached) | 20,283 | 2.4 ms | 3.7 ms | 0 |
| A–Z index (cached) | 52,983 | 0.9 ms | 2.6 ms | 0 |
| Stats (cached) | 70,866 | 0.6 ms | 2.4 ms | 0 |

## Optimization history

Every change tried on this stack, oldest first, from [the optimization log](../../docs/optimization-log.md).

| When | Change | Effect | Status |
| --- | --- | --- | --- |
| before 2026-09-30 | one process with reader threads instead of 4 cluster workers (4 caches missed ~58% each) | native: ~2,900 → ~5,050 users; single contact ~70,000 → ~39,000 req/s (a message hop per uncached request) | kept |
| before 2026-09-30 | reader threads on the built-in `node:sqlite` (global locks on) | native: p99 630 ms at 2,000 users, worse than the cluster; switched to `better-sqlite3`, whose SQLite has no global locks | reverted |
