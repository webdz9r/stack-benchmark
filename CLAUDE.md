# CLAUDE.md

## What this repo is

A benchmark of backend stacks behind **one common interface**. Each stack in
`backend/<stack>/` implements the same address-book REST API over the same SQLite
database: same schema, same SQL, same SQLite tuning, same response cache, same
gzip. The same Vue frontend, load generator and parity check work against all of
them. That way, differences in the results come from the language runtime and
web framework, not from one stack doing less work.

It started as a single Rust + SQLite proof of concept. `backend/rust/` is still
the **reference implementation**. `README.md` explains the project and has
the latest results; full reports are in `results/`.

## Source of truth: `docs/requirements/`

`docs/requirements/` is the complete, language-neutral spec. **Implement or change
a backend from the spec, not by reading another backend's code.** Start with
`docs/requirements/README.md` and read the documents in order:

| Doc | Covers |
| --- | --- |
| `01-architecture.md` | process model, env vars, startup, one writer + read pool, static SPA, logging |
| `02-database.md` | migrations, the 8 pragmas, WAL checkpointing, FTS, the canonical SQL |
| `03-api.md` | all 13 routes, JSON shapes, validation order and exact error messages |
| `04-caching-and-http.md` | response cache, `X-Fresh`, ETags/304, gzip rules |
| `05-seeder.md` | the deterministic xorshift data generator, draw by draw |
| `06-verification.md` | seed checksum, parity check, benchmark integration, acceptance checklist |

Requirements have IDs (`API-12`, `DB-4`, `CACHE-10`): cite them in commits and
reviews. If the spec and `backend/rust/` disagree on anything the parity check
can see, Rust wins and the **spec gets fixed** in the same change.

Schema changes go in a new `backend/migrations/NNN_name.sql`, never an edit to an
applied one. Every stack reads that folder directly, so no stack keeps its own
copy of the schema.

## Documentation map

| Doc | Read it when |
| --- | --- |
| `README.md` | you need the project goal, why SQLite, the latest results, the performance lessons, or how to use Claude to write or optimize a backend |
| `DEVELOPER.md` | you need setup and run instructions (Docker first, native second), or the guide to tuning a deployment with this harness |
| `docs/requirements/` | you build or change a backend (the spec, above) |
| `docs/optimizing.md` | you tune a stack: the method, what to check first, profiling tools, measurement pitfalls |
| `backend/<stack>/README.md` | you work on that stack: its settings, deviations from the spec, and an **Optimizing** section with what was already found and tried |
| `bench/README.md` | you run the suite, change it, or register a stack (`bench.json` format) |
| `results/README.md` | you need the layout of benchmark output and how reports are rebuilt |
| `logs/README.md` | you follow or debug a benchmark run (`logs/bench.log`) |
| `docs/requirements/07-containers.md` | you write or change a stack's `Dockerfile`, or run anything in Docker mode |
| `compose.yaml` | you run a stack in Docker by hand; it's generated from the `bench.json` files, so regenerate it rather than editing it |
| `docs/plans/` | plans: `docker-runs.md` is how Docker mode was planned (now built); check a plan's status before acting on one |

Keep this map current: when you add a doc, add a row here.

## Layout and ports

```
backend/migrations/  shared schema (SQL files, tracked with PRAGMA user_version)
backend/rust/        7878  Rust, Axum, rusqlite (reference)
backend/python/      7879  FastAPI, uvicorn, sqlite3
backend/node/        7880  Fastify, better-sqlite3 on worker threads
backend/rails/       7881  Rails 8.1, Puma, sqlite3 gem (7882 with RAILS_DATA=activerecord)
backend/go/          7883  net/http, mattn/go-sqlite3
backend/csharp/      7884  ASP.NET Core minimal APIs, Microsoft.Data.Sqlite
backend/c/           7885  libmicrohttpd, SQLite amalgamation, yyjson, zlib
backend/java-spring/ 7886  Java, Spring Boot (Spring MVC on Tomcat), xerial sqlite-jdbc
frontend/            Vue 3 + Tailwind v4; `npm run dev` proxies /api to :7878
loadtest/            Rust load generator (simulated users, single endpoint)
bench/               benchmark suite: run.py, report.py, parity.py, suite/
results/             published reference results: summary.* plus one folder per backend (dataset, work DBs and logs git-ignored)
logs/                bench.log: progress of every benchmark run (git-ignored; tail -f it)
docs/requirements/   the spec
docs/optimizing.md   how to find and fix a stack's bottlenecks
docs/plans/          proposals not built yet
```

A new stack takes the next free port (7887 and up). Each stack has its own
database copy at `backend/<stack>/data/address-book.db`, which is git-ignored.

## Common commands

Run these from the repo root unless noted.

```sh
# Reference server (API + built UI)
cd backend/rust && cargo run --release                     # seed: cargo run --release --bin seed -- 110000

# Give another stack the same data as Rust (don't re-seed; Rust's DB may hold extra rows)
sqlite3 backend/rust/data/address-book.db ".backup backend/<stack>/data/address-book.db"

# Parity: 71 responses compared with the Rust server, plus 42 contract checks on both;
# must end "71 identical, 0 mismatched; 42/42 contract checks passed"
python3 bench/parity.py http://127.0.0.1:<port>/api

# Seed checksum (VER-1): must equal the hash in docs/requirements/06-verification.md
DATABASE_PATH=/tmp/seed-check.db <seeder> 10000
sqlite3 /tmp/seed-check.db < docs/requirements/seed-checksum.sql | shasum -a 256

# Load generator
cd loadtest && cargo build --release
./target/release/loadtest url=http://127.0.0.1:<port> users=2000 think=3000 duration=30 edits=5
./target/release/loadtest url=http://127.0.0.1:<port> endpoint="/contacts?limit=60" users=50 think=0 duration=8

# Benchmark suite (see bench/README.md): replaces results/<stack>/ and rebuilds results/summary.*
python3 bench/run.py --list                          # registered stacks, tools ready?
python3 bench/run.py --stacks go,rust --profile quick
python3 bench/run.py                                 # all stacks, standard profile (~6 min/stack)
python3 bench/report.py                              # re-render all reports from the JSON
tail -f logs/bench.log                               # follow a running benchmark

# The runner uses Docker by default (results/); --mode native uses local toolchains (results/native/)
python3 bench/run.py --mode native --stacks rust --profile quick
docker compose --profile rust up --build                 # run one stack by hand
```

Per-stack build and run commands, with each stack's 4-core settings, are in
each `backend/<stack>/README.md` and its `bench.json`. Some stack-specific points:
- **Go** needs `-tags sqlite_fts5` for FTS5.
- **Rails** runs with `RAILS_ENV=production SECRET_KEY_BASE_DUMMY=1 RUBY_YJIT_ENABLE=1`.
- **C#** runs with `dotnet bin/Release/net10.0/AddressBook.dll`, and its seeder is
  `... AddressBook.dll seed N`.
- **Java** runs through `backend/java-spring/run.sh` (seeder: `./run.sh seed N`).
  `/usr/bin/java` is a stub on macOS; the script uses `JAVA_HOME` or Homebrew's
  keg-only `openjdk`.

## Benchmarking rules (learned the hard way)

- **Equal budget.** Every stack runs on a 4-core budget:
  - `TOKIO_WORKER_THREADS=4 DB_READERS=4` (Rust)
  - `GOMAXPROCS=4` (Go)
  - `THREADS=4` (C)
  - `DOTNET_PROCESSOR_COUNT=4` (C#)
  - `JAVA_CPUS=4 DB_READERS=4` (Java: `-XX:ActiveProcessorCount=4`)
  - `DB_READERS=4` (Node: 4 reader threads in one process)
  - 4 workers (Python, Rails)

  Python's threads still spread past 4 cores, because sqlite3 and gzip release
  the GIL. Report that; don't hide it.
- **Compare numbers from the same run.** When a stack is added or changed, rerun
  `python3 bench/run.py` for all stacks rather than mixing new numbers with old
  ones. If you do mix them, say so in the README.
- **Keep the machine quiet** during a benchmark: no builds, seeding or other load
  tests, and ask the user to close heavy apps, since browser tabs, other dev
  servers and job workers skew everything. macOS's own `mediaanalysisd` and
  `spotlightknowledged` can take 3+ cores while the machine looks idle; check
  `top` when a run is flagged. The suite records the load average
  and flags busy runs in the reports. Don't publish flagged numbers.
- **Don't use `ab`** on these servers. It mishandles chunked gzip responses
  (false failures, lost keep-alive). Use `loadtest endpoint=...` instead.
- **Don't run `vmmap` during a load run.** It pauses the process while it
  inspects it and causes request errors. Measure memory between runs, and use
  `ps` for CPU during them.
- **`pgrep` patterns must match every worker process.** Uvicorn and Puma
  workers, for example, can run under a different command line from their
  parent. Check the process count before trusting memory or CPU numbers.
- **Look for measurement artifacts before concluding anything.** In this project:
  - the load generator once throttled itself with typing pauses
  - two search terms matched every seeded row
  - a leftover 365 MB WAL made reads 8x slower

  Sanity-check results that look surprisingly flat or surprisingly bad.
- **Check which SQLite you're running.** A prebuilt SQLite often has memory
  statistics (a global lock on every malloc) and sometimes
  `SQLITE_ENABLE_MEMORY_MANAGEMENT` (a global page-cache lock). Either one
  serializes reader threads: C# went from ~3,250 to 6,000+ users once it was
  switched off. `PRAGMA compile_options` shows the build (DB-2).
- **Cache staleness is part of the design.** Flushing the cache on every write
  collapsed its hit rate. Keep the 1 s published generation, and keep `X-Fresh`
  for read-your-writes (see `04-caching-and-http.md`).

## Docker rules

- **Never mix native and Docker numbers.** Docker runs write to
  `results/` (Docker, the default) and `results/native/`; the reports warn if a
  summary mixes modes (CTR-15).
- **One base family:** every runtime image is Debian 13 slim (glibc), never
  Alpine/musl (CTR-2). Where no official Debian image exists (.NET 10, JDK 27),
  install the vendor's build on `debian:trixie-slim`.
- **Dockerfiles hold build choices only.** Budget variables (`GOMAXPROCS`,
  `DB_READERS`, workers, ...) come from `bench.json` at run time (CTR-5), and
  tuning must match native mode (CTR-4).
- **Databases on named volumes, never bind mounts** (CTR-11).
- **Load generator on the Docker network** (the default). On macOS, published
  ports go through Docker Desktop's port forwarder, which caps fast endpoints.
- **Stop other containers** before a publishable Docker run; they share the VM.
  The runner lists them. Don't stop the user's containers yourself: ask.

## Optimizing a stack

Follow [`docs/optimizing.md`](docs/optimizing.md): reproduce outside the suite,
compare single-endpoint throughput, probe the read pool and the cache, change
one thing at a time. Each `backend/<stack>/README.md` has an **Optimizing**
section with what was already found and tried there; read it first, and add
to it.

## Adding a new stack

1. Read `docs/requirements/` in order. Create `backend/<stack>/` with the next
   free port.
2. Build the server and the seeder from the spec: canonical SQL, all pragmas,
   the checkpoint task, the cache policy, gzip level 6.
3. Pass **VER-1** (seed checksum), then **VER-2** (`71 identical, 0 mismatched; 42/42 contract checks passed`),
   then **VER-3** (a load-test smoke run without errors).
4. Add `backend/<stack>/bench.json` (the manifest: build, start and seed commands,
   port, and env that applies `{cores}`). Run `python3 bench/run.py --stacks
   <stack> --profile quick`; its report must show pass for the seed checksum and
   parity. Add it to `README.md` (results table, "Running it" links, layout) and write a
   short stack README (**VER-4/5/6**).
5. Work through the acceptance checklist in `06-verification.md`, including
   **VER-7**: compare with the existing stacks and investigate any large gap
   before accepting the numbers.

## Environment notes (macOS, zsh)

- **Toolchains:**
  - Ruby: rbenv, with 4.0.1 pinned in `backend/rails/.ruby-version`
  - Python: `uv`
  - Go and .NET 10: Homebrew
  - Java: Homebrew `openjdk` (27, keg-only) and `maven`
  - C: Homebrew `libmicrohttpd` and `yyjson`, with system zlib
  - Node 26
- **zoxide noise.** Shell commands print a "zoxide: detected a possible
  configuration issue" banner. It's harmless; `export _ZO_DOCTOR=0` silences it.
- **Don't use `ls` in scripted commands.** It's aliased to `eza`, and it has hung
  non-interactive shells here. Use `find` or `test -f` instead.
- **Don't name a zsh variable `path`.** It's tied to `$PATH`, and assigning to it
  breaks every later command in that shell.
- **Moving a stack folder** breaks Python's `.venv`, which contains absolute
  paths; recreate it with `uv sync`. Rust and Go need a rebuild.
- **`sqlite3` CLI:** use `".backup"` to copy a live database. Plain `cp` can
  catch it mid-write.
