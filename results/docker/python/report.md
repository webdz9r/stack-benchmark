# Python: benchmark results

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

**Other programs:** used up to 1.9 cores (threshold 1.8) — BUSY: treat these numbers as noisy

> **Warning:** other programs were using the CPU while this ran, so these results are noisy.

**Stack:** FastAPI, uvicorn (uvloop, httptools), sqlite3, orjson  
**Concurrency:** 4 workers x 4 threads  
**Versions:** Python 3.14.7  

## Summary

| Metric | Value |
| --- | ---: |
| Users at p99 ≈ 100 ms | ~2,050 |
| Startup to first response | 836 ms |
| Idle memory | 228 MB |
| Peak memory after a load level | 907 MB |
| Processes | 8 |
| Seed checksum (VER-1) | ✅ pass |
| API parity (VER-2) | ✅ pass (71 identical, 0 mismatched; 42/42 contract checks passed) |
| Seeding | 100,000 contacts in 4.4 s (22,870/s) |
| Image | python:3.14-slim-trixie runtime, 250MB |
| SQLite in the image | 3.46.1 |

## Simulated users

| Users | req/s | p50 | p95 | p99 | Errors | CPU cores | Memory after | Other programs |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 | 633 | 1.8 ms | 7.6 ms | 11.0 ms | 0 | 1.47 | 375 MB | 0.37 cores |
| 2,000 | 1,259 | 1.8 ms | 8.8 ms | 32.3 ms | 0 | 2.65 (throttled 9%) | 578 MB | 0.34 cores |
| 3,000 | 1,230 | 1,372 ms | 1,622 ms | 1,728 ms | 0 | 4.00 (throttled 100%) | 783 MB | 0.31 cores |
| 4,000 | 1,245 | 2,636 ms | 3,077 ms | 3,206 ms | 0 | 4.00 (throttled 100%) | 907 MB | 1.95 cores |

### p99 by request type

| Request type | 1,000 users | 2,000 users | 3,000 users | 4,000 users |
| --- | ---: | ---: | ---: | ---: |
| Search (typed) | 9.3 ms | 35.8 ms | 1,738 ms | 3,207 ms |
| A–Z index for a search | 7.6 ms | 30.3 ms | 1,728 ms | 3,219 ms |
| List page | 28.7 ms | 35.4 ms | 1,727 ms | 3,206 ms |
| A–Z index | 10.5 ms | 27.5 ms | 1,720 ms | 3,202 ms |
| Open a contact | 2.0 ms | 25.9 ms | 1,713 ms | 3,198 ms |
| Save a contact | 11.4 ms | 13.3 ms | 1,689 ms | 3,195 ms |
| Tags | 6.1 ms | 11.9 ms | 1,697 ms | 3,203 ms |
| Stats | 8.2 ms | 16.8 ms | 1,776 ms | 3,206 ms |

Simulated users open the app, then act every ~3 s on average: scroll or jump letters (35%), type a search (30%), open a contact (25%), switch view (5%), edit and save (5%). Each level warms up for 10 s and is measured for 30 s. Capacity is where p99 latency crosses 100 ms, interpolated between tested levels. A level whose p99 passes 2,000 ms ends that stack's ramp. Single-endpoint tests use 50 clients with no pauses. CPU is CPU-seconds used during the measured window divided by its length (1.0 = one core).

## Single endpoints

| Request | req/s | p50 | p99 | Errors |
| --- | ---: | ---: | ---: | ---: |
| Single contact | 5,795 | 6.4 ms | 38.5 ms | 0 |
| List page 1 (uncached) | 1,399 | 27.9 ms | 74.7 ms | 0 |
| List page at offset 55,000 | 1,309 | 23.7 ms | 83.1 ms | 0 |
| Search `smith` (cached) | 15,818 | 2.7 ms | 10.8 ms | 0 |
| A–Z index (cached) | 18,448 | 2.3 ms | 10.6 ms | 0 |
| Stats (cached) | 20,626 | 1.8 ms | 13.7 ms | 0 |
