# Backend Stack Benchmark

**One app, many backend stacks, one specification.**

This repo compares backend stacks on equal terms. Every backend implements the
same address-book API from the same written spec, over the same SQLite
database, with the same SQL, cache and compression. A load generator then
measures how many simulated users each one can serve, and a parity check
proves they all return the same responses.

Holding everything else constant leaves the runtime and the web framework as
the only variables: Rust vs Go vs Node vs Java, and so on. Along the way the repo
also became a record of *how* to make each stack fast, and of what doesn't
help.

## Why SQLite

Each backend embeds SQLite and reads a local database file. There's no
database server and no network hop between the app and its data.

That was a deliberate choice. With Postgres or MySQL, every request includes a
network round trip, and connection pools and server tuning would dominate the
results. With SQLite in the process, a query is a function call, so the numbers
show what the runtime itself costs:
- its HTTP stack
- JSON encoding
- threading or process model
- garbage collector
- how its SQLite driver is built

It also keeps the setup trivial: clone, build, run. The data is realistic,
though: 110,000 contacts with emails, phones, addresses and tags, full-text
search, and a database of about 90 MB.

## The app

An address book: browse a sorted list, jump through an A–Z index, search as you
type, open and edit contacts, tag and favorite them. The API has 13 routes (see
[03-api.md](docs/requirements/03-api.md)).

The **frontend** (`frontend/`, Vue 3 + Tailwind) is only there to demo the
functionality and to make the workload realistic. The load generator replays
the frontend's real request patterns. Every backend serves the built frontend,
so you can open any of them in a browser and use the same app.

## How it works

1. **One spec.** [`docs/requirements/`](docs/requirements/README.md) is a
   complete, language-neutral specification: architecture, schema and SQL,
   SQLite tuning, every route and error message, the cache and gzip rules, the
   data generator and how to verify a backend. **Backends are written from the
   spec, not by copying another backend.** `backend/rust/` is the reference
   implementation the spec was derived from.
2. **Shared schema.** Every backend applies the migrations in
   `backend/migrations/`, so schemas can't drift.
3. **Same work everywhere.** Every backend uses:
   - the same SQLite pragmas and one-writer / many-readers access
   - the same 64 MiB response cache (with ETags and read-your-writes)
   - gzip at level 6
   - a 4-core budget

   Without that, the comparison would mean nothing.
4. **Proof of sameness.** Each backend's seeder must produce byte-identical data
   (a checksum), and `bench/parity.py` compares 71 responses against the Rust
   server, plus 42 contract checks. Every stack passes all of them.
5. **Measurement.** `loadtest/` simulates users who browse, search as they type,
   open contacts and edit (5%), with ~3 s pauses. `bench/run.py` builds each
   stack, verifies it, ramps users until p99 latency passes 2 s, and writes
   reports to `results/` (Markdown and HTML, with charts).

## Results

Latest run on an Apple M5 Max. Each server is limited to 4 cores, and the load
generator runs on the same machine. **Capacity** is the number of simulated
users at which p99 latency reaches 100 ms.

| Stack | Capacity | Single contact | Uncached list page | Idle memory |
| --- | ---: | ---: | ---: | ---: |
| C# (ASP.NET Core) | ≥ 6,000 | 79,100 req/s | 21,500 req/s | 63 MB |
| C (libmicrohttpd) | ≥ 6,000 | 48,500 req/s | 25,500 req/s | 3 MB |
| Java (Spring Boot) | ~5,600 | 71,800 req/s | 17,500 req/s | 176 MB |
| Go (net/http) | ~5,500 | 55,400 req/s | 20,100 req/s | 4 MB |
| Rust (Axum) | ~5,100 | 71,500 req/s | 27,300 req/s | 3 MB |
| Node (Fastify) | ~5,050 | 38,800 req/s | 16,600 req/s | 102 MB |
| Python (FastAPI) | ~3,050 | 13,500 req/s | 2,800 req/s | 211 MB |
| Rails (direct SQL) | ~3,000 | 18,900 req/s | 11,200 req/s | 199 MB |
| Rails + ActiveRecord | ~1,950 | 5,700 req/s | 1,600 req/s | 199 MB |

**Full results:** [`results/summary.md`](results/summary.md) has latency by user
level, CPU, memory and single-endpoint throughput for every stack, with each
stack's report a click away (for example [Rust](results/rust/report.md)).
Every report starts with the machine specs. `summary.html` and each
`report.html` have charts; download them to view.

Read these as a comparison between stacks, not as server sizing: a cloud vCPU
is slower than an M5 core. The C# and Java runs were flagged because other
programs were busy during their low-user levels, so rerun them before quoting
them. Your own numbers are one command away (see [Running it](#running-it)).

## What we learned about performance

The first versions of most stacks had one avoidable bottleneck, and it was
rarely the language. Finding it changed the ranking more than the choice of
language did:

| Stack | Before | After | The bottleneck |
| --- | ---: | ---: | --- |
| Go | ~1,500 | ~5,500 | `CGO_CFLAGS` replaced the default `-O2`, so SQLite ran unoptimized |
| C# | ~3,250 | ≥ 6,000 | SQLite's memory statistics: a global lock on every malloc, serializing the reader threads |
| Node | ~2,900 | ~5,050 | 4 cluster processes meant 4 caches that each missed ~58% of the time. Now one process with reader threads, on a driver whose SQLite has no global locks |
| Rust | ~3,800 | ~5,100 | The cache policy (TinyLFU) rejected fresh entries, the bundled SQLite had a global page-cache lock, and slow gzip ran on the async threads |
| Python | ~2,050 | ~3,050 | The same memory-statistics lock, switched off at runtime before `import sqlite3` |
| Rails | ~2,250 | ~3,000 | The sqlite3 gem holds Ruby's GVL during queries, so extra threads per worker only added switching |
| Java | ~5,250 | ~5,600 | Parallel GC instead of G1, leaving the 4 cores to the query threads |
| C | resets at 6,000 | 0 errors | SQLite ran on the HTTP I/O threads, so bursts left nobody accepting connections |

The lessons that carry over to any project:

- **Check how your SQLite is compiled.** Prebuilt copies often take a
  process-wide lock on every allocation or page fetch, which quietly turns
  "4 reader threads" into one. `PRAGMA compile_options` tells you.
- **Cache hit rate beats raw speed.** A cache that rejects new entries, or
  several processes that each keep their own, can cost more than the language
  saves.
- **Keep blocking and CPU-heavy work off the threads that serve connections.**
  That applies to SQLite calls and gzip.
- **More threads is rarely the fix.** Find the shared resource first: a pool, a
  lock or a cache.
- **Measure carefully.** Profilers distort latency, lock waits don't show up in
  CPU profiles, and macOS's own background indexing can take 3+ cores in the
  middle of a run.

The full method, tools and pitfalls are in
[`docs/optimizing.md`](docs/optimizing.md). Each `backend/<stack>/README.md`
has an **Optimizing** section with what was tried there, including what didn't
help.

## Writing a backend with AI

Every backend here was written by Claude (Claude Code) from the spec, and the
repo is set up so the next one can be too. [`CLAUDE.md`](CLAUDE.md) gives the
assistant the project rules, the doc map and the benchmarking pitfalls. The spec
gives it everything it needs, and the checks tell it (and you) when it's done.

A typical request:

> Add a Kotlin + Ktor backend in `backend/kotlin-ktor/` on the next free port.
> Build it from `docs/requirements/` only, not from the other backends. Pass the
> seed checksum and parity check, add a `bench.json`, and run the quick
> benchmark profile.

The definition of done is the acceptance checklist in
[06-verification.md](docs/requirements/06-verification.md):
- **VER-1:** identical seed data
- **VER-2:** "71 identical, 0 mismatched; 42/42 contract checks passed"
- **VER-3:** a clean load test
- **VER-4/5/6:** registered with the suite, plus a README for the stack
- **VER-7:** compared against the existing stacks, with any large gap
  investigated

Because the checks are mechanical, you can trust the result without reading
every line.

## Optimizing with AI

Optimizing works the same way. Point Claude at one stack and the method:

> Optimize the Python backend. Follow `docs/optimizing.md`: reproduce outside
> the suite, compare single-endpoint throughput, probe the read pool and the
> cache, and change one thing at a time. Record what helped and what didn't in
> its README.

What made this work:
- **Ask for evidence, not guesses.** A temporary probe (wait time against query
  time, cache misses) found most bottlenecks in one run.
- **A/B one change at a time** against the full user ramp, and repeat close
  calls: run-to-run noise at high load can be ±40 ms.
- **Keep the machine quiet** while measuring. The suite flags runs where other
  programs were busy. Don't trust flagged numbers.
- **Write the lessons down**: in the stack's README, in `docs/optimizing.md`,
  and in the spec when they apply to every backend. That way the next session,
  human or AI, starts where the last one stopped.

## Running it

```sh
# Reference backend + UI
cd backend/rust
cargo run --release --bin seed -- 110000    # fake contacts
cargo run --release                         # API + built UI on http://127.0.0.1:7878

cd frontend && npm install && npm run build # build the UI the backends serve
npm run dev                                 # or hot-reload on :5173, proxying /api to :7878

# Benchmarks (from the repo root)
python3 bench/run.py --list                 # registered stacks; are their tools installed?
python3 bench/run.py --stacks go,rust --profile quick
python3 bench/run.py                        # every stack, standard profile (~6 min each)
open results/summary.html                   # comparison; results/<stack>/report.html for detail
tail -f logs/bench.log                      # follow a running benchmark
```

Each stack's build and run commands, settings and notes are in its README:
[Rust](backend/rust/README.md) · [Go](backend/go/README.md) ·
[C#](backend/csharp/README.md) · [C](backend/c/README.md) ·
[Java](backend/java-spring/README.md) · [Node](backend/node/README.md) ·
[Python](backend/python/README.md) · [Rails](backend/rails/README.md).
More on the suite in [`bench/README.md`](bench/README.md).

## Repository layout

```
backend/
  migrations/        shared schema, applied by every backend
  rust/              reference implementation (Axum)      :7878
  python/            FastAPI                               :7879
  node/              Fastify                               :7880
  rails/             Rails, direct SQL and ActiveRecord    :7881 / :7882
  go/                net/http                              :7883
  csharp/            ASP.NET Core                          :7884
  c/                 libmicrohttpd                         :7885
  java-spring/       Spring Boot                           :7886
frontend/            Vue 3 + Tailwind demo UI
loadtest/            simulated-user and single-endpoint load generator (Rust)
bench/               benchmark suite, report renderer, parity check
results/             published reference results (summary + one report per stack)
logs/                benchmark progress log (git-ignored)
docs/
  requirements/      the spec every backend is built from
  optimizing.md      how to find and fix a stack's bottlenecks
  plans/             what's planned next, e.g. running every stack in Docker
CLAUDE.md            instructions for AI assistants working in this repo
```
