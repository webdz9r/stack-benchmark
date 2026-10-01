# Rails: benchmark results

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

**Other programs:** used up to 3.1 cores (threshold 1.8) — BUSY: treat these numbers as noisy

> **Warning:** other programs were using the CPU while this ran, so these results are noisy.

**Stack:** Rails 8.1 API, Puma, sqlite3 gem (direct SQL)  
**Concurrency:** 4 Puma workers x 1 thread  
**Versions:** ruby 4.0.1 (2026-01-13 revision e04267a14b) +PRISM [aarch64-linux]; Rails 8.1.4  

## Summary

| Metric | Value |
| --- | ---: |
| Users at p99 ≈ 100 ms | ~2,850 |
| Startup to first response | 674 ms |
| Idle memory | 116 MB |
| Peak memory after a load level | 917 MB |
| Processes | 7 |
| Seed checksum (VER-1) | ✅ pass |
| API parity (VER-2) | ✅ pass (71 identical, 0 mismatched; 42/42 contract checks passed) |
| Seeding | 100,000 contacts in 4.5 s (22,432/s) |
| Image | ruby:4.0.1-slim-trixie runtime, 404MB |
| SQLite in the image | 3.53.2 |

## Simulated users

| Users | req/s | p50 | p95 | p99 | Errors | CPU cores | Memory after | Other programs |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 | 633 | 3.0 ms | 12.2 ms | 23.7 ms | 0 | 1.28 | 440 MB | 1.39 cores |
| 2,000 | 1,258 | 4.7 ms | 19.5 ms | 30.9 ms | 0 | 2.38 | 571 MB | 0.34 cores |
| 3,000 | 1,881 | 18.9 ms | 76.3 ms | 113 ms | 0 | 3.56 (throttled 18%) | 694 MB | 0.38 cores |
| 4,000 | 2,081 | 522 ms | 975 ms | 1,064 ms | 0 | 3.96 (throttled 30%) | 794 MB | 0.60 cores |
| 5,000 | 1,937 | 1,618 ms | 1,850 ms | 1,907 ms | 0 | 3.97 (throttled 38%) | 826 MB | 3.09 cores |
| 6,000 | 2,089 | 2,046 ms | 2,487 ms | 2,612 ms | 0 | 3.96 (throttled 41%) | 917 MB | 2.80 cores |

### p99 by request type

| Request type | 1,000 users | 2,000 users | 3,000 users | 4,000 users | 5,000 users | 6,000 users |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Search (typed) | 20.3 ms | 30.4 ms | 113 ms | 1,059 ms | 1,910 ms | 2,620 ms |
| A–Z index for a search | 19.7 ms | 31.0 ms | 114 ms | 1,072 ms | 1,908 ms | 2,615 ms |
| List page | 27.6 ms | 31.2 ms | 112 ms | 1,061 ms | 1,906 ms | 2,612 ms |
| A–Z index | 28.0 ms | 32.5 ms | 116 ms | 1,068 ms | 1,904 ms | 2,585 ms |
| Open a contact | 19.2 ms | 29.3 ms | 111 ms | 1,066 ms | 1,901 ms | 2,608 ms |
| Save a contact | 14.8 ms | 32.1 ms | 118 ms | 1,061 ms | 1,902 ms | 2,620 ms |
| Tags | 21.8 ms | 30.6 ms | 110 ms | 1,042 ms | 1,902 ms | 2,577 ms |
| Stats | 23.7 ms | 30.7 ms | 111 ms | 1,051 ms | 1,909 ms | 2,604 ms |

Simulated users open the app, then act every ~3 s on average: scroll or jump letters (35%), type a search (30%), open a contact (25%), switch view (5%), edit and save (5%). Each level warms up for 10 s and is measured for 30 s. Capacity is where p99 latency crosses 100 ms, interpolated between tested levels. A level whose p99 passes 2,000 ms ends that stack's ramp. Single-endpoint tests use 50 clients with no pauses. CPU is CPU-seconds used during the measured window divided by its length (1.0 = one core).

## Single endpoints

| Request | req/s | p50 | p99 | Errors |
| --- | ---: | ---: | ---: | ---: |
| Single contact | 15,415 | 3.1 ms | 6.3 ms | 0 |
| List page 1 (uncached) | 8,404 | 5.6 ms | 10.7 ms | 0 |
| List page at offset 55,000 | 3,843 | 13.0 ms | 17.1 ms | 0 |
| Search `smith` (cached) | 13,876 | 3.5 ms | 7.6 ms | 0 |
| A–Z index (cached) | 15,261 | 3.1 ms | 6.2 ms | 0 |
| Stats (cached) | 16,743 | 3.1 ms | 4.8 ms | 0 |
