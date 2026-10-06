# Java (Spring Boot): benchmark results

[← All backends](../summary.md)

|  |  |
| --- | --- |
| **CPU** | Apple M5 Max |
| **Cores** | 18 physical / 18 logical (6 Super, 12 Performance) |
| **Memory** | 36.0 GB |
| **OS** | macOS 27.0 (kernel 27.0.0, arm64) |
| **Power** | AC power |
| **Date** | 2026-09-30 19:41:07 |
| **Profile** | standard: the published numbers: 6 user levels (~6 min per stack) |
| **Core budget** | 4 cores per server (the load generator runs on the same machine) |
| **Dataset** | 110,000 contacts |
| **Memory metric** | physical footprint (vmmap) |
| **Repo commit** | uncommitted (with uncommitted changes) |
| **Notes** | java-spring: Parallel GC by default |

**Other programs:** used up to 3.6 cores (threshold 1.8) — BUSY: treat these numbers as noisy

> **Warning:** other programs were using the CPU while this ran, so these results are noisy.

**Stack:** Spring Boot 4.1 (Spring MVC on Tomcat), JDK 27, xerial sqlite-jdbc, Jackson  
**Concurrency:** 1 JVM, -XX:ActiveProcessorCount=4, Tomcat thread per request, 4 read connections  
**Versions:** openjdk version "27" 2026-09-15; Apache Maven 3.9.16 (2bdd9fddda4b155ebf8000e807eb73fd829a51d5)  

## Summary

| Metric | Value |
| --- | ---: |
| Users at p99 ≈ 100 ms | ~5,600 |
| Startup to first response | 879 ms |
| Idle memory | 176 MB |
| Peak memory after a load level | 1.00 GB |
| Processes | 1 |
| Seed checksum (VER-1) | ✅ pass |
| API parity (VER-2) | ✅ pass (71 identical, 0 mismatched; 42/42 contract checks passed) |
| Seeding | 100,000 contacts in 4.1 s (24,210/s) |

## Simulated users

| Users | req/s | p50 | p95 | p99 | Errors | CPU cores | Memory after | Other programs |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 | 633 | 0.8 ms | 7.4 ms | 11.8 ms | 0 | 1.14 | 537 MB | 3.57 cores |
| 2,000 | 1,261 | 0.6 ms | 7.8 ms | 13.8 ms | 0 | 1.80 | 661 MB | 2.44 cores |
| 3,000 | 1,902 | 0.5 ms | 8.6 ms | 14.8 ms | 0 | 2.36 | 738 MB | 0.74 cores |
| 4,000 | 2,551 | 0.5 ms | 17.1 ms | 31.5 ms | 0 | 2.99 | 814 MB | 0.71 cores |
| 5,000 | 3,170 | 0.7 ms | 41.3 ms | 61.2 ms | 0 | 3.55 | 918 MB | 0.61 cores |
| 6,000 | 3,759 | 7.1 ms | 103 ms | 127 ms | 0 | 4.10 | 1.00 GB | 0.57 cores |

### p99 by request type

| Request type | 1,000 users | 2,000 users | 3,000 users | 4,000 users | 5,000 users | 6,000 users |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Search (typed) | 9.5 ms | 11.6 ms | 13.8 ms | 30.9 ms | 56.5 ms | 122 ms |
| A–Z index for a search | 7.5 ms | 8.9 ms | 12.2 ms | 29.4 ms | 53.7 ms | 120 ms |
| List page | 27.5 ms | 27.1 ms | 26.4 ms | 34.5 ms | 67.7 ms | 140 ms |
| A–Z index | 10.4 ms | 14.4 ms | 14.5 ms | 29.9 ms | 62.6 ms | 121 ms |
| Open a contact | 3.6 ms | 8.2 ms | 10.4 ms | 30.7 ms | 64.6 ms | 152 ms |
| Save a contact | 8.9 ms | 10.0 ms | 8.7 ms | 8.9 ms | 8.1 ms | 31.9 ms |
| Tags | 9.1 ms | 11.6 ms | 12.5 ms | 30.3 ms | 67.8 ms | 132 ms |
| Stats | 10.4 ms | 14.9 ms | 14.2 ms | 32.1 ms | 65.6 ms | 125 ms |

Simulated users open the app, then act every ~3 s on average: scroll or jump letters (35%), type a search (30%), open a contact (25%), switch view (5%), edit and save (5%). Each level warms up for 10 s and is measured for 30 s. Capacity is where p99 latency crosses 100 ms, interpolated between tested levels. A level whose p99 passes 2,000 ms ends that stack's ramp. Single-endpoint tests use 50 clients with no pauses. CPU is CPU-seconds used during the measured window divided by its length (1.0 = one core).

## Single endpoints

| Request | req/s | p50 | p99 | Errors |
| --- | ---: | ---: | ---: | ---: |
| Single contact | 71,837 | 0.3 ms | 3.6 ms | 0 |
| List page 1 (uncached) | 17,456 | 2.7 ms | 11.0 ms | 0 |
| List page at offset 55,000 | 4,950 | 10.1 ms | 19.3 ms | 0 |
| Search `smith` (cached) | 80,737 | 0.5 ms | 1.5 ms | 0 |
| A–Z index (cached) | 123,330 | 0.4 ms | 0.9 ms | 0 |
| Stats (cached) | 134,431 | 0.3 ms | 0.8 ms | 0 |

## Optimization history

Every change tried on this stack, oldest first, from [the optimization log](../../../docs/optimization-log.md).

| When | Change | Effect | Status |
| --- | --- | --- | --- |
| before 2026-09-30 | Parallel GC instead of G1 | native: p99 at 5,000 users 84 → 71 ms and 172 → 77 ms (two A/Bs); at 6,000, 429 → 170 ms; capacity ~5,250 → ~5,600 | kept |
| before 2026-09-30 | generational ZGC | p99 126 ms at 5,000 users, worse than G1 | no effect |
| open | virtual threads, `-Xmx`, AppCDS for startup |  | open |
