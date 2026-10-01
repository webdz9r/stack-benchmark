"""Runs the benchmark for each selected stack and writes the results.

Two modes: native (the default: each stack's toolchain on this machine) and
docker (each stack's image, see docs/requirements/07-containers.md). The steps
are the same; only building, seeding and starting servers differ.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from . import containers, machine, procs, report
from .stacks import ROOT, Stack, fill

LOADTEST_DIR = ROOT / "loadtest"
LOADTEST = LOADTEST_DIR / "target" / "release" / "loadtest"
RESULTS = ROOT / "results"
LOG_FILE = ROOT / "logs" / "bench.log"
CACHE = RESULTS / ".cache"
WORK = RESULTS / ".work"
CHECKSUM_SQL = ROOT / "docs" / "requirements" / "seed-checksum.sql"
EXPECTED_CHECKSUM = "4757200eff847274560a4359166b3c6977b0fb45b0bd5f7286c11a53a91fc86a"

ENDPOINTS = [
    ("Single contact", "/contacts/77777"),
    ("List page 1 (uncached)", "/contacts?limit=60"),
    ("List page at offset 55,000", "/contacts?limit=60&offset=55000"),
    ("Search `smith` (cached)", "/contacts?limit=60&q=smith"),
    ("A–Z index (cached)", "/contacts/letters"),
    ("Stats (cached)", "/stats"),
]


@dataclass
class Profile:
    name: str
    endpoint_warmup: int
    endpoint_duration: int
    levels: list[int]
    ramp_warmup: int
    ramp_duration: int
    seed_count: int
    description: str


PROFILES = {
    "quick": Profile("quick", 2, 5, [500, 1000, 2000], 5, 15, 20_000,
                     "smoke test: short runs, 3 user levels (~3 min per stack)"),
    "standard": Profile("standard", 2, 8, [1000, 2000, 3000, 4000, 5000, 6000], 10, 30, 100_000,
                        "the published numbers: 6 user levels (~6 min per stack)"),
    "full": Profile("full", 3, 15, [500, 1000, 2000, 3000, 4000, 5000, 6000, 8000], 15, 60, 100_000,
                    "long, low-noise runs: 8 user levels (~15 min per stack)"),
}


@dataclass
class Options:
    profile: Profile
    cores: int = 4
    dataset: int = 110_000
    reference: str = "rust"
    stop_p99_ms: float = 2000.0
    build: bool = True
    parity: bool = True
    conformance: bool = True
    endpoints: bool = True
    ramp: bool = True
    seed: bool = True
    out: Path | None = None
    notes: str = ""
    think_ms: int = 3000
    edit_pct: int = 5
    endpoint_clients: int = 50
    wait_quiet: int = 0      # minutes to wait, before each stack, for other programs to go quiet
    mode: str = "native"     # or "docker"
    loadgen: str = "network"  # docker mode: "network" (a container on the network) or "host" (published ports)
    memory: str = "4g"       # docker mode: --memory per server container


def log(msg: str) -> None:
    """Print a progress line and append it to logs/bench.log (tail -f it to follow a run)."""
    line = f"[{dt.datetime.now():%H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def sh(cmd: str, cwd: Path, env: dict | None = None, log_file: Path | None = None,
       timeout: float = 1800) -> subprocess.CompletedProcess:
    out = subprocess.run(cmd, shell=True, cwd=cwd, env={**_base_env(), **(env or {})},
                         capture_output=True, text=True, timeout=timeout)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, "a") as f:
            f.write(f"$ {cmd}\n{out.stdout}{out.stderr}\n")
    return out


def _base_env() -> dict:
    import os
    return {**os.environ, "_ZO_DOCTOR": "0", "DOTNET_NOLOGO": "1", "DOTNET_CLI_TELEMETRY_OPTOUT": "1"}


# ---------------------------------------------------------------- setup

def build_loadtest(opts: Options) -> None:
    log("building loadtest")
    out = sh("cargo build --release --quiet", LOADTEST_DIR)
    if out.returncode != 0:
        raise SystemExit(f"loadtest build failed:\n{out.stderr}")
    if opts.mode == "docker" and opts.loadgen == "network":
        out = containers.docker("build", "-q", "-f", str(LOADTEST_DIR / "Dockerfile"), "-t",
                                containers.LOADTEST_IMAGE, str(ROOT), timeout=1800)
        if out.returncode != 0:
            raise SystemExit(f"loadtest image build failed:\n{out.stderr}")


def build_stack(stack: Stack, run_dir: Path, opts: Options) -> tuple[bool, float, str]:
    if opts.mode == "docker":
        return containers.build_image(stack, run_dir / stack.name / "build.log")
    started = time.monotonic()
    for cmd in stack.build:
        out = sh(cmd, stack.dir, log_file=run_dir / stack.name / "build.log")
        if out.returncode != 0:
            return False, time.monotonic() - started, f"`{cmd}` failed (see build.log)"
    return True, time.monotonic() - started, ""


def run_seeder(stack: Stack, count: int, db: Path | None, opts: Options, log_file: Path,
               tag: str) -> tuple[subprocess.CompletedProcess, float]:
    """Seed `count` contacts into `db` (None: discard the database). Returns output and wall time."""
    env = stack.environment(opts.mode, port=stack.port, cores=opts.cores)
    if opts.mode == "docker":
        return containers.seed(stack, count, env, db, log_file, volume=f"sb-{stack.name}-{tag}")
    target = db or WORK / f"{stack.name}-{tag}.db"
    _remove_db(target)
    started = time.monotonic()
    out = sh(fill(stack.seed, count=count), stack.dir, env={**env, "DATABASE_PATH": str(target)}, log_file=log_file)
    wall = time.monotonic() - started
    if db is None:
        _remove_db(target)
    return out, wall


def ensure_dataset(reference: Stack, count: int, opts: Options) -> Path:
    """Build the shared dataset once with the reference seeder, and reuse it."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"dataset-{count}.db"
    if path.exists():
        return path
    log(f"building the {count:,}-contact dataset with the {reference.label} seeder")
    tmp = CACHE / f"dataset-{count}.tmp.db"
    _remove_db(tmp)
    out, _ = run_seeder(reference, count, tmp, opts, WORK / "dataset-seed.log", "dataset")
    if out.returncode != 0 or not tmp.exists():
        raise SystemExit(f"dataset seeding failed:\n{out.stdout}{out.stderr}")
    _copy_db(tmp, path)
    _remove_db(tmp)
    return path


def _copy_db(src: Path, dst: Path) -> None:
    """Consistent copy with SQLite's online backup (safe even if src is in use)."""
    _remove_db(dst)
    a, b = sqlite3.connect(src), sqlite3.connect(dst)
    try:
        a.backup(b)
    finally:
        a.close()
        b.close()


def _remove_db(path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        Path(str(path) + suffix).unlink(missing_ok=True)


def versions(stack: Stack, opts: Options) -> list[str]:
    lines = []
    for cmd in stack.versions:
        if opts.mode == "docker":
            # The same commands, inside the image; tools that only exist at build time are skipped.
            out = containers.docker("run", "--rm", "--entrypoint", "sh", stack.image, "-c", cmd, timeout=120)
            if out.returncode != 0:
                continue
        else:
            out = sh(cmd, stack.dir, timeout=120)
        text = (out.stdout or out.stderr).strip().splitlines()
        if text:
            lines.append(text[0].strip())
    return lines


# ---------------------------------------------------------------- measurements

def start_server(stack: Stack, db: Path, opts: Options, log_path: Path):
    """Start the stack's server on a copy of `db`; returns (server, ms to first healthy response)."""
    env = stack.environment(opts.mode, port=stack.port, cores=opts.cores)
    if opts.mode == "docker":
        volume = f"sb-{stack.name}-data"
        containers.load_db(stack, volume, db, "bench.db")
        server = containers.ContainerServer(stack, volume, "bench.db", env, opts.cores, opts.memory, log_path)
    else:
        server = procs.Server(fill(stack.start, port=stack.port, cores=opts.cores), stack.dir,
                              {**env, "DATABASE_PATH": str(db)}, log_path)
    return server, procs.wait_healthy(stack.port, server)


def stop_server(server, stack: Stack, opts: Options) -> None:
    server.stop()
    if opts.mode == "docker":
        containers.remove_volume(f"sb-{stack.name}-data")


def loadtest_cmd(stack: Stack, out_json: Path, opts: Options, params: dict) -> list[str]:
    """The load generator: on the host against the published port, or in a
    container on the Docker network (--loadgen network)."""
    args = [f"{k}={v}" for k, v in params.items()]
    if opts.mode == "docker" and opts.loadgen == "network":
        return ["docker", "run", "--rm", "--network", containers.NETWORK, "-v", f"{out_json.parent.resolve()}:/out",
                containers.LOADTEST_IMAGE, f"url=http://{stack.name}:{stack.port}", f"json=/out/{out_json.name}", *args]
    return [str(LOADTEST), f"url=http://127.0.0.1:{stack.port}", f"json={out_json}", *args]


def run_loadtest(stack: Stack, out_json: Path, opts: Options, **params) -> dict:
    subprocess.run(loadtest_cmd(stack, out_json, opts, params), capture_output=True, text=True, timeout=3600)
    return json.loads(out_json.read_text()) if out_json.exists() else {}


def conformance(stack: Stack, run_dir: Path, opts: Options) -> dict:
    """VER-1: seed 10k contacts into an empty database and hash its contents."""
    db = WORK / f"{stack.name}-checksum.db"
    _remove_db(db)
    out, _ = run_seeder(stack, 10_000, db, opts, run_dir / stack.name / "seed.log", "checksum")
    if out.returncode != 0 or not db.exists():
        return {"ok": False, "checksum": "", "error": "seeder failed (see seed.log)"}
    digest = seed_checksum(db)
    _remove_db(db)
    return {"ok": digest == EXPECTED_CHECKSUM, "checksum": digest}


def seed_checksum(db: Path) -> str:
    """Hash seed-checksum.sql's output exactly as the sqlite3 CLI prints it
    (list mode: '|' between columns, NULL as an empty string)."""
    lines = []
    with sqlite3.connect(db) as conn:
        for statement in CHECKSUM_SQL.read_text().split(";"):
            if statement.strip():
                for row in conn.execute(statement):
                    lines.append("|".join("" if v is None else str(v) for v in row))
    return hashlib.sha256(("\n".join(lines) + "\n").encode()).hexdigest()


def parity(stack: Stack, reference: Stack, db: Path, opts: Options, run_dir: Path) -> dict:
    """VER-2: the parity check against the reference server, run in the same mode (CTR-17)."""
    ref_db = WORK / "reference.db"
    _copy_db(db, ref_db)
    ref, ready = start_server(reference, ref_db, opts, run_dir / stack.name / "reference-server.log")
    try:
        if ready is None:
            return {"ok": False, "summary": f"{reference.label} reference server failed to start"}
        out = subprocess.run([sys.executable, str(ROOT / "bench" / "parity.py"),
                              f"http://127.0.0.1:{stack.port}/api", f"http://127.0.0.1:{reference.port}/api"],
                             capture_output=True, text=True, timeout=600)
        (run_dir / stack.name / "parity.log").write_text(out.stdout + out.stderr)
        last = (out.stdout.strip().splitlines() or ["no output"])[-1]
        m = re.match(r"(\d+) identical, (\d+) mismatched; (\d+)/(\d+) contract checks passed", last)
        ok = bool(m) and m.group(2) == "0" and m.group(3) == m.group(4)
        return {"ok": ok, "summary": last}
    finally:
        stop_server(ref, reference, opts)
        _remove_db(ref_db)


def docker_machinery_pids() -> list[int]:
    """Docker Desktop's host processes (the VM, and the port forwarder that carries
    published-port traffic). Their CPU is the containers' and the load's, not other
    programs'."""
    if procs.SYSTEM != "Darwin":
        return []
    out = subprocess.run(["ps", "-A", "-o", "pid=,comm="], capture_output=True, text=True).stdout
    return [int(l.split(None, 1)[0]) for l in out.splitlines()
            if "com.apple.Virtualization.VirtualMachine" in l or "com.docker.backend" in l]


def ramp(stack: Stack, server, opts: Options, stack_dir: Path) -> list[dict]:
    levels = []
    p = opts.profile
    machinery = docker_machinery_pids() if opts.mode == "docker" else []
    for users in p.levels:
        log(f"  {stack.name}: {users:,} users")
        out_json = stack_dir / f"ramp-{users}.json"
        proc = subprocess.Popen(
            loadtest_cmd(stack, out_json, opts, {
                "users": users, "think": opts.think_ms, "edits": opts.edit_pct,
                "warmup": p.ramp_warmup, "duration": p.ramp_duration, "max_id": opts.dataset}),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # CPU = CPU-seconds used during the measured window / window length.
        time.sleep(p.ramp_warmup)
        ours = sorted({*server.host_pids(), *machinery, proc.pid})
        stat0 = server.cpu_stat() if opts.mode == "docker" else {}
        cpu0, t0 = server.cpu_seconds(), time.monotonic()
        machinery0 = procs.cpu_seconds(machinery)
        other = procs.OtherWork(ours)  # everything except the server, load generator, Docker and runner
        time.sleep(p.ramp_duration / 2)
        rss = server.rss_mb()  # ps / cgroup reads don't pause the process
        time.sleep(p.ramp_duration / 2)
        cpu1, t1 = server.cpu_seconds(), time.monotonic()
        stat1 = server.cpu_stat() if opts.mode == "docker" else {}
        machinery1 = procs.cpu_seconds(machinery)
        background = other.cores(sorted({*server.host_pids(), *machinery, proc.pid}))
        proc.wait(timeout=600)
        result = json.loads(out_json.read_text()) if out_json.exists() else {}
        level = {
            "users": users,
            "result": result,
            "cpu_cores": round((cpu1 - cpu0) / (t1 - t0), 2),
            "background_cores": round(background, 2),
            "rss_mb": round(rss, 1),
            # Measured after the run: vmmap (native, macOS) pauses the process it inspects.
            "memory_after_mb": round(server.footprint_mb(), 1),
            "server_alive": server.alive(),
        }
        if stat1:
            # How much the --cpus quota held the server back: paused periods / periods,
            # and paused time per second of the window (CTR-16).
            periods = stat1.get("nr_periods", 0) - stat0.get("nr_periods", 0)
            level["throttled_pct"] = round(100 * (stat1.get("nr_throttled", 0) - stat0.get("nr_throttled", 0))
                                           / periods, 1) if periods else 0.0
            level["throttled_ms_per_s"] = round((stat1.get("throttled_usec", 0) - stat0.get("throttled_usec", 0))
                                                / 1000 / (t1 - t0), 1)
        if machinery:
            # Host CPU of Docker Desktop's VM and port forwarder: the container's CPU plus Docker's overhead.
            level["docker_host_cores"] = round((machinery1 - machinery0) / (t1 - t0), 2)
        levels.append(level)
        p99 = result.get("all", {}).get("p99_ms", float("inf"))
        if not server.alive():
            log(f"  {stack.name}: server exited during the run; stopping the ramp")
            break
        if p99 > opts.stop_p99_ms:
            log(f"  {stack.name}: p99 {p99:.0f} ms > {opts.stop_p99_ms:.0f} ms; skipping higher levels")
            break
    return levels


def seed_bench(stack: Stack, opts: Options, run_dir: Path) -> dict:
    count = opts.profile.seed_count
    out, wall = run_seeder(stack, count, None, opts, run_dir / stack.name / "seed.log", "seed")
    m = re.search(r"in ([\d.]+) ms \((\d+) contacts/sec", out.stdout)
    if out.returncode != 0 or not m:
        return {"ok": False, "count": count, "error": "seeder failed (see seed.log)"}
    return {"ok": True, "count": count, "insert_ms": float(m.group(1)), "per_sec": int(m.group(2)),
            "wall_s": round(wall, 2)}


# ---------------------------------------------------------------- one stack

def warn_if_busy(meta: dict, what: str, opts: Options) -> float:
    """Sample 2 s of CPU used by other programs; warn if it's over the threshold."""
    machinery = docker_machinery_pids() if opts.mode == "docker" else []
    other = procs.OtherWork(machinery)
    time.sleep(2)
    cores = other.cores(machinery)
    if cores > meta["busy_threshold"]:
        log(f"WARNING: other programs used {cores:.1f} cores just before {what} (threshold "
            f"{meta['busy_threshold']:.1f}): results will be noisy. Close them for publishable numbers.")
    if opts.mode == "docker":
        others = containers.other_containers()
        if others:
            log(f"WARNING: other containers are running ({', '.join(others)}); they share CPU with the "
                "stack under test. Stop them for publishable numbers.")
    return cores


def wait_for_quiet(meta: dict, what: str, opts: Options) -> None:
    """Hold until other programs stay under the busy threshold for two samples in a
    row (macOS indexing and media analysis come in bursts), or give up after
    opts.wait_quiet minutes and let the busy check flag the result."""
    machinery = docker_machinery_pids() if opts.mode == "docker" else []
    deadline, quiet, waited = time.monotonic() + opts.wait_quiet * 60, 0, False
    while time.monotonic() < deadline:
        other = procs.OtherWork(machinery)
        time.sleep(5)
        if other.cores(machinery) <= meta["busy_threshold"]:
            quiet += 1
            if quiet >= 2:
                if waited:
                    log(f"machine is quiet again; starting {what}")
                return
        else:
            if not waited:
                log(f"waiting up to {opts.wait_quiet} min for other programs to go quiet before {what}")
            quiet, waited = 0, True
    log(f"still busy after {opts.wait_quiet} min; running {what} anyway (it will be flagged)")


def run_stack(stack: Stack, reference: Stack, dataset: Path, opts: Options, run_dir: Path, meta: dict,
              load: float | None = None) -> dict:
    """Benchmark one stack into <results>/<stack>/, replacing its previous results."""
    stack_dir = run_dir / stack.name
    shutil.rmtree(stack_dir, ignore_errors=True)
    stack_dir.mkdir(parents=True, exist_ok=True)
    result: dict = {
        "name": stack.name, "label": stack.label, "description": stack.description,
        "concurrency": fill(stack.concurrency, cores=opts.cores), "port": stack.port, "slot": stack.slot,
        "status": "ok", "error": "", "versions": [], "started_at": dt.datetime.now().isoformat(timespec="seconds"),
        "mode": opts.mode,
        "background_before_cores": round(load, 2) if load is not None else None,
        "run": meta,  # machine, profile, core budget, ...: backends are often measured at different times
    }

    def finish(status: str = "ok", error: str = "") -> dict:
        result["status"], result["error"] = status, error
        result["finished_at"] = dt.datetime.now().isoformat(timespec="seconds")

        (stack_dir / "result.json").write_text(json.dumps(result, indent=2))
        return result

    if opts.mode == "docker" and not stack.docker:
        log(f"{stack.name}: skipped, no docker block in bench.json")
        return finish("skipped", "no docker block in bench.json (docs/requirements/07-containers.md)")
    missing = stack.missing_tools(opts.mode)
    if missing:
        log(f"{stack.name}: skipped, missing {', '.join(missing)}")
        return finish("skipped", f"missing tools: {', '.join(missing)}")
    if procs.port_in_use(stack.port):
        return finish("failed", f"port {stack.port} is already in use; stop whatever is running there")

    if opts.build and (stack.build or opts.mode == "docker"):
        log(f"{stack.name}: building{' image' if opts.mode == 'docker' else ''}")
        ok, secs, error = build_stack(stack, run_dir, opts)
        result["build_s"] = round(secs, 1)
        if not ok:
            log(f"{stack.name}: build failed")
            return finish("failed", error)
    if opts.mode == "docker":
        result["docker"] = {**containers.image_details(stack), "loadgen": opts.loadgen}
    result["versions"] = versions(stack, opts)

    if opts.conformance:
        log(f"{stack.name}: seed checksum")
        result["conformance"] = conformance(stack, run_dir, opts)

    db = WORK / f"{stack.name}.db"
    _copy_db(dataset, db)
    log(f"{stack.name}: starting server")
    server, startup_ms = start_server(stack, db, opts, stack_dir / "server.log")
    try:
        if startup_ms is None:
            return finish("failed", "server did not answer /api/health (see server.log)")
        result["startup_ms"] = round(startup_ms)
        machinery = docker_machinery_pids() if opts.mode == "docker" else []
        other = procs.OtherWork(sorted({*server.host_pids(), *machinery}))
        time.sleep(3)
        result["background_idle_cores"] = round(other.cores(sorted({*server.host_pids(), *machinery})), 2)
        result["processes"] = server.process_count()
        result["idle_memory_mb"] = round(server.footprint_mb(), 1)
        result["idle_rss_mb"] = round(server.rss_mb(), 1)

        if opts.parity and stack.name != reference.name:
            log(f"{stack.name}: parity check against {reference.label}")
            result["parity"] = parity(stack, reference, db, opts, run_dir)

        if opts.endpoints:
            log(f"{stack.name}: single endpoints")
            p = opts.profile
            result["endpoints"] = []
            for label, path in ENDPOINTS:
                data = run_loadtest(stack, stack_dir / "endpoint.json", opts, endpoint=path,
                                    users=opts.endpoint_clients, think=0,
                                    warmup=p.endpoint_warmup, duration=p.endpoint_duration)
                result["endpoints"].append({"label": label, "path": path, "result": data})
            (stack_dir / "endpoint.json").unlink(missing_ok=True)

        if opts.ramp:
            log(f"{stack.name}: simulated users")
            result["ramp"] = ramp(stack, server, opts, stack_dir)
    finally:
        stop_server(server, stack, opts)
        _remove_db(db)

    if opts.seed:
        log(f"{stack.name}: seeding {opts.profile.seed_count:,} contacts")
        result["seed"] = seed_bench(stack, opts, run_dir)
    log(f"{stack.name}: done")
    return finish()


# ---------------------------------------------------------------- whole run

def run(stacks: list[Stack], all_stacks: list[Stack], opts: Options) -> Path:
    """Benchmark the given stacks and rebuild the summary. Native results go to
    results/, Docker results to results/docker/ (CTR-15), unless --out says otherwise."""
    reference = next((s for s in all_stacks if s.name == opts.reference), None)
    if reference is None:
        raise SystemExit(f"reference stack {opts.reference!r} not found")

    info = machine.collect()
    root = (opts.out or (RESULTS / "docker" if opts.mode == "docker" else RESULTS)).resolve()
    root.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)

    meta = {
        "machine": info,
        "git": machine.git_state(),
        "memory_metric": machine.memory_metric_name() if opts.mode == "native"
                         else "container working set (cgroup memory.current minus inactive_file)",
        "started_at": dt.datetime.now().isoformat(timespec="seconds"),
        "profile": vars(opts.profile),
        "cores": opts.cores,
        "dataset": opts.dataset,
        "reference": reference.name,
        "stop_p99_ms": opts.stop_p99_ms,
        "think_ms": opts.think_ms,
        "edit_pct": opts.edit_pct,
        "endpoint_clients": opts.endpoint_clients,
        "notes": opts.notes,
        "busy_threshold": machine.busy_threshold(info),
        "mode": opts.mode,
    }
    if opts.mode == "docker":
        d = containers.info()
        meta.update({"docker": d, "loadgen": opts.loadgen, "memory": opts.memory})
        if d["vm_cpus"] and d["vm_cpus"] < opts.cores + 2:
            log(f"WARNING: Docker has {d['vm_cpus']} CPUs; give it at least {opts.cores + 2} (cores + 2) "
                "so the load and Docker itself don't compete with the server.")
        containers.ensure_network()
    log(f"==== benchmark run: {', '.join(s.name for s in stacks)} (profile {opts.profile.name}, "
        f"{opts.cores} cores, {opts.mode}){' — ' + opts.notes if opts.notes else ''}")
    log(f"results: {root}")
    warn_if_busy(meta, "the run", opts)

    build_loadtest(opts)
    needs_reference = opts.parity or not (CACHE / f"dataset-{opts.dataset}.db").exists()
    if opts.build and needs_reference and (reference.build or opts.mode == "docker"):
        log(f"{reference.name}: building (reference)")
        ok, _, error = build_stack(reference, WORK, opts)
        if not ok:
            raise SystemExit(f"reference build failed: {error}")
    dataset = ensure_dataset(reference, opts.dataset, opts)

    for stack in stacks:
        if opts.wait_quiet:
            wait_for_quiet(meta, stack.name, opts)
        before = warn_if_busy(meta, stack.name, opts)
        result = run_stack(stack, reference, dataset, opts, root, meta, before)
        report.write_stack(root, result)
        report.write_summary(root)  # after every stack, so a long run shows progress

    shutil.rmtree(WORK, ignore_errors=True)
    log(f"done: {root / 'summary.html'}")
    return root
