# Java (Spring Boot) backend

The address-book API on **Spring Boot 4.1** (Spring MVC on embedded Tomcat) and
**JDK 27**, with **xerial sqlite-jdbc** and hand-written SQL. Port **7886**. It's
built from [`docs/requirements/`](../../docs/requirements/README.md). A lighter
Java variant (Javalin) may follow as `backend/java-javalin/`.

## Run

Needs Homebrew `openjdk` (keg-only) and `maven`. `/usr/bin/java` on macOS is a
stub unless a JDK is linked, so `run.sh` uses `JAVA_HOME` if set, otherwise
`/opt/homebrew/opt/openjdk`.

```sh
mvn -q package -DskipTests                                  # target/address-book.jar
sqlite3 ../rust/data/address-book.db ".backup data/address-book.db"
JAVA_CPUS=4 DB_READERS=4 ./run.sh                           # API + built UI on :7886
./run.sh seed 110000                                        # seeder (SEED-1)
```

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_PATH` | `data/address-book.db` | SQLite file (created if absent) |
| `BIND_ADDR` / `PORT` | `127.0.0.1:7886` | Listen address |
| `STATIC_DIR` | `../../frontend/dist` | Built UI, served if `index.html` exists |
| `MIGRATIONS_DIR` | `../migrations` | Shared schema, read at startup (ARCH-2) |
| `DB_READERS` | CPU count | Read-only connections in the pool |
| `JAVA_CPUS` | all cores | `-XX:ActiveProcessorCount`: the core budget (ARCH-9/10). GC, JIT and the common pool size themselves from it |
| `JAVA_OPTS` | — | Extra JVM flags |

## Layout

| File | What it does |
| --- | --- |
| `Application.java` | Entry point (server, or `seed`), beans, startup log lines |
| `Db.java` | One writer behind a lock, `DB_READERS` read-only `NOMUTEX` connections, per-connection statement cache, migrations, 5 s checkpoint task |
| `Store.java` | The canonical SQL |
| `Inputs.java` | Strict body parsing, validation V1–V9 / T1–T3, `fts_query` |
| `ResponseCache.java` | 64 MiB LRU by bytes, 30 s TTL, one computation per key for concurrent misses |
| `ApiController.java` | The 13 routes, published generation, `X-Fresh`, ETags and 304s |
| `GzipFilter.java` | gzip level 6 at 32 bytes and over |
| `StaticController.java`, `ErrorAdvice.java` | SPA fallback; JSON errors |

## Choices and deviations

- **SQLite build (DB-2):** xerial's bundled SQLite 3.53 is already built with
  `DEFAULT_MEMSTATUS=0` and without `ENABLE_MEMORY_MANAGEMENT` (checked with
  `PRAGMA compile_options`), so nothing needs setting at runtime.
- **No JdbcTemplate or HikariCP.** The spec wants one serialized writer, a fixed
  read-only pool and cached prepared statements (DB-14). Neither Hikari nor
  sqlite-jdbc caches statements, so `Db` owns its connections. The SQL is sent
  unchanged (DB-15).
- **Explicit `BEGIN IMMEDIATE` / `COMMIT`** on an autocommit connection,
  rather than JDBC's `setAutoCommit(false)`. That takes the write lock up front
  (DB-4) and keeps transaction boundaries visible in `Db.Conn.transaction`.
- **Own gzip filter.** Tomcat's `server.compression` skips any response with a
  strong ETag, so every cached response would have gone out uncompressed
  (HTTP-5). The filter buffers the body, gzips it at level 6 with a per-thread
  `Deflater`, and never caches the gzipped bytes.
- **Strict JSON input.** Bodies are read as a Jackson tree and type-checked by
  hand, so `"yes"`, `1` and `"3"` are never coerced (03-api.md §7). Output uses
  Jackson records in snake_case, in reference field order.
- **Trimming** uses Unicode `White_Space`, like Rust's `str::trim`. Java's
  `strip()` keeps U+00A0, U+2007 and U+202F.
- **Tomcat keep-alive:** `max-keep-alive-requests=-1`. Tomcat's default closes
  a connection after 100 requests, which the other stacks don't do.
- **Threads:** Tomcat's default pool of platform threads, one per request.
  Virtual threads aren't used, because SQLite calls go through JNI and pin
  their carrier thread.
- **GC:** Parallel GC by default (`run.sh`), max heap left at the JVM default
  (¼ of RAM). See Optimizing; a collector set in `JAVA_OPTS` overrides it.

## Optimizing

First standard-profile run (G1): **~5,250 users** at p99 ≈ 100 ms, with p99
11 ms at 2,000, 31 ms at 4,000 and 77 ms at 5,000 users. Single contact
69,300 req/s, list page 1 20,200 req/s, startup 0.9 s, idle memory 247 MB.
Seed checksum and parity passed. The 5,000 and 6,000 levels were measured
with macOS media analysis running (~2.5 cores), so the top end is noisy.

What we found (see also [`docs/optimizing.md`](../../docs/optimizing.md)):

- **The design already avoids the traps the other stacks hit:** xerial's
  SQLite has no global locks (DB-2), one JVM means one shared cache, the cache
  is a plain LRU that admits every entry, and JSON is written outside
  `db.read`, so a connection is held only for SQL and row mapping.
- **The read pool is the queue at 5,000 users**, as in Rust: ~1,800 reads/s at
  ~1.8 ms each keeps the 4 connections ~80% busy, and waiting for one grows to
  20–50 ms on average while queries take ~2 ms. All read types then share the
  same p99 while writes stay at 9 ms.
- **Parallel GC instead of G1** (now the default in `run.sh`). In every A/B
  trial it had the lower tail: p99 at 5,000 users 71 vs 84 ms and 77 vs 172 ms,
  and at 6,000 users 170 vs 429 ms. Its pauses are short young-generation
  stops with no concurrent GC threads competing for the 4 cores.
- **Didn't help:** generational ZGC (p99 126 ms at 5,000, worse than G1): its
  concurrent threads take CPU from the readers.
- **Not tried yet:**
  - virtual threads (`spring.threads.virtual.enabled=true`). The pool, not
    Tomcat's threads, is the limit, so little is expected.
  - `-Xmx` for memory: the heap grows to ~550 MB under load.
  - AppCDS for startup.
- **Tools:** a temporary probe in `Db.read` timing `readers.take()` against
  query time, plus cache calls/misses, logged once a second. That showed the
  read pool was the queue. A/B trials of `JAVA_OPTS` settings with the full
  ramp. JFR (`JAVA_OPTS="-XX:StartFlightRecording=duration=60s,filename=rec.jfr"`)
  and async-profiler for CPU, `jcmd <pid> Thread.print` for thread waits.

## Docker

`Dockerfile` builds this stack on Debian 13 slim with the same settings as
native ([07-containers.md](../../docs/requirements/07-containers.md)). There's no JDK 27 image yet, so Eclipse Temurin 27 (JDK to build, JRE to run) is installed on `debian:trixie-slim`.
Run it with `docker compose --profile java-spring up --build` from the repo root, or
benchmark it with `python3 bench/run.py --mode docker --stacks java-spring`.

## Verify and benchmark

```sh
python3 bench/run.py --stacks java-spring --profile quick   # from the repo root
```

The report must show **pass** for the seed checksum (VER-1) and API parity
(VER-2). Both passed on the first run.
