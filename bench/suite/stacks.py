"""Stack registry: every backend declares itself in backend/<stack>/bench.json.

A manifest is one JSON object, or a list of them (for folders with variants, like
Rails and Rails + ActiveRecord). Fields:

    name         unique id, used in results paths          "go"
    label        display name                              "Go"
    description  one line: framework, driver, etc.
    port         the stack's port (docs/requirements/README.md)
    requires     tools that must be on PATH                ["go"]
    versions     commands whose first output line is recorded ["go version"]
    build        commands run in the stack folder before benchmarking
    start        command that runs the server (in the foreground)
    seed         command that runs the seeder; {count} is substituted
    env          extra environment; {port} and {cores} are substituted
    concurrency  how the core budget is applied, for the report

The runner always sets DATABASE_PATH. Commands run in the stack folder.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

REQUIRED = ("name", "label", "port", "start", "seed")


@dataclass
class Stack:
    name: str
    label: str
    description: str
    port: int
    dir: Path
    start: str
    seed: str
    build: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    versions: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    concurrency: str = ""
    slot: int = 0  # fixed color slot, by port order across all stacks

    def missing_tools(self) -> list[str]:
        return [tool for tool in self.requires if shutil.which(tool) is None]

    def environment(self, **values) -> dict[str, str]:
        return {k: fill(v, **values) for k, v in self.env.items()}


def fill(template: str, **values) -> str:
    for key, value in values.items():
        template = template.replace("{" + key + "}", str(value))
    return template


def discover() -> list[Stack]:
    stacks: list[Stack] = []
    for path in sorted((ROOT / "backend").glob("*/bench.json")):
        data = json.loads(path.read_text())
        for m in data if isinstance(data, list) else [data]:
            missing = [k for k in REQUIRED if k not in m]
            if missing:
                raise SystemExit(f"{path}: missing {', '.join(missing)}")
            stacks.append(Stack(
                name=m["name"], label=m["label"], description=m.get("description", ""),
                port=int(m["port"]), dir=path.parent, start=m["start"], seed=m["seed"],
                build=m.get("build", []), env=m.get("env", {}), versions=m.get("versions", []),
                requires=m.get("requires", []), concurrency=m.get("concurrency", ""),
            ))
    stacks.sort(key=lambda s: s.port)
    for kind in ("name", "port"):
        seen: dict = {}
        for s in stacks:
            value = getattr(s, kind)
            if value in seen:
                raise SystemExit(f"duplicate {kind} {value!r}: {seen[value]} and {s.dir}")
            seen[value] = s.dir
    for i, s in enumerate(stacks):
        s.slot = i
    return stacks
