"""Docker mode (docs/requirements/07-containers.md): build stack images, move
databases in and out of named volumes, and run servers as containers with the
same interface as procs.Server.

CPU and memory come from the container's own cgroup (CTR-16), read with
`docker exec`, which works the same on Linux and inside Docker Desktop's VM.
"""

from __future__ import annotations

import json
import platform
import re
import subprocess
import time
from pathlib import Path

from .stacks import ROOT, Stack, fill

NETWORK = "stack-benchmark"
LOADTEST_IMAGE = "stack-benchmark-loadtest"
SYSTEM = platform.system()


def docker(*args: str, timeout: float = 600, check: bool = False) -> subprocess.CompletedProcess:
    out = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
    if check and out.returncode != 0:
        raise RuntimeError(f"docker {' '.join(args[:3])} failed: {out.stderr.strip()}")
    return out


# ---------------------------------------------------------------- engine

def info() -> dict:
    """Docker version and the VM/engine resources (CTR-18)."""
    out = docker("info", "--format", "{{json .}}", timeout=60)
    if out.returncode != 0:
        raise SystemExit(f"Docker isn't available: {out.stderr.strip() or out.stdout.strip()}")
    d = json.loads(out.stdout)
    return {
        "docker_version": d.get("ServerVersion", ""),
        "engine_os": d.get("OperatingSystem", ""),
        "engine_arch": d.get("Architecture", ""),
        "vm_cpus": d.get("NCPU", 0),
        "vm_memory_gb": round(d.get("MemTotal", 0) / 2**30, 1),
    }


def host_arch() -> str:
    m = platform.machine().lower()
    return {"x86_64": "amd64", "amd64": "amd64", "arm64": "arm64", "aarch64": "arm64"}.get(m, m)


def other_containers() -> list[str]:
    """Running containers that aren't ours: they share the VM (or host) with the stack."""
    out = docker("ps", "--format", "{{.Names}}", timeout=30)
    return [n for n in out.stdout.split() if not n.startswith("sb-")]


def ensure_network() -> None:
    if docker("network", "inspect", NETWORK, timeout=30).returncode != 0:
        docker("network", "create", NETWORK, timeout=30, check=True)


def vm_pids() -> list[int]:
    """Host processes that run containers. macOS: Docker Desktop's VM, which also
    runs the stack's container, so its CPU isn't "other programs" (the busy check
    warns about other containers separately). Linux: none; containers are ordinary
    processes, found per container with `docker top`."""
    if SYSTEM != "Darwin":
        return []
    out = subprocess.run(["ps", "-A", "-o", "pid=,comm="], capture_output=True, text=True).stdout
    return [int(line.split(None, 1)[0]) for line in out.splitlines()
            if "com.apple.Virtualization.VirtualMachine" in line or "com.docker.krun" in line]


# ---------------------------------------------------------------- images

def build_image(stack: Stack, log_file: Path, tag: str | None = None) -> tuple[bool, float, str]:
    started = time.monotonic()
    tag = tag or stack.image
    cmd = ["docker", "build", "--progress=plain", "-f", str(stack.dockerfile), "-t", tag, str(ROOT)]
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with open(log_file, "a") as f:
        f.write(f"$ {' '.join(cmd)}\n")
        out = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, timeout=3600)
    if out.returncode != 0:
        return False, time.monotonic() - started, "docker build failed (see build.log)"
    arch = image_arch(tag)
    if arch != host_arch():  # CTR-8: never benchmark under emulation
        return False, time.monotonic() - started, f"image is {arch}, host is {host_arch()}: refusing to run emulated"
    return True, time.monotonic() - started, ""


def image_arch(image: str) -> str:
    return docker("image", "inspect", "--format", "{{.Architecture}}", image, timeout=30).stdout.strip()


def image_details(stack: Stack) -> dict:
    """Image ID, base image and SQLite version for the report (CTR-7, CTR-18)."""
    image_id = docker("image", "inspect", "--format", "{{.Id}}", stack.image, timeout=30).stdout.strip()
    # `docker image ls` shows the unpacked size; inspect's .Size is the compressed content.
    size = docker("image", "ls", "--format", "{{.Size}}", stack.image, timeout=30).stdout.strip().splitlines()
    sqlite = docker("run", "--rm", "--entrypoint", "cat", stack.image, "/app/sqlite-version", timeout=60)
    froms = re.findall(r"^FROM\s+(\S+)", stack.dockerfile.read_text(), re.M)
    return {
        "image": stack.image,
        "image_id": image_id[:19],
        "image_size": size[0] if size else "",
        "base_image": froms[-1] if froms else "",
        "sqlite_version": sqlite.stdout.strip() if sqlite.returncode == 0 else "",
    }


# ---------------------------------------------------------------- volumes and databases

def data_dir(stack: Stack) -> str:
    return f"{stack.container_dir}/data"


def reset_volume(name: str) -> None:
    docker("volume", "rm", "-f", name, timeout=60)
    docker("volume", "create", name, timeout=60, check=True)


def remove_volume(name: str) -> None:
    docker("volume", "rm", "-f", name, timeout=60)


def load_db(stack: Stack, volume: str, src: Path, filename: str) -> None:
    """Put a (closed, consistent) database file into a fresh named volume (CTR-11).
    The source is the runner's own copy, not a live database, so copying the file
    is safe; it's never a bind mount."""
    reset_volume(volume)
    holder = f"sb-load-{volume}"
    docker("rm", "-f", holder, timeout=60)
    docker("create", "--name", holder, "-v", f"{volume}:{data_dir(stack)}", stack.image, timeout=60, check=True)
    try:
        docker("cp", str(src), f"{holder}:{data_dir(stack)}/{filename}", timeout=600, check=True)
    finally:
        docker("rm", "-f", holder, timeout=60)


def seed(stack: Stack, count: int, env: dict[str, str], out_db: Path | None, log_file: Path,
         volume: str) -> tuple[subprocess.CompletedProcess, float]:
    """Run the image's seeder into a fresh volume; optionally copy the database out.
    Returns the seeder's output and its wall time."""
    reset_volume(volume)
    name = f"sb-seed-{volume}"
    docker("rm", "-f", name, timeout=60)
    db = f"{data_dir(stack)}/seed.db"
    args = ["run", "--name", name, "-v", f"{volume}:{data_dir(stack)}", "-e", f"DATABASE_PATH={db}"]
    for k, v in env.items():
        args += ["-e", f"{k}={v}"]
    cmd = fill((stack.docker or {}).get("seed", "seed {count}"), count=count).split()
    started = time.monotonic()
    out = docker(*args, stack.image, *cmd, timeout=1800)
    wall = time.monotonic() - started
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with open(log_file, "a") as f:
        f.write(f"$ docker {' '.join(args)} {stack.image} {' '.join(cmd)}\n{out.stdout}{out.stderr}\n")
    try:
        if out.returncode == 0 and out_db is not None:
            for suffix in ("", "-wal"):
                cp = docker("cp", f"{name}:{db}{suffix}", f"{out_db}{suffix}", timeout=600)
                if suffix == "" and cp.returncode != 0:
                    out = subprocess.CompletedProcess(out.args, 1, out.stdout, out.stderr + cp.stderr)
    finally:
        docker("rm", "-f", name, timeout=60)
        remove_volume(volume)
    return out, wall


# ---------------------------------------------------------------- servers

class ContainerServer:
    """A stack's server in a container, with the same interface as procs.Server."""

    def __init__(self, stack: Stack, volume: str, db_file: str, env: dict[str, str], cores: int,
                 memory: str, log_path: Path):
        self.name = f"sb-{stack.name}"
        self.log_path = log_path
        self._alive_at, self._alive = 0.0, True
        docker("rm", "-f", self.name, timeout=60)
        args = ["run", "-d", "--name", self.name, "--network", NETWORK, "--network-alias", stack.name,
                f"--cpus={cores}", f"--memory={memory}",
                "-p", f"127.0.0.1:{stack.port}:{stack.port}",
                "-v", f"{volume}:{data_dir(stack)}", "-e", f"DATABASE_PATH={data_dir(stack)}/{db_file}"]
        for k, v in env.items():
            args += ["-e", f"{k}={v}"]
        start = (stack.docker or {}).get("start", "serve").split()
        out = docker(*args, stack.image, *start, timeout=120)
        if out.returncode != 0:
            self._alive = False
            log_path.write_text(out.stdout + out.stderr)

    def alive(self) -> bool:
        # Cached for 250 ms: wait_healthy polls every few milliseconds.
        if self._alive and time.monotonic() - self._alive_at > 0.25:
            state = docker("inspect", "--format", "{{.State.Running}}", self.name, timeout=30).stdout.strip()
            self._alive, self._alive_at = state == "true", time.monotonic()
        return self._alive

    def _cgroup(self, *files: str) -> dict[str, str]:
        script = "; ".join(f"echo '== {f}'; cat /sys/fs/cgroup/{f}" for f in files)
        out = docker("exec", self.name, "sh", "-c", script, timeout=30).stdout
        parts, current = {}, None
        for line in out.splitlines():
            if line.startswith("== "):
                current = line[3:]
                parts[current] = ""
            elif current:
                parts[current] += line + "\n"
        return parts

    def cpu_stat(self) -> dict[str, int]:
        """The cgroup's cpu.stat: usage, and how often the --cpus quota paused it."""
        stat = self._cgroup("cpu.stat").get("cpu.stat", "")
        return {k: int(v) for k, v in re.findall(r"^(\w+) (\d+)$", stat, re.M)}

    def cpu_seconds(self) -> float:
        return self.cpu_stat().get("usage_usec", 0) / 1e6

    def memory(self) -> dict:
        """memory.current, and memory.current minus inactive_file (CTR-16)."""
        parts = self._cgroup("memory.current", "memory.stat")
        try:
            current = int(parts.get("memory.current", "0").strip() or 0)
        except ValueError:
            current = 0
        m = re.search(r"^inactive_file (\d+)", parts.get("memory.stat", ""), re.M)
        inactive = int(m.group(1)) if m else 0
        return {"current_mb": current / 2**20, "working_set_mb": max(0, current - inactive) / 2**20}

    def rss_mb(self) -> float:
        return self.memory()["current_mb"]

    def footprint_mb(self) -> float:
        return self.memory()["working_set_mb"]

    def process_count(self) -> int:
        procs = self._cgroup("cgroup.procs").get("cgroup.procs", "")
        return len(procs.split())

    def host_pids(self) -> list[int]:
        if SYSTEM == "Darwin":
            return vm_pids()
        out = docker("top", self.name, "-eo", "pid", timeout=30).stdout.split()[1:]
        return [int(p) for p in out if p.isdigit()]

    def stop(self) -> None:
        docker("stop", "-t", "10", self.name, timeout=60)
        logs = docker("logs", self.name, timeout=60)
        with open(self.log_path, "a") as f:
            f.write(logs.stdout + logs.stderr)
        docker("rm", "-f", self.name, timeout=60)
