# Backend benchmark: comparison

|  |  |
| --- | --- |
| **CPU** | Apple M5 Max |
| **Cores** | 18 physical / 18 logical (6 Super, 12 Performance) |
| **Memory** | 36.0 GB |
| **OS** | macOS 27.0 (kernel 27.0.0, arm64) |
| **Power** | AC power |
| **Mode** | Docker 29.2.1 (Docker Desktop, 18 CPUs / 7.7 GB for containers); each server in a container limited to 4 CPUs / 4g, load generator on the Docker network |
| **Memory metric** | container working set (cgroup memory.current minus inactive_file) |

> **Warning:** Measured while the machine was busy with other work: Rust, Node, Rails, Rails + ActiveRecord, Go, C#, C, Java (Spring Boot). Those results are noisy; rerun them on an idle machine before comparing or sharing.

## At a glance

| Stack | Users at p99 ≈ 100 ms | Single contact req/s | List page req/s | Idle memory | Peak memory | Startup | Seed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| [Rust](rust/report.html) | ~5,250 | 35,016 | 14,450 | 4 MB | 450 MB | 16.0 ms | 2.6 s |
| [Python](python/report.html) | ~2,450 | 59,033 | 14,882 | 222 MB | 725 MB | 860 ms | 4.4 s |
| [Node](node/report.html) | ~4,850 | 37,997 | 14,745 | 91 MB | 1.04 GB | 155 ms | 3.0 s |
| [Rails](rails/report.html) | ~2,850 | 15,415 | 8,404 | 116 MB | 917 MB | 674 ms | 4.5 s |
| [Rails + ActiveRecord](rails-ar/report.html) | ~1,150 | 4,355 | 1,318 | 116 MB | 958 MB | 717 ms | 51.9 s |
| [Go](go/report.html) | ~5,300 | 58,360 | 19,324 | 15 MB | 273 MB | 16.0 ms | 4.7 s |
| [C#](csharp/report.html) | ≥ 6,000 | 62,127 | 17,172 | 41 MB | 379 MB | 174 ms | 3.5 s |
| [C](c/report.html) | ≥ 6,000 | 88,013 | 26,207 | 3 MB | 177 MB | 17.0 ms | 2.7 s |
| [Java (Spring Boot)](java-spring/report.html) | ~4,700 | 34,138 | 13,099 | 176 MB | 1.35 GB | 929 ms | 4.0 s |

## p99 latency by simulated users

| Users | Rust | Python | Node | Rails | Rails + ActiveRecord | Go | C# | C | Java (Spring Boot) |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 | 10.3 ms | 29.3 ms | 10.8 ms | 23.7 ms | 34.8 ms | 11.1 ms | 12.4 ms | 10.5 ms | 11.8 ms |
| 2,000 | 9.7 ms | 44.7 ms | 10.1 ms | 30.9 ms | 437 ms | 10.3 ms | 10.1 ms | 9.8 ms | 11.0 ms |
| 3,000 | 11.2 ms | 171 ms | 12.2 ms | 113 ms | 1,709 ms | 12.8 ms | 9.8 ms | 11.4 ms | 14.3 ms |
| 4,000 | 20.0 ms | 6,694 ms | 30.2 ms | 1,064 ms | 3,064 ms | 25.5 ms | 9.6 ms | 19.3 ms | 36.6 ms |
| 5,000 | 52.3 ms | — | 113 ms | 1,907 ms | — | 64.8 ms | 13.3 ms | 36.8 ms | 130 ms |
| 6,000 | 243 ms | — | 500 ms | 2,612 ms | — | 191 ms | 20.4 ms | 72.3 ms | 282 ms |

## CPU cores used

| Users | Rust | Python | Node | Rails | Rails + ActiveRecord | Go | C# | C | Java (Spring Boot) |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 | 0.98 | 1.33 | 1.06 | 1.28 | 2.09 | 1.01 | 0.77 | 0.99 | 1.12 |
| 2,000 | 1.50 | 2.39 | 1.64 | 2.38 | 3.96 | 1.48 | 1.18 | 1.51 | 1.71 |
| 3,000 | 2.02 | 3.66 | 2.21 | 3.56 | 3.99 | 1.98 | 1.57 | 2.00 | 2.31 |
| 4,000 | 2.54 | 3.99 | 2.80 | 3.96 | 3.98 | 2.45 | 1.91 | 2.51 | 2.96 |
| 5,000 | 3.09 | — | 3.59 | 3.97 | — | 2.94 | 2.71 | 2.98 | 3.62 |
| 6,000 | 3.69 | — | 3.90 | 3.96 | — | 3.46 | 3.17 | 3.45 | 3.92 |

## Single endpoints (requests/second)

| Request | Rust | Python | Node | Rails | Rails + ActiveRecord | Go | C# | C | Java (Spring Boot) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Single contact | 35,016 | 59,033 | 37,997 | 15,415 | 4,355 | 58,360 | 62,127 | 88,013 | 34,138 |
| List page 1 (uncached) | 14,450 | 14,882 | 14,745 | 8,404 | 1,318 | 19,324 | 17,172 | 26,207 | 13,099 |
| List page at offset 55,000 | 5,730 | 3,596 | 5,141 | 3,843 | 1,146 | 5,225 | 3,835 | 5,279 | 4,666 |
| Search `smith` (cached) | 78,446 | 27,087 | 20,283 | 13,876 | 13,390 | 78,616 | 64,145 | 65,056 | 40,913 |
| A–Z index (cached) | 139,121 | 51,961 | 52,983 | 15,261 | 15,414 | 156,978 | 106,113 | 171,226 | 103,136 |
| Stats (cached) | 184,112 | 88,912 | 70,866 | 16,743 | 16,660 | 218,021 | 146,383 | 263,389 | 147,569 |

## Stacks and verification

| Stack | Runtime and framework | Concurrency | Seed checksum | API parity | Status |
| --- | --- | --- | --- | --- | --- |
| Rust | Axum, rusqlite (bundled SQLite), moka cache | 1 process, 4 Tokio threads, 4 read connections | ✅ pass | reference | ok |
| Python | FastAPI, uvicorn (uvloop, httptools), sqlite3, orjson | 4 workers, reads on each event loop, 1 write thread each | ✅ pass | ✅ pass | ok |
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
| Rust | 2026-09-30 22:32:03 | standard (Docker) | 4 | Apple M5 Max | busy ⚠ | 92b273d |
| Python | 2026-10-05 15:38:34 | standard (Docker) | 4 | Apple M5 Max | quiet | 5b283bc |
| Node | 2026-09-30 23:15:32 | standard (Docker) | 4 | Apple M5 Max | busy ⚠ | 92b273d |
| Rails | 2026-09-30 23:39:34 | standard (Docker) | 4 | Apple M5 Max | busy ⚠ | 92b273d |
| Rails + ActiveRecord | 2026-09-30 23:49:08 | standard (Docker) | 4 | Apple M5 Max | busy ⚠ | 92b273d |
| Go | 2026-09-30 23:58:26 | standard (Docker) | 4 | Apple M5 Max | busy ⚠ | 92b273d |
| C# | 2026-10-01 00:05:35 | standard (Docker) | 4 | Apple M5 Max | busy ⚠ | 92b273d |
| C | 2026-10-01 00:26:03 | standard (Docker) | 4 | Apple M5 Max | busy ⚠ | 92b273d |
| Java (Spring Boot) | 2026-10-01 00:39:49 | standard (Docker) | 4 | Apple M5 Max | busy ⚠ | 92b273d |

## Method

Simulated users open the app, then act every ~3 s on average: scroll or jump letters (35%), type a search (30%), open a contact (25%), switch view (5%), edit and save (5%). Each level warms up for 10 s and is measured for 30 s. Capacity is where p99 latency crosses 100 ms, interpolated between tested levels. A level whose p99 passes 2,000 ms ends that stack's ramp. Single-endpoint tests use 50 clients with no pauses. CPU is CPU-seconds used during the measured window divided by its length (1.0 = one core).
