"""Process control and resource measurement, for macOS and Linux.

Servers start in their own session, so every worker a stack forks shares one
process group. That's how CPU and memory get summed over all of a stack's
processes without guessing pgrep patterns.
"""

from __future__ import annotations

import os
import platform
import re
import shlex
import signal
import subprocess
import http.client
import time
from pathlib import Path

SYSTEM = platform.system()
CLOCK_TICKS = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100


class Server:
    def __init__(self, cmd: str, cwd: Path, env: dict[str, str], log_path: Path):
        self.log = open(log_path, "ab")
        self.proc = subprocess.Popen(
            shlex.split(cmd), cwd=cwd, env={**os.environ, **env},
            stdout=self.log, stderr=subprocess.STDOUT, start_new_session=True,
        )
        self.pgid = self.proc.pid

    def pids(self) -> list[int]:
        out = subprocess.run(["ps", "-A", "-o", "pid=,pgid="], capture_output=True, text=True).stdout
        pids = []
        for line in out.splitlines():
            parts = line.split()
            if len(parts) == 2 and int(parts[1]) == self.pgid:
                pids.append(int(parts[0]))
        return pids

    def alive(self) -> bool:
        return self.proc.poll() is None

    # The measurement interface the runner uses; containers.ContainerServer has the same.
    def cpu_seconds(self) -> float:
        return cpu_seconds(self.pids())

    def cpu_stat(self) -> dict[str, int]:
        return {}

    def rss_mb(self) -> float:
        return rss_mb(self.pids())

    def footprint_mb(self) -> float:
        """Between load runs only: vmmap pauses the process (see footprint_mb)."""
        return footprint_mb(self.pids())

    def process_count(self) -> int:
        return len(self.pids())

    def host_pids(self) -> list[int]:
        """Host processes whose CPU is this server's, left out of the busy-machine check."""
        return self.pids()

    def stop(self) -> None:
        """Ctrl-C the whole group, escalating to SIGTERM and then SIGKILL."""
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(self.pgid, sig)
            except ProcessLookupError:
                break
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                self.proc.poll()  # reap the leader so it doesn't linger as a zombie
                if not self.pids():
                    break
                time.sleep(0.1)
            else:
                continue
            break
        self.log.close()


def _get(port: int, path: str, timeout: float) -> int | None:
    """Status code of GET http://127.0.0.1:<port><path>, or None if nothing answers.
    http.client rather than urllib: urllib looks up the system proxy settings on
    every call, which is slow on macOS and would inflate the startup time."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("GET", path)
        return conn.getresponse().status
    except OSError:
        return None
    finally:
        conn.close()


def wait_healthy(port: int, server: Server, timeout: float = 120) -> float | None:
    """Poll /api/health; return milliseconds until the first 200, or None."""
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        if not server.alive():
            return None
        if _get(port, "/api/health", 1) == 200:
            return (time.monotonic() - started) * 1000
        time.sleep(0.005)
    return None


def port_in_use(port: int) -> bool:
    return _get(port, "/", 0.5) is not None


# ---------------------------------------------------------------- CPU

def _parse_ps_time(text: str) -> float:
    """[[dd-]hh:]mm:ss[.ff] -> seconds."""
    days = 0
    if "-" in text:
        d, text = text.split("-", 1)
        days = int(d)
    seconds = 0.0
    for part in text.split(":"):
        seconds = seconds * 60 + float(part)
    return days * 86400 + seconds


def cpu_seconds(pids: list[int]) -> float:
    """Total user + system CPU time used so far by these processes."""
    total = 0.0
    if SYSTEM == "Linux":
        for pid in pids:
            try:
                fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
                total += (int(fields[11]) + int(fields[12])) / CLOCK_TICKS
            except (OSError, IndexError, ValueError):
                pass
        return total
    if not pids:
        return 0.0
    out = subprocess.run(["ps", "-o", "time=", "-p", ",".join(map(str, pids))],
                         capture_output=True, text=True).stdout
    for line in out.split():
        try:
            total += _parse_ps_time(line)
        except ValueError:
            pass
    return total


def all_cpu_seconds() -> float:
    """CPU time used so far by every process on the machine (user + system).

    Linux: the kernel's running total in /proc/stat. macOS: the sum over live
    processes (a process that exits mid-window is missed, which only ever
    under-counts other work)."""
    if SYSTEM == "Linux":
        try:
            fields = [int(x) for x in Path("/proc/stat").read_text().split("\n", 1)[0].split()[1:]]
            user, nice, system, _idle, _iowait, irq, softirq, steal = (fields + [0] * 8)[:8]
            return (user + nice + system + irq + softirq + steal) / CLOCK_TICKS
        except (OSError, ValueError):
            return 0.0
    out = subprocess.run(["ps", "-A", "-o", "time="], capture_output=True, text=True).stdout
    total = 0.0
    for line in out.split():
        try:
            total += _parse_ps_time(line)
        except ValueError:
            pass
    return total


def self_cpu_seconds() -> float:
    t = os.times()
    return t.user + t.system


class OtherWork:
    """Measures CPU used by programs other than ours over a window:
    everything on the machine, minus the processes we pass in, minus this runner."""

    def __init__(self, ours: list[int]):
        self.ours = ours
        self.t0 = time.monotonic()
        self.all0, self.ours0, self.self0 = all_cpu_seconds(), cpu_seconds(ours), self_cpu_seconds()

    def cores(self, ours: list[int] | None = None) -> float:
        ours = ours if ours is not None else self.ours
        elapsed = time.monotonic() - self.t0
        other = (all_cpu_seconds() - self.all0) - (cpu_seconds(ours) - self.ours0) - (self_cpu_seconds() - self.self0)
        return max(0.0, other / elapsed) if elapsed > 0 else 0.0


# ---------------------------------------------------------------- memory

def rss_mb(pids: list[int]) -> float:
    if not pids:
        return 0.0
    out = subprocess.run(["ps", "-o", "rss=", "-p", ",".join(map(str, pids))],
                         capture_output=True, text=True).stdout
    return sum(int(x) for x in out.split() if x.isdigit()) / 1024


def footprint_mb(pids: list[int]) -> float:
    """Physical memory attributable to the processes.

    macOS: vmmap's "Physical footprint". It pauses the process while it reads
    it, so only call this between load runs, never during one.
    Linux: proportional set size (shared pages split between their users).
    """
    total = 0.0
    for pid in pids:
        if SYSTEM == "Darwin":
            out = subprocess.run(["vmmap", "--summary", str(pid)], capture_output=True, text=True).stdout
            m = re.search(r"^Physical footprint:\s+([\d.]+)([KMG])", out, re.M)
            if m:
                total += float(m.group(1)) * {"K": 1 / 1024, "M": 1, "G": 1024}[m.group(2)]
        elif SYSTEM == "Linux":
            try:
                m = re.search(r"^Pss:\s+(\d+) kB", Path(f"/proc/{pid}/smaps_rollup").read_text(), re.M)
                total += int(m.group(1)) / 1024 if m else 0
            except OSError:
                pass
        else:
            total += rss_mb([pid])
    return total
