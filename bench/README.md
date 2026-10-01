# Benchmark suite

Run every backend in this repo, or just the ones you care about, under identical
conditions on your own machine. You get a report per backend, plus a consolidated
comparison, as Markdown and as self-contained HTML files you can share.

```sh
python3 bench/run.py --list                       # registered stacks, and whether their tools are installed
python3 bench/run.py                              # every stack, standard profile (~6 min per stack)
python3 bench/run.py --stacks go,rust             # only these stacks
python3 bench/run.py --profile quick              # smoke run (~3 min per stack)
open results/summary.html                         # the comparison; results/<stack>/report.html for detail
tail -f logs/bench.log                            # follow a run's progress (in another terminal)
```

## Requirements

- **Python 3.10+.** The runner uses only the standard library.
- **A Rust toolchain (`cargo`).** The load generator (`loadtest/`) and the
  reference server (`backend/rust/`) are Rust. The reference builds the shared
  dataset and answers the parity check.
- **The toolchain of each stack you want to run:** Go, .NET 10, Node 26, `uv` for
  Python, and Ruby 4.0 via `bundle` for Rails. A stack whose tools are missing is
  skipped, and the reports say so.
- **macOS or Linux.** On Windows, use WSL.

The reports in `results/` are committed as the published reference results
(from the maintainer's machine; see [`results/README.md`](../results/README.md)).
Commit a new run only when updating those. The dataset cache, working databases
and logs are git-ignored. To share your own run, send its `summary.html`.

## What a run does

1. **Records the machine.** CPU model, physical and logical cores (with
   performance/efficiency split on Apple Silicon), memory, OS and kernel, power
   source, and the repo commit. It's printed at the top of every report. The
   hostname is not recorded.
2. **Builds** the load generator and each selected stack, using the `build`
   commands from its manifest.
3. **Creates the dataset once:** 110,000 contacts made by the reference seeder,
   cached in `results/.cache/`. Each stack gets its own copy, so every stack
   starts from identical data.
4. **For each stack:**
   - **Seed checksum (VER-1).** Seeds 10,000 contacts into an empty database and
     compares a hash of the data with the one in `docs/requirements/`.
   - **Startup and idle memory.** Time from launch to the first `GET
     /api/health`, then memory at rest.
   - **Parity (VER-2).** Compares 71 responses with the reference server's,
     and runs 42 contract checks (framework-level statuses, ETags, gzip, the SPA
     fallback) against both servers.
   - **Single endpoints.** Six URLs, each hammered by 50 clients with full gzip
     responses.
   - **Simulated users.** Realistic users at increasing load levels. At each
     level it records requests/second, latency percentiles, errors, CPU cores
     used and memory. The ramp stops early once p99 passes `--stop-p99`
     (default 2 s), so slow stacks don't waste your time.
   - **Seeding speed.** Inserts the profile's contact count into an empty
     database.
5. **Writes the reports** (below): the backend's own report, replacing its
   previous results, then the summary across all backends.

## Profiles

| Profile | User levels | Measured per level | Seed | Use it for |
| --- | --- | --- | --- | --- |
| `quick` | 500, 1k, 2k | 15 s | 20k | checking a new stack works end to end |
| `standard` | 1k–6k in steps of 1k | 30 s | 100k | the numbers you publish |
| `full` | 500–8k | 60 s | 100k | low-noise runs on a quiet machine |

Override the levels with `--levels 1000,3000,5000`, and the core budget with
`--cores 8` (the default is 4). `--skip-{build,parity,conformance,endpoints,ramp,seed}`
leaves out a step.

## How it measures (and why)

- **Equal core budget.** Every server is started with its manifest's concurrency
  settings set to `--cores`, for example `GOMAXPROCS=4` or 4 worker processes.
  The load generator shares the machine, so close other heavy apps before a run.
- **Busy-machine check.** The load average is recorded at the start, before each
  stack, and at the end. If the 1-minute load is above one core's worth (or 10%
  of the cores, whichever is more), the runner prints a warning, and the reports
  flag the affected stacks as noisy. Browser tabs, dev servers, job workers and
  indexing all count.
- **Every process is counted.** Each server runs in its own session, so CPU and
  memory are summed over the whole process group, including all its workers.
  No per-stack process patterns are needed.
- **CPU** is the CPU-seconds the stack used during the measured window, divided
  by the window's length (1.0 = one full core). The same method is used on macOS
  and Linux. `ps %cpu` isn't used, because it means different things on the two
  systems.
- **Memory:**
  - on macOS, the physical footprint from `vmmap`
  - on Linux, the PSS from `/proc/<pid>/smaps_rollup`, with shared pages split
    between the processes that use them

  `vmmap` briefly pauses the process it inspects, so memory is read between load
  levels, never during one.
- **Capacity** is the number of users at which p99 latency crosses 100 ms,
  interpolated between the tested levels.

## Output

Each backend has one current result, and rerunning it replaces that result.
After every backend, the summary is rebuilt from all of their current results:

```
results/
  summary.html       compare every backend, with charts (self-contained, shareable)
  summary.md         the same tables as Markdown
  summary.json       every backend's current result
  <stack>/
    report.html      one backend in detail: latency percentiles, throughput, CPU
                     and memory charts, p99 by request type, single endpoints
    report.md
    result.json      measurements, plus the machine, profile, core budget, date and load
    ramp-<users>.json   raw load-generator output for each level
    server.log  build.log  seed.log  parity.log
```

Backends measured at different times each keep their own conditions. The
summary's last table shows when and how each one was measured, and warnings at
the top flag results that aren't comparable: a different machine, profile or
core budget, or a busy machine. Rerun those backends, and the summary updates.

To rebuild every report after changing `bench/suite/report.py`, run `python3
bench/report.py`. Nothing is re-measured. To keep a separate set of results,
for example from another machine, pass `--out <folder>` to `run.py` and
`report.py`.

## Docker mode

Every stack can also run from its Docker image, so the only thing you need
installed is Docker (plus Python 3.10+ and a Rust toolchain for the runner and
the load generator). The rules for the images are in
[`docs/requirements/07-containers.md`](../docs/requirements/07-containers.md).

```sh
python3 bench/run.py --mode docker                         # every stack, standard profile
python3 bench/run.py --mode docker --stacks go,rust --profile quick
python3 bench/run.py --mode docker --loadgen host          # load generator on the host instead
python3 bench/run.py --list --mode docker                  # which stacks have a docker block
python3 bench/run.py --mode docker --wait-quiet 20         # wait for a quiet machine before each stack
```

`--wait-quiet MIN` works in either mode: before each stack, the runner waits
up to MIN minutes for other programs to stay under the busy threshold. macOS
indexing and media analysis come in bursts, so checking once at the start
isn't enough for an hour-long run.

- **Results go to `results/docker/`**, never mixed with native results (CTR-15).
  Each report shows the mode, Docker version and VM size, and each stack's base
  image and SQLite version.
- **Each server runs with `--cpus=<cores>` and `--memory=4g`** (change it with
  `--memory`), plus its usual budget variables from `bench.json`. The database
  sits on a named volume, never a bind mount.
- **The load generator runs in a container on the Docker network by default**
  (`--loadgen network`). On macOS, `--loadgen host` sends every request through
  Docker Desktop's port forwarder, which capped Rust's cached endpoints at about
  45k req/s against 135–180k on the network. The forwarder is measured instead
  of the server.
- **CPU and memory come from the container's cgroup:** `cpu.stat` for CPU, and
  `memory.current` minus `inactive_file` for memory (page cache left out). On
  macOS the report also shows `docker_host_cores`: the host CPU of Docker
  Desktop's VM and port forwarder, which includes the container, the load
  generator (network mode) and Docker's own overhead.
- **The parity reference runs in Docker too,** so both sides pay the same
  overhead.
- **Throttling is recorded.** `--cpus` is enforced in 100 ms slices; a server
  that bursts past its quota is paused for the rest of the slice, which shows
  up as tail latency even when its average CPU is under the limit. Each level
  records `throttled_pct` (slices in which it was paused) and
  `throttled_ms_per_s`, and the report shows them next to CPU.
- **Native mode's budget is softer.** Natively, the budget is only the runtime's
  own settings, and some stacks spread past it (Python reached ~11 cores at
  4,000 users). In Docker, the cgroup holds every stack to exactly `--cpus`, so
  Docker numbers are the stricter 4-core comparison.
- **Requirements:** give Docker at least `cores + 2` CPUs (the runner warns
  otherwise), and stop other containers before a publishable run: they share the
  VM. Images must match the host's architecture; the runner refuses to benchmark
  under emulation.

`compose.yaml` at the repo root runs any stack by hand (`docker compose
--profile rust up --build`); the runner doesn't use it.

## Adding a backend

1. Implement it in `backend/<stack>/` from the spec in
   [`docs/requirements/`](../docs/requirements/README.md). The spec is written so
   you don't need to read the other backends.
2. Add `backend/<stack>/bench.json`:

   ```json
   {
     "name": "go",
     "label": "Go",
     "description": "net/http, mattn/go-sqlite3, klauspost gzip",
     "port": 7883,
     "requires": ["go"],
     "versions": ["go version"],
     "build": ["go build -tags sqlite_fts5 -o server ./cmd/server", "go build -tags sqlite_fts5 -o seed ./cmd/seed"],
     "start": "./server",
     "seed": "./seed {count}",
     "env": {"BIND_ADDR": "127.0.0.1:{port}", "GOMAXPROCS": "{cores}", "DB_READERS": "{cores}"},
     "concurrency": "1 process, GOMAXPROCS={cores}, {cores} read connections"
   }
   ```

   | Field | Meaning |
   | --- | --- |
   | `name`, `label` | unique id (used in paths and `--stacks`) and display name |
   | `description` | one line: framework, driver, notable libraries |
   | `port` | the stack's port, from `docs/requirements/README.md` |
   | `requires` | tools that must be on `PATH`; if any are missing, the stack is skipped |
   | `versions` | commands whose first output line goes in the report |
   | `build` | commands run in the stack folder before benchmarking |
   | `start` | runs the server in the foreground |
   | `seed` | runs the seeder; `{count}` is replaced with the number of contacts |
   | `env` | extra environment; `{port}` and `{cores}` are replaced |
   | `concurrency` | how the core budget is applied, shown in the report |

   The runner always sets `DATABASE_PATH`, and runs commands in the stack folder.
   A folder with several variants, like `backend/rails/`, can hold a JSON list of
   manifests.
3. Check it: `python3 bench/run.py --stacks <stack> --profile quick`. The report
   must show **pass** for both the seed checksum and API parity.
4. Run `standard` on as many stacks as you can, and share `summary.html`.
