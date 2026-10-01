# Developer guide

From a fresh clone to benchmarking stacks and tuning them with Claude. Docker
is the default way to run everything; running natively is covered after.

## 1. Quick start (Docker, ~10 minutes)

You need **Docker** (Desktop or Engine, with at least 6 CPUs and 8 GB given to
it), **Python 3.10+** and **git**. Nothing else: every stack and the load
generator build inside containers.

```sh
git clone git@github.com:webdz9r/stack-benchmark.git && cd stack-benchmark

# Run one stack with the UI, and fill it with fake contacts
docker compose --profile rust up --build -d               # http://127.0.0.1:7878
docker compose --profile rust run --rm rust seed 110000
docker compose --profile rust down                        # add -v to delete its data

# Benchmark two stacks (first run builds the images: a few minutes)
python3 bench/run.py --stacks rust,go --profile quick
open results/summary.html                                 # or results/summary.md
```

That's the whole loop: run a stack, benchmark it, read the report.

## 2. Everyday commands

```sh
python3 bench/run.py --list                     # every stack, port, and whether it can run
python3 bench/run.py                            # every stack, standard profile (~6 min each, ~1 h total)
python3 bench/run.py --stacks python            # one stack
python3 bench/run.py --profile quick            # short smoke run (~3 min per stack)
python3 bench/run.py --wait-quiet 20            # wait up to 20 min for a quiet machine before each stack
python3 bench/run.py --cores 2 --memory 2g      # a different budget per server
python3 bench/run.py --out /tmp/try-a           # keep a run separate (for A/B comparisons)
python3 bench/report.py                         # rebuild reports from the JSON, nothing re-measured
tail -f logs/bench.log                          # follow a running benchmark

docker compose --profile all up --build -d      # every stack at once, each on its port
python3 bench/parity.py http://127.0.0.1:7883/api   # check a running stack against Rust on :7878
```

| Stack | Port | Compose profile |
| --- | --- | --- |
| Rust (reference) | 7878 | `rust` |
| Python | 7879 | `python` |
| Node | 7880 | `node` |
| Rails / Rails + ActiveRecord | 7881 / 7882 | `rails` / `rails-ar` |
| Go | 7883 | `go` |
| C# | 7884 | `csharp` |
| C | 7885 | `c` |
| Java (Spring Boot) | 7886 | `java-spring` |

**Before a run you want to keep:** close heavy apps, stop other containers
(they share Docker's VM; the runner lists any it finds), and use
`--wait-quiet`. Every report says whether other programs were busy while it ran;
don't trust flagged numbers. On macOS, Spotlight and Photos analysis start on
their own while the machine looks idle.

## 3. Reading the results

`results/summary.html` compares every stack; `results/<stack>/report.html` has
the detail. The numbers that matter most:

- **Capacity:** simulated users at which p99 latency reaches 100 ms. Users act
  every ~3 s like the real UI (browse, search as they type, open, edit).
- **p99 by user level**, and **p99 by request type**. If every request type has
  the same p99, everything is waiting in one queue (a pool, a lock).
- **CPU cores** used, and in Docker **throttled %**: how often the 4-CPU quota
  paused the server.
- **Single-endpoint throughput** (50 clients, no pauses): raw speed per request
  type, which tells slow queries apart from too many queries.
- **Memory**, startup time and seeding speed.

Each report starts with the machine specs and how it was run, because results
from different machines, profiles or modes aren't comparable (the summary
warns when they're mixed).

## 4. Running natively

`--mode native` runs each stack with its own toolchain on your machine and
writes to `results/native/`. It's how the stacks were developed, and it shows
what a runtime does without a container limit. Install what you need:

| Stack | Toolchain |
| --- | --- |
| Rust (also the load generator and the parity reference) | `rustup` / Homebrew `rust` |
| Go | Go 1.27 |
| C# | .NET 10 SDK |
| C | C compiler, `make`, `pkg-config`, libmicrohttpd, yyjson |
| Java | JDK 27 + Maven |
| Node | Node 26 |
| Python | `uv` (it installs Python 3.14) |
| Rails | Ruby 4.0.1 (rbenv) and `bundle` |

```sh
python3 bench/run.py --list --mode native       # which toolchains are installed
python3 bench/run.py --mode native --stacks rust,go

# Develop against a stack by hand: the reference server plus the hot-reload UI
cd backend/rust && cargo run --release --bin seed -- 110000 && cargo run --release
cd frontend && npm install && npm run dev        # :5173, proxies /api to :7878 (native or Docker)
```

Each `backend/<stack>/README.md` has the stack's native commands, settings and
quirks. Missing toolchains just skip that stack.

## 5. How it fits together

- **`docs/requirements/`** is the spec every backend implements: API, schema,
  SQL, SQLite tuning, cache, gzip, seeder, verification. Backends are written
  from it, not from each other.
- **`backend/<stack>/`** holds the code, a `Dockerfile` (rules in
  [07-containers.md](docs/requirements/07-containers.md)) and a `bench.json`
  manifest: how to build, start and seed it, and the env that applies the core
  budget.
- **`bench/run.py`** builds each stack, checks its seed data is byte-identical
  (VER-1), compares 71 responses against the Rust reference plus 42 contract
  checks (VER-2), runs single endpoints and a ramp of simulated users, and
  writes reports.
- **`compose.yaml`** is generated from the `bench.json` files, for running
  stacks by hand; the runner drives Docker directly.
- **`docs/optimizing.md`** is the method for finding a stack's bottleneck, and
  each stack's README has an **Optimizing** section with what was tried.

## 6. Working with Claude

The repo is set up for Claude Code. Start it from the repo root: it reads
[`CLAUDE.md`](CLAUDE.md), which carries the project rules, the doc map and the
benchmarking pitfalls, so you can ask for work in plain terms.

**Add a backend:**

> Add a Kotlin + Ktor backend in `backend/kotlin-ktor/` on the next free port.
> Build it from `docs/requirements/` only. Include a Dockerfile per
> 07-containers.md and a `bench.json`, pass the seed checksum and parity, and run
> the quick profile.

**Optimize a stack:**

> Optimize the Node backend. Follow `docs/optimizing.md`: reproduce with the
> full ramp, compare single-endpoint throughput, probe the read pool and the
> cache, change one thing at a time, and record what helped and what didn't in
> its README.

**Investigate a result:**

> Java's p99 jumps at 5,000 users in Docker but not natively. Find out why, and
> tell me what you'd change before changing anything.

What makes it work well:
- **Ask for evidence.** Temporary probes (time waiting for a connection against
  time running the query, cache misses, throttling) found most bottlenecks in one
  run.
- **One change at a time, A/B against the full ramp**, with `--out` folders,
  and repeat close calls: noise at high load can be ±40 ms.
- **The checks are the definition of done.** A change that breaks parity or the
  seed checksum isn't a speed-up.
- **Have it write the lessons down** in the stack's README and, when they apply
  to every stack, in the spec, so the next session starts where this one ended.
- **Watch the machine.** If a run is flagged busy, rerun it rather than tuning
  against noise.

## 7. Tuning your own stack for deployment

The same harness answers deployment questions, because Docker mode models how
a container platform (Kubernetes, ECS, Fly, Cloud Run) limits your server:
`--cores` is the CPU limit and `--memory` the memory limit.

- **Size instances by capacity per core.** Run a stack at `--cores 2`, `4` and
  `8` (`--out` a folder each). Capacity rarely scales linearly; the curve tells
  you whether more, smaller instances beat fewer, bigger ones.
- **Watch throttling before raising limits.** A high throttled % with average
  CPU under the limit means bursts: GC, JIT or helper threads. Fix it by
  matching the runtime to the limit (`GOMAXPROCS`, worker and thread counts,
  `-XX:ActiveProcessorCount`, `DOTNET_PROCESSOR_COUNT`), choosing a calmer GC
  (Java's Parallel GC beat G1 here), or running with a CPU request and no hard
  limit.
- **Set memory limits from the reports.** Use peak memory under load plus
  headroom, not idle memory. JVM and .NET heaps size themselves from the
  container limit, so re-measure after changing it.
- **A/B runtime settings without touching code.** Change the `env` in a stack's
  `bench.json` (readers, workers, GC flags such as `JAVA_OPTS`), run it with
  `--out`, and compare reports. Keep what moves p99 and capacity, and record it.
- **Check your database driver.** Several stacks here lost half their capacity
  to a SQLite build with global locks. `PRAGMA compile_options` (or your
  driver's equivalent build info) is worth a look in any stack.
- **Measure on the hardware you deploy to.** On macOS, Docker runs in a VM.
  For numbers close to production, run the same commands on a Linux box with
  the same CPU class as your servers.
- **Bring your own app.** The method transfers: write down the contract (API,
  data, limits), give the implementation a parity check and a realistic load
  generator, then let Claude iterate on configuration with the checks as
  guardrails.
