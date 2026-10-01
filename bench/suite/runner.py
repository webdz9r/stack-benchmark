"""Runs the benchmark for each selected stack and writes the results."""

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
from dataclasses import dataclass, field
from pathlib import Path

from . import machine, procs, report
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

def build_loadtest() -> None:
    log("building loadtest")
    out = sh("cargo build --release --quiet", LOADTEST_DIR)
    if out.returncode != 0:
        raise SystemExit(f"loadtest build failed:\n{out.stderr}")


def build_stack(stack: Stack, run_dir: Path) -> tuple[bool, float, str]:
    started = time.monotonic()
    for cmd in stack.build:
        out = sh(cmd, stack.dir, log_file=run_dir / stack.name / "build.log")
        if out.returncode != 0:
            return False, time.monotonic() - started, f"`{cmd}` failed (see build.log)"
    return True, time.monotonic() - started, ""


def ensure_dataset(reference: Stack, count: int, run_dir: Path) -> Path:
    """Build the shared dataset once with the reference seeder, and reuse it."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"dataset-{count}.db"
    if path.exists():
        return path
    log(f"building the {count:,}-contact dataset with the {reference.label} seeder")
    tmp = CACHE / f"dataset-{count}.tmp.db"
    _remove_db(tmp)
    out = sh(fill(reference.seed, count=count), reference.dir,
             env={**reference.environment(port=reference.port, cores=4), "DATABASE_PATH": str(tmp)})
    if out.returncode != 0:
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


def versions(stack: Stack) -> list[str]:
    lines = []
    for cmd in stack.versions:
        out = sh(cmd, stack.dir, timeout=120)
        text = (out.stdout or out.stderr).strip().splitlines()
        if text:
            lines.append(text[0].strip())
    return lines


# ---------------------------------------------------------------- measurements

def start_server(stack: Stack, db: Path, opts: Options, log_path: Path) -> tuple[procs.Server, float | None]:
    env = {**stack.environment(port=stack.port, cores=opts.cores), "DATABASE_PATH": str(db)}
    server = procs.Server(fill(stack.start, port=stack.port, cores=opts.cores), stack.dir, env, log_path)
    return server, procs.wait_healthy(stack.port, server)


def run_loadtest(port: int, out_json: Path, **params) -> dict:
    args = [str(LOADTEST), f"url=http://127.0.0.1:{port}", f"json={out_json}"]
    args += [f"{k}={v}" for k, v in params.items()]
    subprocess.run(args, capture_output=True, text=True, timeout=3600)
    return json.loads(out_json.read_text()) if out_json.exists() else {}


def conformance(stack: Stack, run_dir: Path) -> dict:
    """VER-1: seed 10k contacts into an empty database and hash its contents."""
    db = WORK / f"{stack.name}-checksum.db"
    _remove_db(db)
    out = sh(fill(stack.seed, count=10_000), stack.dir,
             env={**stack.environment(port=stack.port, cores=4), "DATABASE_PATH": str(db)},
             log_file=run_dir / stack.name / "seed.log")
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
    """VER-2: the 62-request parity check against the reference server."""
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
        ref.stop()
        _remove_db(ref_db)


def ramp(stack: Stack, server: procs.Server, opts: Options, stack_dir: Path) -> list[dict]:
    levels = []
    p = opts.profile
    for users in p.levels:
        log(f"  {stack.name}: {users:,} users")
        out_json = stack_dir / f"ramp-{users}.json"
        proc = subprocess.Popen(
            [str(LOADTEST), f"url=http://127.0.0.1:{stack.port}", f"json={out_json}",
             f"users={users}", f"think={opts.think_ms}", f"edits={opts.edit_pct}",
             f"warmup={p.ramp_warmup}", f"duration={p.ramp_duration}", f"max_id={opts.dataset}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # CPU = CPU-seconds used during the measured window / window length.
        time.sleep(p.ramp_warmup)
        pids = server.pids()
        cpu0, t0 = procs.cpu_seconds(pids), time.monotonic()
        other = procs.OtherWork(pids + [proc.pid])  # everything except the server, load generator and runner
        time.sleep(p.ramp_duration / 2)
        rss = procs.rss_mb(server.pids())  # ps doesn't pause the process
        time.sleep(p.ramp_duration / 2)
        cpu1, t1 = procs.cpu_seconds(server.pids()), time.monotonic()
        background = other.cores(server.pids() + [proc.pid])
        proc.wait(timeout=600)
        result = json.loads(out_json.read_text()) if out_json.exists() else {}
        level = {
            "users": users,
            "result": result,
            "cpu_cores": round((cpu1 - cpu0) / (t1 - t0), 2),
            "background_cores": round(background, 2),
            "rss_mb": round(rss, 1),
            # Measured after the run: vmmap pauses the process it inspects.
            "memory_after_mb": round(procs.footprint_mb(server.pids()), 1),
            "server_alive": server.alive(),
        }
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
    db = WORK / f"{stack.name}-seed.db"
    _remove_db(db)
    count = opts.profile.seed_count
    started = time.monotonic()
    out = sh(fill(stack.seed, count=count), stack.dir,
             env={**stack.environment(port=stack.port, cores=4), "DATABASE_PATH": str(db)},
             log_file=run_dir / stack.name / "seed.log")
    wall = time.monotonic() - started
    _remove_db(db)
    m = re.search(r"in ([\d.]+) ms \((\d+) contacts/sec", out.stdout)
    if out.returncode != 0 or not m:
        return {"ok": False, "count": count, "error": "seeder failed (see seed.log)"}
    return {"ok": True, "count": count, "insert_ms": float(m.group(1)), "per_sec": int(m.group(2)),
            "wall_s": round(wall, 2)}


# ---------------------------------------------------------------- one stack

def warn_if_busy(meta: dict, what: str) -> float:
    """Sample 2 s of CPU used by other programs; warn if it's over the threshold."""
    other = procs.OtherWork([])
    time.sleep(2)
    cores = other.cores([])
    if cores > meta["busy_threshold"]:
        log(f"WARNING: other programs used {cores:.1f} cores just before {what} (threshold "
            f"{meta['busy_threshold']:.1f}): results will be noisy. Close them for publishable numbers.")
    return cores


def run_stack(stack: Stack, reference: Stack, dataset: Path, opts: Options, run_dir: Path, meta: dict,
              load: float | None = None) -> dict:
    """Benchmark one stack into results/<stack>/, replacing its previous results."""
    stack_dir = run_dir / stack.name
    shutil.rmtree(stack_dir, ignore_errors=True)
    stack_dir.mkdir(parents=True, exist_ok=True)
    result: dict = {
        "name": stack.name, "label": stack.label, "description": stack.description,
        "concurrency": fill(stack.concurrency, cores=opts.cores), "port": stack.port, "slot": stack.slot,
        "status": "ok", "error": "", "versions": [], "started_at": dt.datetime.now().isoformat(timespec="seconds"),
        "background_before_cores": round(load, 2) if load is not None else None,
        "run": meta,  # machine, profile, core budget, ...: backends are often measured at different times
    }

    def finish(status: str = "ok", error: str = "") -> dict:
        result["status"], result["error"] = status, error
        result["finished_at"] = dt.datetime.now().isoformat(timespec="seconds")

        (stack_dir / "result.json").write_text(json.dumps(result, indent=2))
        return result

    missing = stack.missing_tools()
    if missing:
        log(f"{stack.name}: skipped, missing {', '.join(missing)}")
        return finish("skipped", f"missing tools: {', '.join(missing)}")
    if procs.port_in_use(stack.port):
        return finish("failed", f"port {stack.port} is already in use; stop whatever is running there")

    if opts.build and stack.build:
        log(f"{stack.name}: building")
        ok, secs, error = build_stack(stack, run_dir)
        result["build_s"] = round(secs, 1)
        if not ok:
            log(f"{stack.name}: build failed")
            return finish("failed", error)
    result["versions"] = versions(stack)

    if opts.conformance:
        log(f"{stack.name}: seed checksum")
        result["conformance"] = conformance(stack, run_dir)

    db = WORK / f"{stack.name}.db"
    _copy_db(dataset, db)
    log(f"{stack.name}: starting server")
    server, startup_ms = start_server(stack, db, opts, stack_dir / "server.log")
    try:
        if startup_ms is None:
            return finish("failed", "server did not answer /api/health (see server.log)")
        result["startup_ms"] = round(startup_ms)
        other = procs.OtherWork(server.pids())
        time.sleep(3)
        pids = server.pids()
        result["background_idle_cores"] = round(other.cores(pids), 2)
        result["processes"] = len(pids)
        result["idle_memory_mb"] = round(procs.footprint_mb(pids), 1)
        result["idle_rss_mb"] = round(procs.rss_mb(pids), 1)

        if opts.parity and stack.name != reference.name:
            log(f"{stack.name}: parity check against {reference.label}")
            result["parity"] = parity(stack, reference, db, opts, run_dir)

        if opts.endpoints:
            log(f"{stack.name}: single endpoints")
            p = opts.profile
            result["endpoints"] = []
            for label, path in ENDPOINTS:
                data = run_loadtest(stack.port, stack_dir / "endpoint.json", endpoint=path,
                                    users=opts.endpoint_clients, think=0,
                                    warmup=p.endpoint_warmup, duration=p.endpoint_duration)
                result["endpoints"].append({"label": label, "path": path, "result": data})
            (stack_dir / "endpoint.json").unlink(missing_ok=True)

        if opts.ramp:
            log(f"{stack.name}: simulated users")
            result["ramp"] = ramp(stack, server, opts, stack_dir)
    finally:
        server.stop()
        _remove_db(db)

    if opts.seed:
        log(f"{stack.name}: seeding {opts.profile.seed_count:,} contacts")
        result["seed"] = seed_bench(stack, opts, run_dir)
    log(f"{stack.name}: done")
    return finish()


# ---------------------------------------------------------------- whole run

def run(stacks: list[Stack], all_stacks: list[Stack], opts: Options) -> Path:
    """Benchmark the given stacks into results/<stack>/ and rebuild results/summary.*."""
    reference = next((s for s in all_stacks if s.name == opts.reference), None)
    if reference is None:
        raise SystemExit(f"reference stack {opts.reference!r} not found")

    info = machine.collect()
    root = opts.out or RESULTS
    root.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)

    meta = {
        "machine": info,
        "git": machine.git_state(),
        "memory_metric": machine.memory_metric_name(),
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
    }
    log(f"==== benchmark run: {', '.join(s.name for s in stacks)} (profile {opts.profile.name}, "
        f"{opts.cores} cores){' — ' + opts.notes if opts.notes else ''}")
    log(f"results: {root}")
    warn_if_busy(meta, "the run")

    build_loadtest()
    if opts.build and reference.build and (opts.parity or not (CACHE / f"dataset-{opts.dataset}.db").exists()):
        log(f"{reference.name}: building (reference)")
        ok, _, error = build_stack(reference, WORK)
        if not ok:
            raise SystemExit(f"reference build failed: {error}")
    dataset = ensure_dataset(reference, opts.dataset, WORK)

    for stack in stacks:
        before = warn_if_busy(meta, stack.name)
        result = run_stack(stack, reference, dataset, opts, root, meta, before)
        report.write_stack(root, result)
        report.write_summary(root)  # after every stack, so a long run shows progress

    shutil.rmtree(WORK, ignore_errors=True)
    log(f"done: {root / 'summary.html'}")
    return root
