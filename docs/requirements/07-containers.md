# 7. Containers (Docker mode)

Every stack can also be built, seeded, verified and benchmarked in a container,
without installing its toolchain. This is **Docker mode**, and it's the
default: `bench/run.py` runs stacks in Docker unless given `--mode native`, which
uses each stack's toolchain on the machine. The plan this came from is
[`docs/plans/docker-runs.md`](../plans/docker-runs.md).

The Dockerfile is part of what's being benchmarked, so these rules keep
containers as fair as the native setup: same base OS for every stack, same
budget, no extra tuning that native mode doesn't have.

## 1. Images

- **CTR-1** Each stack MUST have `backend/<stack>/Dockerfile`, built with the
  **repository root** as the build context (`docker build -f
  backend/<stack>/Dockerfile .`), so it can copy `backend/migrations/` and build
  `frontend/`. Variants that share a folder (Rails and Rails + ActiveRecord) share
  one image.
- **CTR-2** The runtime stage MUST be based on **`debian:trixie-slim`** (Debian 13,
  glibc), or on an official language image built on it (`node:26-trixie-slim`,
  `python:3.14-slim-trixie`, `ruby:4.0.1-slim-trixie`, ...). Where no official
  Debian-based image exists for the runtime version in use, install the vendor's
  own build on `debian:trixie-slim`: .NET through Microsoft's `dotnet-install.sh`,
  the JDK from Eclipse Temurin (Adoptium). MUST NOT use Alpine or another musl
  base: musl's allocator is slower under load and would show up as a language
  difference. Build stages MAY use any official image.
- **CTR-3** Multi-stage builds. The toolchain stays in the build stage; the
  runtime stage holds only the server, the seeder, the built frontend
  (`frontend/dist/`) and their runtime dependencies.
- **CTR-4** Tuning MUST match native mode: the production settings the stack
  already uses natively (release builds, `-O2`/`-O3`, YJIT, `RAILS_ENV=production`,
  the GC choice in `run.sh`, ...). New tuning, such as a custom allocator or PGO,
  MUST also be applied to native mode, noted in the stack README, and open to
  every stack.
- **CTR-5** A Dockerfile MUST NOT set concurrency or budget variables
  (`GOMAXPROCS`, `TOKIO_WORKER_THREADS`, `DB_READERS`, `WORKERS`,
  `WEB_CONCURRENCY`, `RAILS_MAX_THREADS`, `JAVA_CPUS`, `DOTNET_PROCESSOR_COUNT`,
  `THREADS`, `UVICORN_WORKERS`, ...). They come from the manifest at run time, so
  the budget is set in one place.
- **CTR-6** The image MUST lay files out like the repository, so the same
  relative defaults work in both modes: the stack in `/app/backend/<stack>/` (the
  working directory), migrations in `/app/backend/migrations/`, the frontend in
  `/app/frontend/dist/`. Data goes in `/app/backend/<stack>/data/`.
- **CTR-7** The image MUST record the SQLite version its server uses in
  `/app/sqlite-version` (one line, e.g. `3.53.2`), written at build time: by
  asking the driver (`select sqlite_version()`) where the runtime can, or from the
  bundled SQLite source otherwise. Stacks that link the system SQLite get
  Debian's version, and the report shows each stack's version so drift is
  visible.
- **CTR-8** Images MUST be built for the host's architecture. Benchmarks MUST NOT
  run under emulation (for example `linux/amd64` on an ARM Mac); the runner
  refuses.

## 2. Running a container

- **CTR-9** The entrypoint MUST accept two commands, from the image's own
  working directory:
  - `serve` (the default): start the server in the foreground
  - `seed <count>`: run the stack's seeder (SEED-1) into `DATABASE_PATH`, then exit
- **CTR-10** Inside the container the server MUST listen on `0.0.0.0`, set
  through the stack's normal variables (`BIND_ADDR`, `PORT`, `HOST`, ... per
  ARCH-6). The native default stays `127.0.0.1`.
- **CTR-11** The database MUST live on a **named Docker volume**, never a bind
  mount. On macOS a bind mount crosses the VM boundary on every WAL write and
  fsync, which would be measured as a stack difference.
- **CTR-12** The container's CPU and memory limits (`--cpus`, `--memory`) MUST be
  set by whatever starts it (the runner or `compose.yaml`), together with the
  stack's budget variables from its manifest. The cgroup limit backs up the
  runtime's own settings (ARCH-10); it doesn't replace them.
- **CTR-13** The image MAY run as root. It's a local benchmark target, never
  deployed, and root avoids volume ownership problems when the runner copies a
  dataset in.

## 3. Manifest

- **CTR-14** A stack opts in to Docker mode with a `docker` block in its
  `bench.json`:

  ```json
  "docker": {
    "start": "serve",
    "seed": "seed {count}",
    "env": { "BIND_ADDR": "0.0.0.0:{port}" }
  }
  ```

  `docker.env` is merged over the native `env`, so the `{cores}` budget is shared;
  it typically only changes the bind address (and anything else a container
  needs). Optional `"dockerfile"` overrides the default `Dockerfile` path, relative
  to the stack folder. A stack without a `docker` block is skipped in Docker mode,
  with the reason recorded.

## 4. Measuring in Docker mode

- **CTR-15** Native and Docker results MUST never be mixed. Every result records
  its `mode`. Docker runs write to `results/` and native runs to
  `results/native/` by default, so one never replaces the other, and the
  summary warns if one report contains both modes.
- **CTR-16** CPU MUST be measured from the container's cgroup (`cpu.stat`
  `usage_usec`), and memory as `memory.current` minus `inactive_file` from
  `memory.stat` (reclaimable page cache left out, which is closest to the native
  footprint). Both raw values are recorded.
- **CTR-17** The parity reference server MUST run in the same mode as the stack
  under test, so both pay the same overhead.
- **CTR-18** Each Docker result MUST record: Docker version, the image ID, the
  base image, the SQLite version (CTR-7), where the load generator ran
  (`host` or `network`), and on macOS the Docker VM's CPU and memory allocation.
  The runner warns if the VM has fewer than `cores + 2` CPUs, or if other
  containers are running (they share the VM with the stack under test).

## 5. Verification in Docker mode

A stack that supports Docker mode passes the same checks in a container:

- **VER-1** in Docker: `seed 10000` in the container, copied out of the volume,
  produces the expected checksum.
- **VER-2** in Docker: `bench/parity.py` against the container (published port)
  ends `71 identical, 0 mismatched; 42/42 contract checks passed`, with the
  reference also in a container.
- `python3 bench/run.py --stacks <stack> --profile quick` (Docker by default) passes
  both.
