# Rails + ActiveRecord: benchmark results

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

**Other programs:** used up to 3.4 cores (threshold 1.8) — BUSY: treat these numbers as noisy

> **Warning:** other programs were using the CPU while this ran, so these results are noisy.

**Stack:** Same Rails app on ActiveRecord models  
**Concurrency:** 4 Puma workers x 1 thread  
**Versions:** ruby 4.0.1 (2026-01-13 revision e04267a14b) +PRISM [aarch64-linux]; Rails 8.1.4  

## Summary

| Metric | Value |
| --- | ---: |
| Users at p99 ≈ 100 ms | ~1,150 |
| Startup to first response | 717 ms |
| Idle memory | 116 MB |
| Peak memory after a load level | 958 MB |
| Processes | 7 |
| Seed checksum (VER-1) | ✅ pass |
| API parity (VER-2) | ✅ pass (71 identical, 0 mismatched; 42/42 contract checks passed) |
| Seeding | 100,000 contacts in 51.9 s (1,929/s) |
| Image | ruby:4.0.1-slim-trixie runtime, 404MB |
| SQLite in the image | 3.53.2 |

## Simulated users

| Users | req/s | p50 | p95 | p99 | Errors | CPU cores | Memory after | Other programs |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 | 631 | 6.0 ms | 22.9 ms | 34.8 ms | 0 | 2.09 | 585 MB | 2.41 cores |
| 2,000 | 1,157 | 196 ms | 393 ms | 437 ms | 0 | 3.96 (throttled 57%) | 720 MB | 3.06 cores |
| 3,000 | 1,205 | 1,429 ms | 1,642 ms | 1,709 ms | 0 | 3.99 (throttled 64%) | 898 MB | 2.46 cores |
| 4,000 | 1,240 | 2,597 ms | 2,963 ms | 3,064 ms | 0 | 3.98 (throttled 64%) | 958 MB | 2.20 cores |

### p99 by request type

| Request type | 1,000 users | 2,000 users | 3,000 users | 4,000 users |
| --- | ---: | ---: | ---: | ---: |
| Search (typed) | 37.4 ms | 441 ms | 1,715 ms | 3,065 ms |
| A–Z index for a search | 34.0 ms | 436 ms | 1,709 ms | 3,062 ms |
| List page | 35.5 ms | 437 ms | 1,708 ms | 3,063 ms |
| A–Z index | 33.7 ms | 434 ms | 1,704 ms | 3,063 ms |
| Open a contact | 30.5 ms | 433 ms | 1,692 ms | 3,068 ms |
| Save a contact | 32.7 ms | 434 ms | 1,719 ms | 3,069 ms |
| Tags | 33.3 ms | 438 ms | 1,698 ms | 3,045 ms |
| Stats | 33.8 ms | 432 ms | 1,707 ms | 3,057 ms |

Simulated users open the app, then act every ~3 s on average: scroll or jump letters (35%), type a search (30%), open a contact (25%), switch view (5%), edit and save (5%). Each level warms up for 10 s and is measured for 30 s. Capacity is where p99 latency crosses 100 ms, interpolated between tested levels. A level whose p99 passes 2,000 ms ends that stack's ramp. Single-endpoint tests use 50 clients with no pauses. CPU is CPU-seconds used during the measured window divided by its length (1.0 = one core).

## Single endpoints

| Request | req/s | p50 | p99 | Errors |
| --- | ---: | ---: | ---: | ---: |
| Single contact | 4,355 | 12.1 ms | 20.4 ms | 0 |
| List page 1 (uncached) | 1,318 | 35.9 ms | 56.8 ms | 0 |
| List page at offset 55,000 | 1,146 | 43.5 ms | 52.6 ms | 0 |
| Search `smith` (cached) | 13,390 | 3.6 ms | 8.2 ms | 0 |
| A–Z index (cached) | 15,414 | 3.3 ms | 6.0 ms | 0 |
| Stats (cached) | 16,660 | 3.0 ms | 5.1 ms | 0 |

## Optimization history

Every change tried on this stack, oldest first, from [the optimization log](../../docs/optimization-log.md).

| When | Change | Effect | Status |
| --- | --- | --- | --- |
| before 2026-09-30 | one thread per Puma worker (`RAILS_MAX_THREADS=1`); the sqlite3 gem holds the GVL during queries | native, raw SQL: ~2,250 → ~3,000 users; p99 at 3,000 users ~590 → ~140 ms. ActiveRecord: neutral | kept |
| before 2026-09-30 | GC tuning (`RUBY_GC_HEAP_*_INIT_SLOTS`, malloc limits) | ~1,430 req/s either way | no effect |
| before 2026-09-30 | removing unneeded middleware (`Rack::Runtime`, `RequestId`, `RemoteIp`, `Sendfile`, logger) | ~1,430 req/s either way | no effect |
| open | a driver that releases the GVL (e.g. `extralite`), raw data layer only |  | open |
