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
| **Date** | 2026-10-05 15:38:26 |
| **Profile** | standard: the published numbers: 6 user levels (~6 min per stack) |
| **Core budget** | 4 cores per server (the load generator runs on the same machine) |
| **Dataset** | 110,000 contacts |
| **Memory metric** | container working set (cgroup memory.current minus inactive_file) |
| **Repo commit** | 5b283bc (with uncommitted changes) |

**Other programs:** used up to 1.7 cores (threshold 1.8)

**Stack:** FastAPI, uvicorn (uvloop, httptools), sqlite3, orjson  
**Concurrency:** 4 workers, reads on each event loop, 1 write thread each  
**Versions:** Python 3.14.8  

## Summary

| Metric | Value |
| --- | ---: |
| Users at p99 ≈ 100 ms | ~2,450 |
| Startup to first response | 860 ms |
| Idle memory | 222 MB |
| Peak memory after a load level | 725 MB |
| Processes | 8 |
| Seed checksum (VER-1) | ✅ pass |
| API parity (VER-2) | ✅ pass (71 identical, 0 mismatched; 42/42 contract checks passed) |
| Seeding | 100,000 contacts in 4.4 s (22,958/s) |
| Image | python:3.14-slim-trixie runtime, 262MB |
| SQLite in the image | 3.46.1 |

## Simulated users

| Users | req/s | p50 | p95 | p99 | Errors | CPU cores | Memory after | Other programs |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 | 632 | 3.5 ms | 15.6 ms | 29.3 ms | 0 | 1.33 | 339 MB | 1.54 cores |
| 2,000 | 1,256 | 5.8 ms | 27.3 ms | 44.7 ms | 0 | 2.39 | 550 MB | 1.34 cores |
| 3,000 | 1,870 | 23.2 ms | 96.0 ms | 171 ms | 0 | 3.66 (throttled 41%) | 698 MB | 1.39 cores |
| 4,000 | 2,225 | 68.1 ms | 169 ms | 6,694 ms | 0 | 3.99 (throttled 78%) | 725 MB | 1.31 cores |

### p99 by request type

| Request type | 1,000 users | 2,000 users | 3,000 users | 4,000 users |
| --- | ---: | ---: | ---: | ---: |
| Search (typed) | 27.4 ms | 43.2 ms | 122 ms | 210 ms |
| A–Z index for a search | 27.0 ms | 43.0 ms | 122 ms | 208 ms |
| List page | 31.6 ms | 43.2 ms | 121 ms | 194 ms |
| A–Z index | 29.1 ms | 44.6 ms | 124 ms | 188 ms |
| Open a contact | 22.2 ms | 38.4 ms | 119 ms | 192 ms |
| Save a contact | 26.0 ms | 80.2 ms | 933 ms | 13,104 ms |
| Tags | 25.2 ms | 37.5 ms | 121 ms | 174 ms |
| Stats | 31.2 ms | 40.2 ms | 120 ms | 175 ms |

Simulated users open the app, then act every ~3 s on average: scroll or jump letters (35%), type a search (30%), open a contact (25%), switch view (5%), edit and save (5%). Each level warms up for 10 s and is measured for 30 s. Capacity is where p99 latency crosses 100 ms, interpolated between tested levels. A level whose p99 passes 2,000 ms ends that stack's ramp. Single-endpoint tests use 50 clients with no pauses. CPU is CPU-seconds used during the measured window divided by its length (1.0 = one core).

## Single endpoints

| Request | req/s | p50 | p99 | Errors |
| --- | ---: | ---: | ---: | ---: |
| Single contact | 59,033 | 0.8 ms | 1.2 ms | 0 |
| List page 1 (uncached) | 14,882 | 3.0 ms | 5.6 ms | 0 |
| List page at offset 55,000 | 3,596 | 13.4 ms | 16.3 ms | 0 |
| Search `smith` (cached) | 27,087 | 1.7 ms | 2.9 ms | 0 |
| A–Z index (cached) | 51,961 | 1.0 ms | 1.2 ms | 0 |
| Stats (cached) | 88,912 | 0.5 ms | 0.8 ms | 0 |
