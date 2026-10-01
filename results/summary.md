# Backend benchmark: comparison

|  |  |
| --- | --- |
| **CPU** | Apple M5 Max |
| **Cores** | 18 physical / 18 logical (6 Super, 12 Performance) |
| **Memory** | 36.0 GB |
| **OS** | macOS 27.0 (kernel 27.0.0, arm64) |
| **Power** | AC power |
| **Memory metric** | physical footprint (vmmap) |

> **Warning:** Measured while the machine was busy with other work: C#, Java (Spring Boot). Those results are noisy; rerun them on an idle machine before comparing or sharing.

## At a glance

| Stack | Users at p99 ≈ 100 ms | Single contact req/s | List page req/s | Idle memory | Peak memory | Startup | Seed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| [Rust](rust/report.html) | ~5,100 | 71,548 | 27,252 | 3 MB | 210 MB | 204 ms | 2.6 s |
| [Python](python/report.html) | ~3,050 | 13,484 | 2,758 | 211 MB | 905 MB | 285 ms | 4.3 s |
| [Node](node/report.html) | ~5,050 | 38,788 | 16,639 | 102 MB | 1.00 GB | 175 ms | 3.1 s |
| [Rails](rails/report.html) | ~3,000 | 18,917 | 11,224 | 199 MB | 951 MB | 794 ms | 4.2 s |
| [Rails + ActiveRecord](rails-ar/report.html) | ~1,950 | 5,719 | 1,633 | 199 MB | 960 MB | 802 ms | 42.1 s |
| [Go](go/report.html) | ~5,500 | 55,375 | 20,110 | 4 MB | 259 MB | 235 ms | 4.6 s |
| [C#](csharp/report.html) | ≥ 6,000 | 79,135 | 21,531 | 63 MB | 836 MB | 181 ms | 3.2 s |
| [C](c/report.html) | ≥ 6,000 | 48,475 | 25,523 | 3 MB | 186 MB | 7.0 ms | 2.6 s |
| [Java (Spring Boot)](java-spring/report.html) | ~5,600 | 71,837 | 17,456 | 176 MB | 1.00 GB | 879 ms | 4.1 s |

## p99 latency by simulated users

| Users | Rust | Python | Node | Rails | Rails + ActiveRecord | Go | C# | C | Java (Spring Boot) |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 | 11.1 ms | 11.6 ms | 11.0 ms | 23.3 ms | 45.6 ms | 11.5 ms | 11.9 ms | 10.7 ms | 11.8 ms |
| 2,000 | 11.1 ms | 19.8 ms | 10.9 ms | 43.7 ms | 103 ms | 11.0 ms | 10.4 ms | 10.4 ms | 13.8 ms |
| 3,000 | 13.1 ms | 50.9 ms | 14.1 ms | 88.1 ms | 1,216 ms | 14.5 ms | 9.8 ms | 12.5 ms | 14.8 ms |
| 4,000 | 26.8 ms | 752 ms | 31.7 ms | 859 ms | 2,257 ms | 29.3 ms | 10.2 ms | 20.1 ms | 31.5 ms |
| 5,000 | 57.8 ms | 1,571 ms | 80.2 ms | 2,587 ms | — | 68.7 ms | 11.7 ms | 43.5 ms | 61.2 ms |
| 6,000 | 486 ms | 3,341 ms | 376 ms | — | — | 133 ms | 14.7 ms | 76.7 ms | 127 ms |

## CPU cores used

| Users | Rust | Python | Node | Rails | Rails + ActiveRecord | Go | C# | C | Java (Spring Boot) |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 | 1.04 | 1.42 | 1.11 | 1.34 | 2.06 | 1.09 | 0.85 | 1.03 | 1.14 |
| 2,000 | 1.65 | 3.08 | 1.74 | 2.51 | 3.69 | 1.66 | 1.29 | 1.61 | 1.80 |
| 3,000 | 2.27 | 4.18 | 2.40 | 3.63 | 4.02 | 2.22 | 1.87 | 2.22 | 2.36 |
| 4,000 | 2.81 | 10.84 | 3.06 | 4.03 | 4.02 | 2.74 | 2.30 | 2.79 | 2.99 |
| 5,000 | 3.41 | 14.85 | 3.84 | 3.98 | — | 3.23 | 3.00 | 3.40 | 3.55 |
| 6,000 | 4.07 | 14.72 | 4.32 | — | — | 3.69 | 3.49 | 4.31 | 4.10 |

## Single endpoints (requests/second)

| Request | Rust | Python | Node | Rails | Rails + ActiveRecord | Go | C# | C | Java (Spring Boot) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Single contact | 71,548 | 13,484 | 38,788 | 18,917 | 5,719 | 55,375 | 79,135 | 48,475 | 71,837 |
| List page 1 (uncached) | 27,252 | 2,758 | 16,639 | 11,224 | 1,633 | 20,110 | 21,531 | 25,523 | 17,456 |
| List page at offset 55,000 | 5,297 | 3,476 | 5,752 | 4,324 | 1,432 | 5,194 | 4,926 | 5,200 | 4,950 |
| Search `smith` (cached) | 70,403 | 19,407 | 20,635 | 18,602 | 18,363 | 89,986 | 67,825 | 64,301 | 80,737 |
| A–Z index (cached) | 115,735 | 26,281 | 44,729 | 20,629 | 20,287 | 150,869 | 121,995 | 136,758 | 123,330 |
| Stats (cached) | 133,054 | 33,646 | 57,754 | 21,864 | 21,497 | 165,132 | 131,628 | 154,286 | 134,431 |

## Stacks and verification

| Stack | Runtime and framework | Concurrency | Seed checksum | API parity | Status |
| --- | --- | --- | --- | --- | --- |
| Rust | Axum, rusqlite (bundled SQLite), moka cache | 1 process, 4 Tokio threads, 4 read connections | ✅ pass | reference | ok |
| Python | FastAPI, uvicorn (uvloop, httptools), sqlite3, orjson | 4 workers x 4 threads | ✅ pass | ✅ pass | ok |
| Node | Fastify, built-in node:sqlite on worker threads | 1 process: event loop + 4 reader threads + 1 writer thread | ✅ pass | ✅ pass | ok |
| Rails | Rails 8.1 API, Puma, sqlite3 gem (direct SQL) | 4 Puma workers x 1 thread | ✅ pass | ✅ pass | ok |
| Rails + ActiveRecord | Same Rails app on ActiveRecord models | 4 Puma workers x 1 thread | ✅ pass | ✅ pass | ok |
| Go | net/http, mattn/go-sqlite3, klauspost gzip | 1 process, GOMAXPROCS=4, 4 read connections | ✅ pass | ✅ pass | ok |
| C# | ASP.NET Core minimal APIs, Microsoft.Data.Sqlite, source-generated JSON | 1 process, DOTNET_PROCESSOR_COUNT=4, 4 read connections | ✅ pass | ✅ pass | ok |
| C | libmicrohttpd, SQLite amalgamation (compiled in), yyjson, zlib | 1 process, 4 threads, one read connection each | ✅ pass | ✅ pass | ok |
| Java (Spring Boot) | Spring Boot 4.1 (Spring MVC on Tomcat), JDK 27, xerial sqlite-jdbc, Jackson | 1 JVM, -XX:ActiveProcessorCount=4, Tomcat thread per request, 4 read connections | ✅ pass | ✅ pass | ok |

## When and how each backend was measured

| Stack | Measured | Profile | Core budget | Machine | Load | Commit |
| --- | --- | --- | --- | --- | --- | --- |
| Rust | 2026-09-30 12:29:21 | standard | 4 | Apple M5 Max | quiet | uncommitted |
| Python | 2026-09-30 15:35:51 | standard | 4 | Apple M5 Max | quiet | uncommitted |
| Node | 2026-09-30 15:07:23 | standard | 4 | Apple M5 Max | quiet | uncommitted |
| Rails | 2026-09-30 20:35:39 | standard | 4 | Apple M5 Max | quiet | uncommitted |
| Rails + ActiveRecord | 2026-09-30 20:26:12 | standard | 4 | Apple M5 Max | quiet | uncommitted |
| Go | 2026-09-30 11:09:21 | standard | 4 | Apple M5 Max | quiet | uncommitted |
| C# | 2026-09-30 13:24:03 | standard | 4 | Apple M5 Max | busy ⚠ | uncommitted |
| C | 2026-09-30 11:37:20 | standard | 4 | Apple M5 Max | quiet | uncommitted |
| Java (Spring Boot) | 2026-09-30 19:41:12 | standard | 4 | Apple M5 Max | busy ⚠ | uncommitted |

## Method

Simulated users open the app, then act every ~3 s on average: scroll or jump letters (35%), type a search (30%), open a contact (25%), switch view (5%), edit and save (5%). Each level warms up for 10 s and is measured for 30 s. Capacity is where p99 latency crosses 100 ms, interpolated between tested levels. A level whose p99 passes 2,000 ms ends that stack's ramp. Single-endpoint tests use 50 clients with no pauses. CPU is CPU-seconds used during the measured window divided by its length (1.0 = one core).
