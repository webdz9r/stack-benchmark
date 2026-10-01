# Optimizing a stack

How we found and fixed the bottlenecks in each backend, so the next round
starts from the method rather than from guesses. Stack-specific findings are
in each `backend/<stack>/README.md` under **Optimizing**.

The rules in the spec still apply: a speed-up must keep parity (VER-2) and the
seed checksum (VER-1), and it must not do less work than the other stacks.

## The method

1. **Reproduce it outside the suite.** Copy the benchmark dataset and run the
   server by hand with its 4-core settings from `bench.json`:

   ```sh
   sqlite3 results/.cache/dataset-110000.db ".backup /tmp/trial.db"
   DATABASE_PATH=/tmp/trial.db <stack env> <start command> &
   for u in 1000 2000 3000 4000 5000; do
     loadtest/target/release/loadtest url=http://127.0.0.1:<port> users=$u think=3000 warmup=10 duration=30 edits=5
   done
   ```

   Run the **whole ramp** against one server process, as the suite does. Some
   problems only appear after a few minutes of uptime: C# looked fine at 4,000
   users from a fresh start (68 ms) and failed after the ramp (515 ms), once
   its cache had filled.

2. **Ask whether queries are slow or there are too many of them.** Compare
   single-endpoint throughput with other stacks:

   ```sh
   loadtest/target/release/loadtest url=http://127.0.0.1:<port> endpoint="/contacts?limit=60&offset=50000" users=32 think=0 duration=10
   ```

   If a stack matches the others here but loses under the mixed load, the
   problem is the cache, the process model or contention, not the SQL.

3. **Look at p99 by request type** (`results/<stack>/result.json`,
   `ramp[].result.kinds`). If every read type has the same p99, even cache hits
   like `tags`, then everything is waiting in one shared queue. Rust showed 118 ms
   for every read type while writes took 8 ms: that pointed at the read pool.

4. **Measure the queue, then the work.** Add a temporary probe around the
   database read path that logs, once a second, the time spent waiting for a
   connection against the time spent running the query. Then count cache
   calls and misses. These two probes found most of the problems below. Remove
   them before benchmarking.

5. **Change one thing, rerun the same trial**, and keep what moved p99. Write
   down what didn't help as well, in the stack's README.

6. **Record it with the suite:** `python3 bench/run.py --stacks <stack>`.

## Check these first

These were real bottlenecks in more than one stack.

- **SQLite's global locks.** Run `PRAGMA compile_options` through the stack's
  own driver (not the `sqlite3` CLI, which is a different build):
  - no `DEFAULT_MEMSTATUS=0` means memory statistics are on, and every
    malloc/free takes a process-wide mutex;
  - `ENABLE_MEMORY_MANAGEMENT` means all connections share one page cache
    behind a global mutex.

  Either one serializes reader *threads* in the same process (separate
  processes each have their own). Fixing it: compile flags (Rust, Go, C),
  `sqlite3_config(SQLITE_CONFIG_MEMSTATUS, 0)` at startup before SQLite
  initializes (C#, Python), or a driver built without them (Node). This was
  the biggest single fix: C# went from ~3,250 users to 6,000+, Python from
  ~2,050 to ~3,050.
- **Optimization level.** Setting `CFLAGS`/`CGO_CFLAGS` usually replaces the
  default `-O2`. An unoptimized SQLite is about 3x slower (Go).
- **The cache hit rate.** The cache must admit every new entry and evict LRU
  (CACHE-5). A frequency-based policy (moka's default TinyLFU) rejects fresh
  entries after each generation bump. A stack that runs N processes has N
  caches and misses up to N times as often: Node's 4 cluster workers each
  missed ~58% of cached requests; C#'s single cache misses 18–24%.
- **Work on the event loop.** SQLite, gzip or JSON on the threads that serve
  connections hold up every other request behind them (ARCH-11). In Rust the
  pure-Rust gzip on the 4 async workers tripled p99 at 4,000 users.

## Run it in Docker too

Docker mode (`bench/run.py --mode docker`, see
[07-containers.md](requirements/07-containers.md)) is a second opinion worth
getting for every stack:

- **It enforces the core budget.** Natively, a stack's budget is only its own
  settings, and some spread past them: Python used ~11 cores at 4,000 users. In
  a container `--cpus=4` is a hard cap, so the Docker capacity is the honest
  4-core number (Python: ~2,050 users, against ~3,050 natively). Watch
  `throttled_pct` in Docker reports: bursty runtimes (GC, JIT, helper threads)
  get paused by the quota even when their average CPU is under it.
- **It runs on Linux and glibc.** That exposed a real bug in the C backend:
  `buf_take` returned unterminated memory for an empty buffer. macOS usually
  hands back zeroed memory, so the empty label still read as `""` and native
  parity passed; on Linux it returned garbage and parity failed.

## Tools that worked

| Question | Tool |
| --- | --- |
| Where does native CPU go? | macOS `sample <pid> 8 -file out.txt`, then read "Sort by top of stack" |
| Where does JS CPU go? | `node --cpu-prof --cpu-prof-dir=DIR` (one profile per thread; needs a clean exit, so add a temporary `SIGTERM` → `process.exit(0)`) |
| Is the read pool the queue? | a probe timing connection wait vs query time; Go: `db.Stats().WaitCount/WaitDuration` |
| Cache hit rate? | a probe counting calls and misses in the cache's compute path |
| Is it the GC? | .NET `GC.GetTotalPauseDuration()` and `GC.CollectionCount(n)` |
| Is the event loop saturated? | Node `performance.eventLoopUtilization()` |
| Is load spread across workers? | `lsof -a -p <pid> -iTCP -sTCP:ESTABLISHED` per worker, plus `ps -o pcpu` |
| Which SQLite is this? | `PRAGMA compile_options` and `sqlite_version()` through the stack's driver |

## Pitfalls

- **A profiler changes what it measures.** `sample` pauses the process: Go's
  p99 went from 37 ms to 335 ms while sampled. Use it to see *where* time
  goes, never *how much* latency there is.
- **Lock waits don't show up in CPU profiles.** A thread blocked on a mutex is
  idle to the profiler. Node's reader threads looked half idle while they were
  the bottleneck. On macOS, `__psynch_mutexwait` and `__psynch_mutexdrop` in a
  `sample` are the sign of contention.
- **More threads is rarely the answer.** More async workers (Rust) and a
  higher thread-pool minimum (C#) both made no difference or made things
  worse. Find the shared resource first.
- **The load generator shares one connection pool.** 3,000 simulated users
  use only ~70 keep-alive connections, and each stays with the worker that
  accepted it. Multi-process servers that share a listening socket (uvicorn,
  Puma) can end up with a few hot workers and some idle ones. Check the spread
  before blaming the code.
- **WAL commits reset other connections' page caches.** After any commit, every
  other connection discards its cached pages at its next read transaction.
  `btreeInitPage` and `__munmap` high in a profile under write load are this.
  It costs every stack the same, so it isn't a stack-specific problem.
- **Leftover processes skew the suite's busy check.** `dotnet build` leaves a
  compiler server running unless given `--disable-build-servers`; apps like
  Zoom, Spotlight or an App Store update easily use 1.5 cores.
- **macOS starts its own background work when the machine looks idle**, which
  is exactly when a benchmark runs. `mediaanalysisd` (Photos analysis) and
  `spotlightknowledged` / `corespotlightd` (Spotlight) together took ~3.3 cores during a Rails run
  and made it look 2x worse. When a run is flagged busy, check
  `top -o cpu -stats pid,cpu,command` before blaming the stack, and rerun
  once they've finished.
