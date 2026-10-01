"""Machine specs, recorded at the top of every report so results can be compared
across machines. Deliberately leaves out the hostname and user name."""

from __future__ import annotations

import os
import platform
import re
import subprocess
from pathlib import Path

from .stacks import ROOT


def _run(cmd: list[str] | str, cwd: Path | None = None) -> str:
    try:
        out = subprocess.run(cmd, shell=isinstance(cmd, str), cwd=cwd, capture_output=True,
                             text=True, timeout=30)
        return (out.stdout or out.stderr).strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _sysctl(name: str) -> str:
    return _run(["sysctl", "-n", name])


def collect() -> dict:
    system = platform.system()
    info: dict = {
        "os": system,
        "os_version": "",
        "kernel": platform.release(),
        "arch": platform.machine(),
        "cpu": "",
        "cores_logical": os.cpu_count() or 0,
        "cores_physical": 0,
        "core_types": "",
        "memory_gb": 0.0,
        "power": "",
        "python": platform.python_version(),
    }
    if system == "Darwin":
        info["os_version"] = f"macOS {platform.mac_ver()[0]}"
        info["cpu"] = _sysctl("machdep.cpu.brand_string")
        info["cores_physical"] = int(_sysctl("hw.physicalcpu") or 0)
        info["memory_gb"] = round(int(_sysctl("hw.memsize") or 0) / 2**30, 1)
        levels = []
        for i in range(int(_sysctl("hw.nperflevels") or 0)):
            name = _sysctl(f"hw.perflevel{i}.name")
            count = _sysctl(f"hw.perflevel{i}.physicalcpu")
            if name and count:
                levels.append(f"{count} {name}")
        info["core_types"] = ", ".join(levels)
        power = _run(["pmset", "-g", "batt"])
        info["power"] = "AC power" if "AC Power" in power else "battery" if "Battery Power" in power else ""
    elif system == "Linux":
        release = Path("/etc/os-release")
        if release.exists():
            m = re.search(r'^PRETTY_NAME="?([^"\n]+)', release.read_text(), re.M)
            info["os_version"] = m.group(1) if m else ""
        cpuinfo = Path("/proc/cpuinfo").read_text() if Path("/proc/cpuinfo").exists() else ""
        m = re.search(r"^model name\s*:\s*(.+)$", cpuinfo, re.M)
        info["cpu"] = m.group(1).strip() if m else platform.processor()
        cores = {(p, c) for p, c in re.findall(r"physical id\s*:\s*(\d+)[\s\S]*?core id\s*:\s*(\d+)", cpuinfo)}
        info["cores_physical"] = len(cores) or info["cores_logical"]
        meminfo = Path("/proc/meminfo").read_text() if Path("/proc/meminfo").exists() else ""
        m = re.search(r"^MemTotal:\s*(\d+) kB", meminfo, re.M)
        info["memory_gb"] = round(int(m.group(1)) / 2**20, 1) if m else 0.0
    else:
        info["os_version"] = platform.platform()
        info["cpu"] = platform.processor()
    return info


def load_average() -> list[float]:
    """1, 5 and 15-minute load averages (runnable processes)."""
    try:
        return [round(x, 2) for x in os.getloadavg()]
    except OSError:
        return []


def busy_threshold(info: dict) -> float:
    """Cores of CPU used by other programs above which results count as noisy:
    one core, or 10% of the machine, whichever is more."""
    return max(1.0, 0.1 * (info.get("cores_logical") or 1))


def git_state() -> dict:
    commit = _run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"])
    dirty = bool(_run(["git", "-C", str(ROOT), "status", "--porcelain"]))
    return {"commit": commit if re.fullmatch(r"[0-9a-f]{4,40}", commit) else "uncommitted", "dirty": dirty}


def memory_metric_name() -> str:
    return {"Darwin": "physical footprint (vmmap)", "Linux": "PSS (/proc/<pid>/smaps_rollup)"}.get(
        platform.system(), "RSS")


def slug(info: dict) -> str:
    """A filesystem-friendly machine name from the CPU model, e.g. apple-m5-max."""
    text = re.sub(r"\(r\)|\(tm\)|cpu|processor|@.*$", "", info.get("cpu", "").lower())
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:40] or "machine"
