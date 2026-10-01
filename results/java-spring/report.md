# Java (Spring Boot): benchmark results

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

**Other programs:** used up to 2.5 cores (threshold 1.8) — BUSY: treat these numbers as noisy

> **Warning:** other programs were using the CPU while this ran, so these results are noisy.

**Stack:** Spring Boot 4.1 (Spring MVC on Tomcat), JDK 27, xerial sqlite-jdbc, Jackson  
**Concurrency:** 1 JVM, -XX:ActiveProcessorCount=4, Tomcat thread per request, 4 read connections  
**Versions:** openjdk version "27" 2026-09-15  

## Summary

| Metric | Value |
| --- | ---: |
| Users at p99 ≈ 100 ms | ~4,700 |
| Startup to first response | 929 ms |
| Idle memory | 176 MB |
| Peak memory after a load level | 1.35 GB |
| Processes | 3 |
| Seed checksum (VER-1) | ✅ pass |
| API parity (VER-2) | ✅ pass (71 identical, 0 mismatched; 42/42 contract checks passed) |
| Seeding | 100,000 contacts in 4.0 s (25,316/s) |
| Image | debian:trixie-slim runtime, 484MB |
| SQLite in the image | 3.53.4 |

## Simulated users

| Users | req/s | p50 | p95 | p99 | Errors | CPU cores | Memory after | Other programs |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 | 633 | 0.8 ms | 7.6 ms | 11.8 ms | 0 | 1.12 | 586 MB | 2.46 cores |
| 2,000 | 1,260 | 0.6 ms | 7.1 ms | 11.0 ms | 0 | 1.71 | 711 MB | 1.09 cores |
| 3,000 | 1,902 | 0.5 ms | 8.5 ms | 14.3 ms | 0 | 2.31 (throttled 1%) | 803 MB | 0.60 cores |
| 4,000 | 2,551 | 0.6 ms | 18.0 ms | 36.6 ms | 0 | 2.96 (throttled 16%) | 978 MB | 0.25 cores |
| 5,000 | 3,148 | 3.5 ms | 101 ms | 130 ms | 0 | 3.62 (throttled 62%) | 1.17 GB | 0.40 cores |
| 6,000 | 3,675 | 64.1 ms | 231 ms | 282 ms | 0 | 3.92 (throttled 91%) | 1.35 GB | 0.31 cores |

### p99 by request type

| Request type | 1,000 users | 2,000 users | 3,000 users | 4,000 users | 5,000 users | 6,000 users |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Search (typed) | 9.8 ms | 9.6 ms | 12.9 ms | 35.0 ms | 121 ms | 268 ms |
| A–Z index for a search | 7.6 ms | 7.7 ms | 11.3 ms | 33.4 ms | 118 ms | 271 ms |
| List page | 27.7 ms | 26.4 ms | 25.7 ms | 40.1 ms | 140 ms | 296 ms |
| A–Z index | 11.2 ms | 10.7 ms | 13.7 ms | 34.9 ms | 129 ms | 271 ms |
| Open a contact | 3.7 ms | 5.6 ms | 9.6 ms | 41.1 ms | 146 ms | 305 ms |
| Save a contact | 12.4 ms | 11.5 ms | 11.4 ms | 11.4 ms | 22.8 ms | 172 ms |
| Tags | 10.5 ms | 10.0 ms | 12.9 ms | 37.4 ms | 133 ms | 279 ms |
| Stats | 11.5 ms | 10.4 ms | 14.3 ms | 36.2 ms | 134 ms | 278 ms |

Simulated users open the app, then act every ~3 s on average: scroll or jump letters (35%), type a search (30%), open a contact (25%), switch view (5%), edit and save (5%). Each level warms up for 10 s and is measured for 30 s. Capacity is where p99 latency crosses 100 ms, interpolated between tested levels. A level whose p99 passes 2,000 ms ends that stack's ramp. Single-endpoint tests use 50 clients with no pauses. CPU is CPU-seconds used during the measured window divided by its length (1.0 = one core).

## Single endpoints

| Request | req/s | p50 | p99 | Errors |
| --- | ---: | ---: | ---: | ---: |
| Single contact | 34,138 | 0.7 ms | 18.3 ms | 0 |
| List page 1 (uncached) | 13,099 | 2.5 ms | 41.6 ms | 0 |
| List page at offset 55,000 | 4,666 | 9.4 ms | 33.0 ms | 0 |
| Search `smith` (cached) | 40,913 | 0.8 ms | 16.5 ms | 0 |
| A–Z index (cached) | 103,136 | 0.4 ms | 1.3 ms | 0 |
| Stats (cached) | 147,569 | 0.3 ms | 1.1 ms | 0 |
