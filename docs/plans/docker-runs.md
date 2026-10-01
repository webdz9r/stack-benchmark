# Plan: run stacks and benchmarks in Docker

Status: built on the `docker` branch · requirements in [07-containers.md](../requirements/07-containers.md)

## What was built, and where it differs from this plan

Phases 1–6 are implemented on the `docker` branch. The rules are in
[07-containers.md](../requirements/07-containers.md) (CTR-1..18), not in the
CTR list below, which is the original proposal. Changes from the plan:

- **Debian 13 (trixie)**, not 12 (bookworm): it's the current stable release,
  and every official image used has a trixie variant.
- **.NET 10 and JDK 27 have no official Debian-based image.** The runtime is
  installed from the vendor on `debian:trixie-slim` instead: Microsoft's
  `dotnet-install.sh` (ASP.NET Core runtime), and Eclipse Temurin 27 from
  Adoptium (JDK to build, JRE to run).
- **The SQLite version is a file, `/app/sqlite-version`**, written at build
  time, rather than an image label (labels can't be computed during a build).
  C# and Java gained a `sqlite-version` command to produce it.
- **The load generator defaults to the Docker network** (`--loadgen network`),
  not the host. On macOS, published ports go through Docker Desktop's port
  forwarder, which capped Rust's cached endpoints at ~45k req/s against
  135–180k on the network: the forwarder was being measured.
- **Phase 0 became a by-product** of the full runs: native and Docker results
  for every stack, side by side in the root README.
- Along the way, `backend/c/Makefile` got a fix for a race under `make -j` (two
  targets sharing one download rule), and Rails' Puma now reads `HOST`.

## Goal

Add a **Docker mode** alongside today's native mode. Any stack can then be built,
started, seeded and benchmarked from a container, without installing its
toolchain. Native mode stays the default and is unchanged.

Why:

- **Reproducibility.** `docker compose up` runs every stack. No rbenv, uv,
  Homebrew libraries or pinned Node versions needed.
- **Configuration kept apart from code.** Each stack's runtime tuning (base
  image, compiler flags, JIT, allocator, worker model) lives in one Dockerfile
  anyone can review. The shared budget (CPU, memory, network, volumes) lives in
  one compose file.
- **Enforced budget.** cgroups apply `--cpus` and `--memory` the same way to
  every stack, backing up the per-runtime env vars (ARCH-10).
- **Credible Linux numbers.** On a Linux host, containers cost close to nothing,
  so a dedicated Linux box can produce the published numbers.

Non-goals: changing the API, the spec's behaviour or the native workflow;
deploying to production; Kubernetes.

## Principles

1. **Never mix native and Docker numbers.** Every result records its `mode`. The
   summary warns when backends in one report were measured in different modes,
   the same way it already warns about a different machine or profile.
2. **The Dockerfile is part of what's being benchmarked.** Rules for what it may
   contain go in the spec (phase 1), so tuning stays fair.
3. **One base family for every stack:** Debian slim (glibc). No Alpine: musl's
   memory allocator is noticeably slower under load for Rust, Python and Node,
   and that would show up as a language difference.
4. **The budget lives in one place.** Dockerfiles hold build-time choices only.
   CPU and memory limits and the `{cores}` env vars come from the runner or the
   compose file, so a Dockerfile can't override them.
5. **The database lives on a named volume, never a bind mount.** On macOS, bind
   mounts cross the VM boundary on every WAL write and fsync.

## Phase 0: measure the overhead first (half a day)

Before building anything, check whether this is worth doing on a Mac.

- Hand-write Dockerfiles for **Rust** (fastest) and **Rails** (slowest).
- Run each natively and in Docker (named volume, `--cpus=4`) with the same
  commands: the six single endpoints and a `quick` ramp.
- Record the difference in throughput, p99 and CPU. Test both published ports
  and running `loadtest` inside the same Docker network.

**Decision point.** If Docker on macOS narrows the Rust vs. Rails gap by more
than about 10%, document Docker mode as "for reproducibility and Linux hosts,
not for published macOS numbers". Either way, keep going: the portability win
doesn't depend on this.

## Phase 1: spec changes

Add `docs/requirements/07-containers.md` and link it from the requirements
README. New requirement IDs:

- **CTR-1** Each stack MUST have `backend/<stack>/Dockerfile`, built with the
  **repo root** as its build context, so it can copy `backend/migrations/` and
  `frontend/dist/`.
- **CTR-2** The runtime image MUST be based on `debian:<release>-slim`, or on an
  official language image built on it (e.g. `rust:<v>-slim-bookworm` for the build
  stage, `ruby:<v>-slim-bookworm`). All stacks use the same Debian release.
- **CTR-3** Multi-stage builds: the toolchain stays in the build stage, and the
  runtime stage holds only the server, the seeder and their runtime dependencies.
- **CTR-4** Allowed tuning: the production-mode settings the stack already
  documents natively (YJIT, `-O2`, release builds, `RAILS_ENV=production`). New
  tuning, such as a custom allocator (jemalloc, mimalloc) or PGO, MUST be
  applied to native mode too, noted in the stack README, and open to every stack.
- **CTR-5** Dockerfiles MUST NOT set concurrency or budget env vars (`GOMAXPROCS`,
  `WORKERS`, `DB_READERS`, ...). Those come from the manifest at runtime.
- **CTR-6** The container MUST listen on `0.0.0.0` inside the container, set
  through `BIND_ADDR` / `PORT` / `HOST` (see ARCH-6 changes below). The native
  default stays loopback.
- **CTR-7** The image MUST contain the same seeder and pass VER-1 when run with
  `docker run ... seed 10000`.
- **CTR-8** Each stack MUST record the SQLite version it uses (`select
  sqlite_version()`), in the image label `org.address-book.sqlite` or in its
  health output. Stacks that link the system SQLite get the Debian version, and
  the report shows it so drift is visible.

Changes to existing docs:

- **ARCH-6:** say that the bind host must also be configurable (for containers),
  while the default stays `127.0.0.1`.
- **06-verification.md:** add a Docker section to the acceptance checklist: VER-1
  and VER-2 pass in Docker mode.

## Phase 2: make every stack container-ready

Small code changes, before any Dockerfile:

| Stack | Change |
| --- | --- |
| rails | `config/puma.rb` hardcodes `bind "tcp://127.0.0.1:..."`: read a `HOST` env var, defaulting to `127.0.0.1` |
| node | already reads `HOST`; nothing to do |
| python | `start` passes `--host 127.0.0.1`; the Docker start command passes `--host 0.0.0.0` |
| rust, go, csharp, c | already read `BIND_ADDR`; nothing to do |

Check every stack for paths relative to the stack folder (`DATABASE_PATH`,
`STATIC_DIR`, the migrations folder). In the image, place things so the same
relative layout works: `/app/backend/<stack>/`, `/app/backend/migrations/`,
`/app/frontend/dist/`, with the working directory set to `/app/backend/<stack>`.
Then no env var needs to change between modes.

## Phase 3: Dockerfiles

One per stack, following CTR-1..8. Build them in order of risk:

1. **rust**: `rust:slim-bookworm` build stage, `debian:bookworm-slim` runtime.
2. **go**: build with `-tags sqlite_fts5` and the manifest's `CGO_CFLAGS`, then a
   slim runtime.
3. **c**: build stage installs `libmicrohttpd-dev`, `libyyjson-dev` (or builds
   yyjson from source) and `zlib1g-dev`. The runtime stage installs only the
   runtime libraries.
4. **csharp**: `mcr.microsoft.com/dotnet/sdk:10.0` build, then
   `aspnet:10.0-bookworm-slim` runtime.
5. **node**: `node:26-bookworm-slim`, with `npm ci --omit=dev`.
6. **python**: `python:<v>-slim-bookworm` with `uv sync --frozen`. The venv is
   built inside the image, so the "moving the folder breaks `.venv`" problem goes
   away.
7. **rails**: `ruby:4.0.1-slim-bookworm`, `bundle install` with the deployment
   and without-development settings, YJIT on. One image serves both `rails` and
   `rails-ar`; `RAILS_DATA` picks the variant.

Also:

- **`frontend/Dockerfile`** or a shared build stage that runs `npm ci && npm run
  build`, whose `dist/` the stack images copy in. This way the SPA contract checks
  in VER-2 behave the same.
- **`loadtest/Dockerfile`**, so the load generator can run inside the Docker
  network (see phase 5).
- A root **`.dockerignore`**: `target/`, `node_modules/`, `.venv/`, `data/`,
  `results/`, `logs/`, `bin/`, `obj/`, `.git/`.

Check: for each stack, run `docker run` with the seeder into a throwaway volume,
then compute the VER-1 checksum. Then start the container and run
`python3 bench/parity.py http://127.0.0.1:<port>/api` against it.

## Phase 4: `compose.yaml` at the repo root

For people who just want to run things:

```yaml
x-budget: &budget
  cpus: "4"
  mem_limit: 2g

services:
  rust:
    build: { context: ., dockerfile: backend/rust/Dockerfile }
    ports: ["127.0.0.1:7878:7878"]
    environment: { BIND_ADDR: "0.0.0.0:7878", TOKIO_WORKER_THREADS: "4", DB_READERS: "4" }
    volumes: ["rust-data:/app/backend/rust/data"]
    <<: *budget
  # ... one service per stack, same ports as native
```

- One named volume per stack.
- Services sit behind `profiles:` so `docker compose --profile go up` starts one
  stack.
- `docker compose run --rm rust seed 110000` seeds, if the entrypoint is a small
  script that dispatches `serve` or `seed N`.
- Document in the root README under "Running it", in a new "With Docker"
  subsection.

The compose file is for manual use. The benchmark runner drives `docker`
directly (phase 5), so its budget always follows `--cores`.

## Phase 5: benchmark runner support

### Manifest

Add an optional `docker` block to each `bench.json`, so native fields stay
unchanged:

```json
"docker": {
  "dockerfile": "Dockerfile",
  "start": "serve",
  "seed": "seed {count}",
  "env": { "BIND_ADDR": "0.0.0.0:{port}" }
}
```

`docker.env` is merged over `env`, so the `{cores}` settings are shared. A stack
without a `docker` block is skipped in Docker mode, with the reason recorded.

### CLI

```sh
python3 bench/run.py --mode docker --stacks rust,go --profile quick
python3 bench/run.py --mode docker --loadgen host      # default: loadtest on the host, via published ports
python3 bench/run.py --mode docker --loadgen network   # loadtest in a container on the same network
```

### Code changes (`bench/suite/`)

- **`stacks.py`:** parse the `docker` block. In Docker mode, `missing_tools()`
  checks only for `docker`, which makes `--list` show every stack as ready.
- **New `containers.py`:** a `ContainerServer` with the same interface as
  `procs.Server` (`pids()`, `alive()`, `stop()`), plus:
  - `build(stack)`: `docker build -f backend/<stack>/Dockerfile -t
    address-book-<stack> .` with the build log in `build.log`
  - `start(stack, volume, env, cores)`: `docker run -d --name ab-<stack>
    --cpus=<cores> --memory=<limit> -p 127.0.0.1:<port>:<port> -v <volume>:...`
  - `cpu_seconds()`: read `cpu.stat` `usage_usec` from the container's cgroup
    (`docker exec ... cat /sys/fs/cgroup/cpu.stat`). This works on macOS too,
    since it reads inside the VM, and avoids `docker stats` sampling noise.
  - `memory_mb()`: `memory.current` minus `inactive_file` from `memory.stat`.
    That leaves out reclaimable page cache and comes closest to the native
    footprint. Record both raw values in `result.json`.
- **Datasets:** load the cached dataset into the stack's volume with a throwaway
  container that holds the host file read-only and runs SQLite `.backup` into the
  volume. Don't use `cp`, per the repo rule.
- **VER-1:** run the seeder container against a fresh volume, then copy the file
  out with `docker cp` (after the container stops) and hash it with the existing
  `seed_checksum()`.
- **Parity:** the reference server runs in the **same mode** as the stack under
  test, so both pay the same overhead. In Docker mode, build the reference image
  first.
- **Busy-machine check:** in Docker mode on macOS, also report the Docker VM's
  own CPU use during the idle sample. Stacks run inside the VM, so other
  containers count as background load.
- **`result.json`:** add `mode`, `docker_version`, the image digest, base image,
  SQLite version (CTR-8), `loadgen` placement, and on macOS the Docker VM's CPU
  and memory allocation (from `docker info`).

### Reports (`bench/suite/report.py`)

- Show the mode in the header and in the "how it was measured" table.
- Warn when backends in one summary were measured in different modes or with
  different `loadgen` placement.
- Keep the results separate by default: Docker runs write to
  `results/docker/` unless `--out` says otherwise, so a Docker run doesn't
  replace a stack's native result.

## Phase 6: docs

- `bench/README.md`: a "Docker mode" section covering requirements (Docker
  Desktop or Engine, VM given at least cores + 2 CPUs), the flags, how CPU and
  memory are measured in containers, and the macOS caveat from phase 0.
- Root `README.md`: "With Docker" under "Running it". Any Docker-mode numbers
  get their own table, clearly labelled, never merged into the native one.
- `CLAUDE.md`: add the Docker benchmarking rules (no bind mounts for the DB, one
  base family, don't mix modes, keep CTR-5).
- Each stack README: a two-line "Docker" section (VER-6).

## Order of work and checks

| Step | Done when |
| --- | --- |
| 0. Overhead spike | Native vs. Docker numbers for Rust and Rails written down; macOS guidance decided |
| 1. Spec | `07-containers.md` merged; ARCH-6 and the checklist updated |
| 2. Bind-host fixes | Native parity still `71 identical, 0 mismatched; 42/42` for every stack |
| 3. Dockerfiles | Every image passes VER-1 and VER-2 in a container |
| 4. Compose | `docker compose --profile <stack> up` serves the UI for every stack |
| 5. Runner | `run.py --mode docker --profile quick` passes for all stacks; native mode output unchanged |
| 6. Docs | READMEs updated; first full Docker `standard` run done on a quiet machine |

## Risks and open questions

- **macOS overhead** may shrink the differences between stacks (phase 0 decides
  how Docker mode is positioned). On Linux, use `--network host` or run the load
  generator in the same network to avoid the userland proxy.
- **Runtimes that ignore cgroup limits.** Recent Go and .NET read the CPU quota.
  Node, Python and Ruby use explicit worker counts from the manifest. Log each
  runtime's detected CPU count at startup to confirm.
- **SQLite drift** between the bundled builds (Rust, C, Node, maybe C#) and
  Debian's system SQLite (Python, Rails, Go via cgo, if not bundled). CTR-8
  makes it visible. Pinning a single version everywhere is a possible follow-up.
- **Image size and build time**, especially Rails and .NET. Use BuildKit cache
  mounts for cargo, go, npm, uv and bundle caches.
- **Apple Silicon vs. x86.** Build native-arch images only; never benchmark under
  emulation (`--platform linux/amd64` on an ARM Mac). The runner should refuse if
  the image arch differs from the host's.
- **Open question:** should the Docker VM's resources be fixed (e.g. 8 CPUs,
  8 GB), so macOS Docker runs are comparable across machines? Proposed: record
  them, and warn if the VM has fewer than `cores + 2` CPUs.
