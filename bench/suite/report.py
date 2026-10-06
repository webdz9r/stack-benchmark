"""Markdown and self-contained HTML reports, rendered from the result JSON.

Two kinds of report:

- results/<stack>/report.{html,md}: one backend in detail, with charts.
- results/summary.{html,md,json}: every backend's current result, compared.

Each backend has one current result (results/<stack>/result.json), replaced
whenever that backend is rerun. The result carries its own run details
(machine, profile, core budget, date, background load), because backends are
often measured at different times.

Every report starts with the machine specs. HTML files have no external
dependencies (inline CSS, SVG and a few lines of JS), so a single file can be
shared as is.
"""

from __future__ import annotations

import html
import json
import math
import os
import re
from pathlib import Path

CAPACITY_P99_MS = 100.0

# Every optimization tried on each stack; each report shows its own section.
OPTIMIZATION_LOG = Path(__file__).resolve().parents[2] / "docs" / "optimization-log.md"
# Stacks that share another's code, and so its history.
LOG_SECTION_OF = {"rails-ar": "Rails"}

# Categorical palette (validated reference instance): slot i -> (light, dark).
PALETTE = [
    ("#2a78d6", "#3987e5"), ("#eb6834", "#d95926"), ("#1baf7a", "#199e70"), ("#eda100", "#c98500"),
    ("#e87ba4", "#d55181"), ("#008300", "#008300"), ("#4a3aa7", "#9085e9"), ("#e34948", "#e66767"),
]

REQUEST_KINDS = [
    ("search", "Search (typed)"), ("search-letters", "A–Z index for a search"), ("list", "List page"),
    ("letters", "A–Z index"), ("contact", "Open a contact"), ("write", "Save a contact"), ("tags", "Tags"),
    ("stats", "Stats"), ("endpoint", "Single endpoint"),
]


# ---------------------------------------------------------------- optimization log

def optimization_log(r: dict) -> tuple[list[str], list[list[str]]] | None:
    """This stack's table from docs/optimization-log.md (its `## <label>` section),
    as (headers, rows) of markdown cells; None if the log has no table for it."""
    try:
        text = OPTIMIZATION_LOG.read_text()
    except OSError:
        return None
    heading = LOG_SECTION_OF.get(r["name"], r["label"])
    section = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not section:
        return None
    lines = [l for l in section.group(1).splitlines() if l.startswith("|")]
    if len(lines) < 3:
        return None
    cells = lambda l: [c.strip() for c in l.strip().strip("|").split("|")]
    return cells(lines[0]), [cells(l) for l in lines[2:]]


def md_inline_html(text: str) -> str:
    """The little markdown the log uses (`code`, *emphasis*), as HTML."""
    out = e(text)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    return re.sub(r"\*([^*]+)\*", r"<em>\1</em>", out)


# ---------------------------------------------------------------- numbers

def capacity(levels: list[dict]) -> tuple[str, float | None]:
    """Users at which p99 crosses 100 ms, interpolated between tested levels.
    Returns (qualifier, users): ("", 3650), (">=", 6000) or ("<", 1000)."""
    points = [(l["users"], l["result"].get("all", {}).get("p99_ms")) for l in levels if l.get("result")]
    points = [(u, p) for u, p in points if p is not None]
    if not points:
        return "", None
    prev = None
    for users, p99 in points:
        if p99 >= CAPACITY_P99_MS:
            if prev is None:
                return "<", users
            u0, p0 = prev
            return "", round((u0 + (CAPACITY_P99_MS - p0) / (p99 - p0) * (users - u0)) / 50) * 50
        prev = (users, p99)
    return ">=", points[-1][0]


def fmt_capacity(levels: list[dict] | None) -> str:
    if not levels:
        return "—"
    q, users = capacity(levels)
    if users is None:
        return "—"
    return {"<": "< ", ">=": "≥ "}.get(q, "~") + f"{users:,}"


def fmt_int(v) -> str:
    return "—" if v is None else f"{v:,.0f}"


def fmt_ms(v) -> str:
    if v is None:
        return "—"
    return f"{v:,.0f} ms" if v >= 100 else f"{v:.1f} ms"


def fmt_mb(v) -> str:
    if v is None:
        return "—"
    return f"{v / 1024:.2f} GB" if v >= 1024 else f"{v:,.0f} MB"


def level_at(levels: list[dict] | None, users: int) -> dict | None:
    return next((l for l in levels or [] if l["users"] == users), None)


def all_users(results: list[dict]) -> list[int]:
    return sorted({l["users"] for r in results for l in r.get("ramp") or []})


def peak_memory(r: dict) -> float | None:
    values = [l.get("memory_after_mb") for l in r.get("ramp") or [] if l.get("memory_after_mb")]
    return max(values) if values else None


def ramp_value(r: dict, users: int, key: str):
    level = level_at(r.get("ramp"), users)
    if not level:
        return None
    if key in ("p50_ms", "p95_ms", "p99_ms", "req_s"):
        return level["result"].get("all", {}).get(key)
    return level.get(key)


def check(ok: bool | None) -> str:
    return "—" if ok is None else ("✅ pass" if ok else "❌ fail")


def endpoint_rps(r: dict, i: int) -> str:
    return fmt_int(ep_value(r, i))


def ep_value(r: dict, i: int) -> float | None:
    eps = r.get("endpoints") or []
    return eps[i]["result"].get("all", {}).get("req_s") if i < len(eps) else None


def p99_cell(level: dict | None) -> str:
    if not level:
        return "—"
    text = fmt_ms(level["result"].get("all", {}).get("p99_ms"))
    return text + (" ⚠" if level["result"].get("errors") else "")


def cpu_cell(level: dict | None) -> str:
    return "—" if not level else f"{level['cpu_cores']:.2f}"


def seed_text(seed: dict | None) -> str:
    if not seed:
        return "—"
    if not seed.get("ok"):
        return f"failed: {seed.get('error', '')}"
    return f"{seed['count']:,} contacts in {seed['insert_ms'] / 1000:.1f} s ({seed['per_sec']:,}/s)"


def seed_short(seed: dict | None) -> str:
    return f"{seed['insert_ms'] / 1000:.1f} s" if seed and seed.get("ok") else "—"


# ---------------------------------------------------------------- run context

def busy(meta: dict, load: list[float] | None) -> bool:
    return bool(load) and load[0] > meta.get("busy_threshold", float("inf"))


def background_cores(r: dict) -> list[float]:
    """CPU used by other programs: just before, at idle, and during each load level."""
    values = [r.get("background_before_cores"), r.get("background_idle_cores")]
    values += [l.get("background_cores") for l in r.get("ramp") or []]
    return [v for v in values if v is not None]


def result_busy(r: dict) -> bool:
    """Was other work competing with this stack's measurements?"""
    meta = r.get("run", {})
    measured = background_cores(r)
    if measured:
        return max(measured) > meta.get("busy_threshold", float("inf"))
    # Older results only recorded the load average (which also counts the benchmark itself).
    return busy(meta, r.get("load_before")) or busy(meta, r.get("load_after"))


def annotate(r: dict, link: str) -> dict:
    """Attach what the renderers need: the result's run details, busy flag and report link."""
    return {**r, "_busy": result_busy(r), "_link": link, "_meta": r.get("run", {})}


def machine_rows(meta: dict, run_details: bool = True) -> list[tuple[str, str]]:
    m = meta["machine"]
    cores = f"{m['cores_physical']} physical / {m['cores_logical']} logical"
    if m.get("core_types"):
        cores += f" ({m['core_types']})"
    git = meta["git"]
    p = meta["profile"]
    rows = [
        ("CPU", m.get("cpu") or "unknown"),
        ("Cores", cores),
        ("Memory", f"{m['memory_gb']} GB"),
        ("OS", f"{m['os_version']} (kernel {m['kernel']}, {m['arch']})"),
    ]
    if m.get("power"):
        rows.append(("Power", m["power"]))
    if meta.get("mode") == "docker":
        d = meta.get("docker", {})
        rows.append(("Mode", f"Docker {d.get('docker_version', '')} ({d.get('engine_os', '')}, "
                             f"{d.get('vm_cpus', '?')} CPUs / {d.get('vm_memory_gb', '?')} GB for containers); "
                             f"each server in a container limited to {meta['cores']} CPUs / {meta.get('memory', '?')}, "
                             f"load generator on the {'host via published ports' if meta.get('loadgen') == 'host' else 'Docker network'}"))
    if not run_details:
        rows.append(("Memory metric", meta["memory_metric"]))
        return rows
    rows += [
        ("Date", meta["started_at"].replace("T", " ")),
        ("Profile", f"{p['name']}: {p['description']}"),
        ("Core budget", f"{meta['cores']} cores per server (the load generator runs on the same machine)"),
        ("Dataset", f"{meta['dataset']:,} contacts"),
        ("Memory metric", meta["memory_metric"]),
        ("Repo commit", git["commit"] + (" (with uncommitted changes)" if git["dirty"] else "")),
    ]
    if meta.get("notes"):
        rows.append(("Notes", meta["notes"]))
    return rows


def load_text(r: dict) -> str:
    measured = background_cores(r)
    if measured:
        text = f"used up to {max(measured):.1f} cores (threshold {r['run'].get('busy_threshold', 0):.1f})"
        return text + (" — BUSY: treat these numbers as noisy" if result_busy(r) else "")
    before, after = r.get("load_before") or [], r.get("load_after") or []
    if not before and not after:
        return "not measured"
    parts = ([f"{before[0]:.1f} before"] if before else []) + ([f"{after[0]:.1f} after"] if after else [])
    text = "load average " + ", ".join(parts)
    if result_busy(r):
        text += " (BUSY: other programs were using the CPU; treat these numbers as noisy)"
    return text


METHOD_NOTE = (
    "Simulated users open the app, then act every ~{think:.0f} s on average: scroll or jump letters (35%), "
    "type a search (30%), open a contact (25%), switch view (5%), edit and save ({edit}%). Each level warms up "
    "for {warm} s and is measured for {dur} s. Capacity is where p99 latency crosses 100 ms, interpolated "
    "between tested levels. A level whose p99 passes {stop:,.0f} ms ends that stack's ramp. Single-endpoint "
    "tests use {clients} clients with no pauses. CPU is CPU-seconds used during the measured window divided by "
    "its length (1.0 = one core)."
)


def method_note(meta: dict) -> str:
    p = meta["profile"]
    return METHOD_NOTE.format(think=meta["think_ms"] / 1000, edit=meta["edit_pct"], warm=p["ramp_warmup"],
                              dur=p["ramp_duration"], stop=meta["stop_p99_ms"], clients=meta["endpoint_clients"])


def comparability(results: list[dict]) -> list[str]:
    """Warnings about results that weren't measured under the same conditions."""
    warnings = []
    def distinct(fn):
        return sorted({fn(r["_meta"]) for r in results})
    for label, fn in (
        ("machines", lambda m: f"{m['machine'].get('cpu')} / {m['machine'].get('memory_gb')} GB"),
        ("profiles", lambda m: m["profile"]["name"]),
        ("core budgets", lambda m: f"{m['cores']} cores"),
        ("datasets", lambda m: f"{m['dataset']:,} contacts"),
        ("modes (native vs Docker)", lambda m: m.get("mode", "native")),
        ("load generator placements", lambda m: m.get("loadgen", "host")),
    ):
        values = distinct(fn)
        if len(values) > 1:
            warnings.append(f"These results come from different {label} ({', '.join(values)}), so they aren't "
                            "directly comparable.")
    noisy = [r["label"] for r in results if r.get("_busy")]
    if noisy:
        warnings.append(f"Measured while the machine was busy with other work: {', '.join(noisy)}. Those results "
                        "are noisy; rerun them on an idle machine before comparing or sharing.")
    return warnings


def source_rows(results: list[dict]) -> list[list[str]]:
    rows = []
    for r in results:
        m = r["_meta"]
        profile = m["profile"]["name"] + (" (Docker)" if m.get("mode") == "docker" else "")
        rows.append([r["label"], (r.get("started_at") or m["started_at"]).replace("T", " "), profile,
                     f"{m['cores']}", m["machine"].get("cpu") or "?",
                     "busy ⚠" if r.get("_busy") else "quiet", m["git"]["commit"]])
    return rows


SOURCE_HEADERS = ["Stack", "Measured", "Profile", "Core budget", "Machine", "Load", "Commit"]


# ---------------------------------------------------------------- markdown

def md_table(headers: list[str], rows: list[list[str]], right: set[int] = frozenset()) -> str:
    align = ["---:" if i in right else "---" for i in range(len(headers))]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(align) + " |"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def md_machine(meta: dict, run_details: bool = True) -> str:
    return md_table(["", ""], [[f"**{k}**", v] for k, v in machine_rows(meta, run_details)])


def summary_rows(r: dict) -> list[list[str]]:
    conf, par = r.get("conformance"), r.get("parity")
    return [
        ["Users at p99 ≈ 100 ms", fmt_capacity(r.get("ramp"))],
        ["Startup to first response", fmt_ms(r.get("startup_ms"))],
        ["Idle memory", fmt_mb(r.get("idle_memory_mb"))],
        ["Peak memory after a load level", fmt_mb(peak_memory(r))],
        ["Processes", fmt_int(r.get("processes"))],
        ["Seed checksum (VER-1)", check(conf["ok"]) if conf else "—"],
        ["API parity (VER-2)", f"{check(par['ok'])} ({par['summary']})" if par else "— (reference stack)"],
        ["Seeding", seed_text(r.get("seed"))],
    ] + ([
        ["Image", f"{r['docker'].get('base_image', '?')} runtime, {r['docker'].get('image_size') or '?'}"],
        ["SQLite in the image", r["docker"].get("sqlite_version") or "?"],
    ] if r.get("docker") else [])


def ramp_rows(r: dict) -> list[list[str]]:
    rows = []
    for l in r.get("ramp") or []:
        a = l["result"].get("all", {})
        rows.append([f"{l['users']:,}", fmt_int(a.get("req_s")), fmt_ms(a.get("p50_ms")), fmt_ms(a.get("p95_ms")),
                     fmt_ms(a.get("p99_ms")), fmt_int(l["result"].get("errors")),
                     f"{l['cpu_cores']:.2f}" + (f" (throttled {l['throttled_pct']:.0f}%)" if l.get("throttled_pct") else ""),
                     fmt_mb(l.get("memory_after_mb")),
                     "—" if l.get("background_cores") is None else f"{l['background_cores']:.2f} cores"])
    return rows


RAMP_HEADERS = ["Users", "req/s", "p50", "p95", "p99", "Errors", "CPU cores", "Memory after", "Other programs"]


def kind_rows(r: dict) -> tuple[list[str], list[list[str]]]:
    """p99 per request type (rows) at each user level (columns)."""
    levels = r.get("ramp") or []
    headers = ["Request type"] + [f"{l['users']:,} users" for l in levels]
    rows = []
    for kind, label in REQUEST_KINDS:
        cells = [fmt_ms(l["result"].get("kinds", {}).get(kind, {}).get("p99_ms")) for l in levels]
        if any(c != "—" for c in cells):
            rows.append([label] + cells)
    return headers, rows


def stack_markdown(r: dict) -> str:
    meta = r["run"]
    out = [f"# {r['label']}: benchmark results", "", "[← All backends](../summary.md)", "",
           md_machine(meta), "", f"**Other programs:** {load_text(r)}", ""]
    if result_busy(r):
        out += ["> **Warning:** other programs were using the CPU while this ran, so these results are noisy.", ""]
    out += [f"**Stack:** {r['description']}  ", f"**Concurrency:** {r['concurrency']}  "]
    if r.get("versions"):
        out.append(f"**Versions:** {'; '.join(r['versions'])}  ")
    out.append("")
    if r["status"] != "ok":
        out += [f"**{r['status'].upper()}:** {r['error']}", ""]
    out += ["## Summary", "", md_table(["Metric", "Value"], summary_rows(r), {1}), ""]
    if r.get("ramp"):
        out += ["## Simulated users", "", md_table(RAMP_HEADERS, ramp_rows(r), set(range(9))), ""]
        headers, rows = kind_rows(r)
        out += ["### p99 by request type", "", md_table(headers, rows, set(range(1, len(headers)))), "",
                method_note(meta), ""]
    if r.get("endpoints"):
        rows = [[x["label"], fmt_int(x["result"].get("all", {}).get("req_s")),
                 fmt_ms(x["result"].get("all", {}).get("p50_ms")), fmt_ms(x["result"].get("all", {}).get("p99_ms")),
                 fmt_int(x["result"].get("errors"))] for x in r["endpoints"]]
        out += ["## Single endpoints", "", md_table(["Request", "req/s", "p50", "p99", "Errors"], rows, {1, 2, 3, 4}), ""]
    log = optimization_log(r)
    if log:
        href = r.get("_log_href", "../../docs/optimization-log.md")
        out += ["## Optimization history", "",
                f"Every change tried on this stack, oldest first, from [the optimization log]({href}).", "",
                md_table(*log), ""]
    return "\n".join(out)


def summary_markdown(meta: dict, results: list[dict], title: str) -> str:
    ok = [r for r in results if r["status"] == "ok"]
    out = [f"# {title}", "", md_machine(meta, run_details=False), ""]
    for warning in comparability(ok):
        out += [f"> **Warning:** {warning}", ""]
    out += ["## At a glance", "", md_table(
        ["Stack", "Users at p99 ≈ 100 ms", "Single contact req/s", "List page req/s", "Idle memory",
         "Peak memory", "Startup", "Seed"],
        [[f"[{r['label']}]({r['_link']})", fmt_capacity(r.get("ramp")), endpoint_rps(r, 0), endpoint_rps(r, 1),
          fmt_mb(r.get("idle_memory_mb")), fmt_mb(peak_memory(r)), fmt_ms(r.get("startup_ms")),
          seed_short(r.get("seed"))] for r in ok],
        set(range(1, 8))), ""]
    users = all_users(ok)
    if users:
        out += ["## p99 latency by simulated users", "", md_table(
            ["Users"] + [r["label"] for r in ok],
            [[f"{u:,}"] + [p99_cell(level_at(r.get("ramp"), u)) for r in ok] for u in users],
            set(range(len(ok) + 1))), ""]
        out += ["## CPU cores used", "", md_table(
            ["Users"] + [r["label"] for r in ok],
            [[f"{u:,}"] + [cpu_cell(level_at(r.get("ramp"), u)) for r in ok] for u in users],
            set(range(len(ok) + 1))), ""]
    if any(r.get("endpoints") for r in ok):
        labels = [x["label"] for x in next(r["endpoints"] for r in ok if r.get("endpoints"))]
        out += ["## Single endpoints (requests/second)", "", md_table(
            ["Request"] + [r["label"] for r in ok],
            [[label] + [endpoint_rps(r, i) for r in ok] for i, label in enumerate(labels)],
            set(range(1, len(ok) + 1))), ""]
    out += ["## Stacks and verification", "", md_table(
        ["Stack", "Runtime and framework", "Concurrency", "Seed checksum", "API parity", "Status"],
        [[r["label"], r["description"], r["concurrency"], check((r.get("conformance") or {}).get("ok")),
          check((r.get("parity") or {}).get("ok")) if r.get("parity") else "reference",
          r["status"] + (f": {r['error']}" if r["error"] else "")] for r in results]), ""]
    out += ["## When and how each backend was measured", "", md_table(SOURCE_HEADERS, source_rows(ok)), ""]
    out += ["## Method", "", method_note(meta), ""]
    return "\n".join(out)


# ---------------------------------------------------------------- html

CSS = """
.viz-root{color-scheme:light;--surface:#fcfcfb;--panel:#f4f3f0;--ink:#0b0b0b;--ink2:#52514e;--muted:#8a8984;
--rule:#e2e0da;--grid:#ecebe7;--warn:#b54708;%LIGHT%}
@media (prefers-color-scheme: dark){:root:where(:not([data-theme="light"])) .viz-root{color-scheme:dark;
--surface:#1a1a19;--panel:#242422;--ink:#ffffff;--ink2:#c3c2b7;--muted:#8f8e86;--rule:#383835;--grid:#2c2c2a;--warn:#f79009;%DARK%}}
:root[data-theme="dark"] .viz-root{color-scheme:dark;--surface:#1a1a19;--panel:#242422;--ink:#ffffff;--ink2:#c3c2b7;
--muted:#8f8e86;--rule:#383835;--grid:#2c2c2a;--warn:#f79009;%DARK%}
*{box-sizing:border-box}
body{margin:0}
.viz-root{background:var(--surface);color:var(--ink);min-height:100vh;
font:15px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1080px;margin:0 auto;padding:40px 20px 80px}
h1{font-size:28px;line-height:1.2;margin:0 0 6px;letter-spacing:-.01em}
h2{font-size:18px;margin:44px 0 12px;padding-top:18px;border-top:1px solid var(--rule)}
h3{font-size:15px;margin:28px 0 8px}
a{color:inherit;text-decoration-color:var(--muted);text-underline-offset:3px}
a:hover{text-decoration-color:var(--ink)}
.sub{color:var(--ink2);margin:0 0 24px}
.specs{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));background:var(--panel);
border:1px solid var(--rule);border-radius:10px;overflow:hidden;margin:0 0 8px}
.specs div{padding:10px 14px;border-right:1px solid var(--rule);border-bottom:1px solid var(--rule);margin:0 -1px -1px 0}
.specs dt{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.specs dd{margin:2px 0 0;font-size:14px}
.table-wrap{overflow-x:auto;margin:0 -4px}
table{border-collapse:collapse;width:100%;font-size:14px;font-variant-numeric:tabular-nums}
th,td{padding:8px 10px;border-bottom:1px solid var(--rule);text-align:left;vertical-align:middle;white-space:nowrap}
th{font-weight:600;color:var(--ink2);font-size:12px}
td.num,th.num{text-align:right}
td.wrap{white-space:normal;min-width:220px}
td code{font-size:12px;background:var(--grid);padding:0 3px;border-radius:3px}
.swatch{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:8px;vertical-align:-1px}
.bar{position:relative;min-width:140px}
.bar span{position:relative;z-index:1}
.bar i{position:absolute;left:4px;top:50%;height:6px;margin-top:9px;border-radius:0 3px 3px 0;opacity:.9}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:8px 32px}
.chart{position:relative;margin:8px 0 4px}
.chart svg{display:block;width:100%;height:auto;overflow:visible}
.chart text{fill:var(--ink2);font-size:12px}
.legend{display:flex;flex-wrap:wrap;gap:6px 18px;margin:0 0 10px;font-size:13px;color:var(--ink2)}
.tip{position:absolute;pointer-events:none;background:var(--panel);border:1px solid var(--rule);border-radius:8px;
padding:8px 10px;font-size:12px;box-shadow:0 4px 18px rgba(0,0,0,.12);display:none;min-width:160px;z-index:5}
.tip b{display:block;margin-bottom:4px;color:var(--ink)}
.tip div{display:flex;justify-content:space-between;gap:14px;color:var(--ink2)}
.note{color:var(--ink2);font-size:13px;max-width:820px}
.warn{border:1px solid var(--warn);border-radius:8px;padding:10px 14px;margin:14px 0;color:var(--warn)}
.bad{color:var(--warn)}
.status{font-size:13px}
footer{margin-top:48px;color:var(--muted);font-size:12px}
"""

SCRIPT = """
document.querySelectorAll('.chart[data-series]').forEach(function(el){
  var series=JSON.parse(el.dataset.series), xs=JSON.parse(el.dataset.xs), unit=el.dataset.unit||'';
  var svg=el.querySelector('svg'), tip=el.querySelector('.tip'), line=svg.querySelector('.cross');
  var box=JSON.parse(el.dataset.box);
  function fmt(v){ if(v==null) return '—'; return (v>=100?Math.round(v).toLocaleString():v.toFixed(v>=10?1:2))+unit; }
  svg.addEventListener('mousemove',function(ev){
    var r=svg.getBoundingClientRect(), sx=(ev.clientX-r.left)*box.w/r.width;
    var best=0; xs.forEach(function(x,i){ if(Math.abs(box.px[i]-sx)<Math.abs(box.px[best]-sx)) best=i; });
    line.setAttribute('x1',box.px[best]); line.setAttribute('x2',box.px[best]); line.style.display='';
    var rows=series.map(function(s){
      return '<div><span><i class="swatch" style="background:var(--s'+s.slot+')"></i>'+s.label+'</span><span>'+
        fmt(s.values[best])+'</span></div>';}).join('');
    tip.innerHTML='<b>'+xs[best].toLocaleString()+' users</b>'+rows; tip.style.display='block';
    var left=box.px[best]*r.width/box.w+14; if(left+180>r.width) left-=200; tip.style.left=left+'px'; tip.style.top='10px';
  });
  svg.addEventListener('mouseleave',function(){tip.style.display='none'; line.style.display='none';});
});
"""


def e(text) -> str:
    return html.escape(str(text))


def page(title: str, body: str) -> str:
    light = "".join(f"--s{i}:{l};" for i, (l, _) in enumerate(PALETTE))
    dark = "".join(f"--s{i}:{d};" for i, (_, d) in enumerate(PALETTE))
    css = CSS.replace("%LIGHT%", light).replace("%DARK%", dark)
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'><title>{e(title)}</title>"
            f"<style>{css}</style></head><body><div class='viz-root'><main>{body}"
            f"<footer>Generated by bench/run.py · backend-stack benchmark suite</footer></main></div>"
            f"<script>{SCRIPT}</script></body></html>")


def html_specs(meta: dict, run_details: bool = True, extra: list[tuple[str, str]] = ()) -> str:
    cells = "".join(f"<div><dt>{e(k)}</dt><dd>{e(v)}</dd></div>" for k, v in [*machine_rows(meta, run_details), *extra])
    return f"<dl class='specs'>{cells}</dl>"


def html_table(headers: list[str], rows: list[list[str]], numeric: set[int] = frozenset(),
               raw: bool = False, wrap: set[int] = frozenset()) -> str:
    def cls(i):
        c = ["num"] if i in numeric else []
        c += ["wrap"] if i in wrap else []
        return f" class='{' '.join(c)}'" if c else ""
    head = "".join(f"<th{cls(i)}>{e(h)}</th>" for i, h in enumerate(headers))
    body = "".join("<tr>" + "".join(f"<td{cls(i)}>{c if raw else e(c)}</td>" for i, c in enumerate(row)) + "</tr>"
                   for row in rows)
    return f"<div class='table-wrap'><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


def stack_name_cell(r: dict, link: bool = True) -> str:
    name = e(r["label"])
    if link and r.get("_link"):
        name = f"<a href='{e(r['_link'])}'>{name}</a>"
    return f"<span class='swatch' style='background:var(--s{r['slot'] % 8})'></span>{name}"


def bar_cell(value: float | None, max_value: float, slot: int, text: str) -> str:
    if value is None or not max_value:
        return e(text)
    pct = max(2.0, 100.0 * value / max_value)
    return (f"<div class='bar'><span>{e(text)}</span>"
            f"<i style='width:calc({pct:.1f}% - 8px);background:var(--s{slot % 8})'></i></div>")


def warnings_html(warnings: list[str]) -> str:
    return "".join(f"<p class='warn'><b>⚠ Warning:</b> {e(w)}</p>" for w in warnings)


def _nice_step(span: float) -> float:
    raw = span / 5 if span > 0 else 1
    power = 10 ** math.floor(math.log10(raw))
    return next(m * power for m in (1, 2, 2.5, 5, 10) if m * power >= raw)


def _fmt_tick(v: float, unit: str) -> str:
    if unit == " ms":
        return f"{v:g} ms" if v < 1000 else f"{v / 1000:g} s"
    if unit == " MB" and v >= 1024:
        return f"{v / 1024:.2f}".rstrip("0").rstrip(".") + " GB"
    return f"{v:,.0f}{unit}" if v >= 10 or v == 0 else f"{v:g}{unit}"


def line_chart(series: list[dict], xs: list[int], *, unit: str, log: bool = False, ref: float | None = None,
               ref_label: str = "", aria: str = "", legend: bool = True, height: int = 320, width: int = 900) -> str:
    """Lines over simulated-user levels. series: [{label, slot, values}]; None values are gaps."""
    values = [v for s in series for v in s["values"] if v is not None and (v > 0 or not log)]
    if not xs or not values:
        return ""
    w, h, left, right, top, bottom = width, height, 70, 20, 16, 44
    if log:
        lo = 10 ** math.floor(math.log10(max(min(values), 0.1)))
        hi = 10 ** math.ceil(math.log10(max(max(values), (ref or 0) * 2, lo * 10)))
        ticks, t = [], lo
        while t <= hi:
            ticks.append(t)
            t *= 10
        def py(v):
            return top + (h - top - bottom) * (1 - (math.log10(v) - math.log10(lo)) / (math.log10(hi) - math.log10(lo)))
    else:
        top_value = max(max(values), ref or 0) * 1.1
        step = _nice_step(top_value)
        hi = math.ceil(top_value / step) * step
        ticks = [i * step for i in range(int(round(hi / step)) + 1)]
        def py(v):
            return top + (h - top - bottom) * (1 - v / hi)
    x0, x1 = xs[0], xs[-1]
    def px(x):
        return left + (w - left - right) * ((x - x0) / (x1 - x0) if x1 > x0 else 0.5)
    parts = []
    for t in ticks:
        y = py(t)
        parts.append(f"<line x1='{left}' x2='{w - right}' y1='{y:.1f}' y2='{y:.1f}' stroke='var(--grid)'/>")
        parts.append(f"<text x='{left - 8}' y='{y + 4:.1f}' text-anchor='end'>{e(_fmt_tick(t, unit))}</text>")
    if ref is not None:
        y = py(ref)
        parts.append(f"<line x1='{left}' x2='{w - right}' y1='{y:.1f}' y2='{y:.1f}' stroke='var(--ink2)' "
                     f"stroke-dasharray='4 4' stroke-width='1'/>")
        parts.append(f"<text x='{w - right}' y='{y - 6:.1f}' text-anchor='end'>{e(ref_label)}</text>")
    for x in xs:
        parts.append(f"<text x='{px(x):.1f}' y='{h - bottom + 20}' text-anchor='middle'>{x:,}</text>")
    parts.append(f"<text x='{(left + w - right) / 2}' y='{h - 6}' text-anchor='middle'>simulated users</text>")
    for s in series:
        color = f"var(--s{s['slot'] % 8})"
        pts = [(px(x), py(v)) for x, v in zip(xs, s["values"]) if v is not None and (v > 0 or not log)]
        if not pts:
            continue
        path = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(pts))
        parts.append(f"<path d='{path}' fill='none' stroke='{color}' stroke-width='2' stroke-linejoin='round'/>")
        for x, y in pts:
            parts.append(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='4' fill='{color}' stroke='var(--surface)' "
                         f"stroke-width='2'/>")
    parts.append(f"<line class='cross' x1='0' x2='0' y1='{top}' y2='{h - bottom}' stroke='var(--muted)' "
                 f"style='display:none'/>")
    legend_html = ""
    if legend and len(series) > 1:
        legend_html = "<div class='legend'>" + "".join(
            f"<span><i class='swatch' style='background:var(--s{s['slot'] % 8})'></i>{e(s['label'])}</span>"
            for s in series) + "</div>"
    data = e(json.dumps([{"label": s["label"], "slot": s["slot"] % 8, "values": s["values"]} for s in series]))
    box = e(json.dumps({"w": w, "px": [round(px(x), 1) for x in xs]}))
    return (f"{legend_html}<div class='chart' data-series='{data}' data-xs='{e(json.dumps(xs))}' "
            f"data-unit='{e(unit)}' data-box='{box}'><svg viewBox='0 0 {w} {h}' role='img' aria-label='{e(aria)}'>"
            f"{''.join(parts)}</svg><div class='tip'></div></div>")


def capacity_chart(results: list[dict]) -> str:
    """Horizontal bars: users served at p99 ≈ 100 ms, sorted high to low."""
    rows = []
    for r in results:
        q, users = capacity(r.get("ramp") or [])
        if users is not None:
            rows.append((r, q, users))
    if not rows:
        return ""
    rows.sort(key=lambda t: -t[2])
    top = max(u for _, _, u in rows)
    w, bar_h, gap, label_w = 900, 22, 12, 190
    h = len(rows) * (bar_h + gap)
    parts = []
    for i, (r, q, users) in enumerate(rows):
        y = i * (bar_h + gap)
        width = max(4, (w - label_w - 90) * users / top)
        parts.append(f"<text x='{label_w - 12}' y='{y + bar_h / 2 + 4}' text-anchor='end'>{e(r['label'])}"
                     f"{' ⚠' if r.get('_busy') else ''}</text>")
        parts.append(f"<path d='M{label_w},{y} h{width - 4:.1f} a4,4 0 0 1 4,4 v{bar_h - 8} a4,4 0 0 1 -4,4 "
                     f"h{-(width - 4):.1f} z' fill='var(--s{r['slot'] % 8})'><title>{e(r['label'])}: "
                     f"{e(fmt_capacity(r.get('ramp')))} users</title></path>")
        parts.append(f"<text x='{label_w + width + 8:.1f}' y='{y + bar_h / 2 + 4}'>"
                     f"{e({'<': '< ', '>=': '≥ '}.get(q, '~'))}{users:,}</text>")
    return (f"<div class='chart'><svg viewBox='0 0 {w} {h}' role='img' "
            f"aria-label='Users served at p99 latency of about 100 ms'>{''.join(parts)}</svg></div>")


def series_for(results: list[dict], users: list[int], key: str) -> list[dict]:
    return [{"label": r["label"], "slot": r["slot"], "values": [ramp_value(r, u, key) for u in users]}
            for r in results if r.get("ramp")]


def summary_html(meta: dict, results: list[dict], title: str, subtitle: str) -> str:
    ok = [r for r in results if r["status"] == "ok"]
    users = all_users(ok)
    body = [f"<h1>{e(title)}</h1><p class='sub'>{e(subtitle)}</p>", html_specs(meta, run_details=False)]
    body.append(warnings_html(comparability(ok)))

    body.append("<h2>Users served at p99 ≈ 100 ms</h2>")
    body.append(capacity_chart(ok))
    body.append(html_table(
        ["Stack", "Users at p99 ≈ 100 ms", "Single contact req/s", "List page req/s", "Idle memory", "Peak memory",
         "Startup", "Seed"],
        [[stack_name_cell(r), e(fmt_capacity(r.get("ramp"))), e(endpoint_rps(r, 0)), e(endpoint_rps(r, 1)),
          e(fmt_mb(r.get("idle_memory_mb"))), e(fmt_mb(peak_memory(r))), e(fmt_ms(r.get("startup_ms"))),
          e(seed_short(r.get("seed")))] for r in ok], set(range(1, 8)), raw=True))

    if users:
        body.append("<h2>p99 latency as users grow</h2><p class='note'>Log scale. Hover for values. A missing point "
                    "means the stack's ramp ended at an earlier level. Stack names link to their detailed reports.</p>")
        body.append(line_chart(series_for(ok, users, "p99_ms"), users, unit=" ms", log=True, ref=CAPACITY_P99_MS,
                               ref_label="100 ms capacity line", aria="p99 latency by number of simulated users"))
        body.append(html_table(["Users"] + [r["label"] for r in ok],
                               [[f"{u:,}"] + [p99_cell(level_at(r.get("ramp"), u)) for r in ok] for u in users],
                               set(range(len(ok) + 1))))
        body.append("<h2>CPU cores used</h2><p class='note'>CPU-seconds per second during each measured window. "
                    "The dashed line is the core budget each server was given.</p>")
        body.append(line_chart(series_for(ok, users, "cpu_cores"), users, unit=" cores", ref=meta["cores"],
                               ref_label=f"core budget ({meta['cores']})", aria="CPU cores used by simulated users"))
        body.append(html_table(["Users"] + [r["label"] for r in ok],
                               [[f"{u:,}"] + [cpu_cell(level_at(r.get("ramp"), u)) for r in ok] for u in users],
                               set(range(len(ok) + 1))))

    if any(r.get("endpoints") for r in ok):
        body.append(f"<h2>Single endpoints</h2><p class='note'>Requests/second with {meta['endpoint_clients']} "
                    "clients and no pauses. Bars compare stacks within each row.</p>")
        labels = [x["label"] for x in next(r["endpoints"] for r in ok if r.get("endpoints"))]
        rows = []
        for i, label in enumerate(labels):
            vals = [ep_value(r, i) for r in ok]
            top = max((v for v in vals if v), default=0)
            rows.append([e(label)] + [bar_cell(v, top, r["slot"], fmt_int(v)) for v, r in zip(vals, ok)])
        body.append(html_table(["Request"] + [r["label"] for r in ok], rows, set(), raw=True))

    body.append("<h2>Memory</h2>")
    top = max([peak_memory(r) or 0 for r in ok] + [r.get("idle_memory_mb") or 0 for r in ok] + [1])
    body.append(html_table(
        ["Stack", "Idle", "Peak after a load level", "Processes"],
        [[stack_name_cell(r), bar_cell(r.get("idle_memory_mb"), top, r["slot"], fmt_mb(r.get("idle_memory_mb"))),
          bar_cell(peak_memory(r), top, r["slot"], fmt_mb(peak_memory(r))), e(fmt_int(r.get("processes")))]
         for r in ok], {3}, raw=True))

    body.append("<h2>Stacks and verification</h2>")
    body.append(html_table(
        ["Stack", "Runtime and framework", "Concurrency", "Seed checksum", "API parity", "Status"],
        [[stack_name_cell(r), e(r["description"]), e(r["concurrency"]),
          e(check((r.get("conformance") or {}).get("ok"))),
          e(check((r.get("parity") or {}).get("ok")) if r.get("parity") else "reference"),
          f"<span class='status{' bad' if r['status'] != 'ok' else ''}'>{e(r['status'])}"
          f"{': ' + e(r['error']) if r['error'] else ''}</span>"] for r in results],
        raw=True, wrap={1, 5}))
    body.append("<h2>When and how each backend was measured</h2><p class='note'>Each backend keeps only its "
                "latest benchmark; rerunning one replaces its results and rebuilds this page.</p>")
    body.append(html_table(SOURCE_HEADERS, source_rows(ok)))
    body.append(f"<h2>Method</h2><p class='note'>{e(method_note(meta))}</p>")
    return page(title, "".join(body))


def stack_html(r: dict) -> str:
    meta = r["run"]
    body = [f"<p class='note'><a href='../summary.html'>← All backends</a></p>",
            f"<h1>{stack_name_cell(r, link=False)}: benchmark results</h1>",
            f"<p class='sub'>{e(r['description'])}. {e(r['concurrency'])}."
            + (f" {e('; '.join(r['versions']))}." if r.get("versions") else "") + "</p>",
            html_specs(meta, extra=[("Other programs", load_text(r))])]
    if result_busy(r):
        body.append(warnings_html(["Other programs were using the CPU while this ran, so these results are noisy."]))
    if r["status"] != "ok":
        body.append(f"<p class='warn'><b>{e(r['status'].upper())}:</b> {e(r['error'])}</p>")
    body.append("<h2>Summary</h2>")
    body.append(html_table(["Metric", "Value"], summary_rows(r), {1}))

    if r.get("ramp"):
        users = [l["users"] for l in r["ramp"]]
        body.append("<h2>Simulated users</h2>")
        pct = [{"label": label, "slot": slot, "values": [l["result"].get("all", {}).get(key) for l in r["ramp"]]}
               for label, slot, key in (("p50", 0, "p50_ms"), ("p95", 1, "p95_ms"), ("p99", 2, "p99_ms"))]
        body.append("<h3>Latency percentiles</h3>")
        body.append(line_chart(pct, users, unit=" ms", log=True, ref=CAPACITY_P99_MS, ref_label="100 ms",
                               aria="Latency percentiles by number of simulated users"))
        one = lambda key: [{"label": r["label"], "slot": r["slot"], "values": [ramp_value(r, u, key) for u in users]}]
        body.append("<div class='grid2'><div><h3>Throughput (requests/second)</h3>")
        body.append(line_chart(one("req_s"), users, unit=" req/s", height=300, width=460, aria="Requests per second by users"))
        body.append("</div><div><h3>CPU cores used</h3>")
        body.append(line_chart(one("cpu_cores"), users, unit=" cores", ref=meta["cores"],
                               ref_label=f"budget ({meta['cores']})", height=300, width=460, aria="CPU cores by users"))
        body.append("</div><div><h3>Memory after each level</h3>")
        body.append(line_chart(one("memory_after_mb"), users, unit=" MB", height=300, width=460, aria="Memory by users"))
        body.append("</div></div>")
        body.append(html_table(RAMP_HEADERS, ramp_rows(r), set(range(9))))
        headers, rows = kind_rows(r)
        body.append("<h3>p99 by request type</h3><p class='note'>Which requests slow down first as load grows.</p>")
        body.append(html_table(headers, rows, set(range(1, len(headers)))))
        body.append(f"<p class='note'>{e(method_note(meta))}</p>")

    if r.get("endpoints"):
        body.append("<h2>Single endpoints</h2>")
        top = max((ep_value(r, i) or 0 for i in range(len(r["endpoints"]))), default=0)
        body.append(html_table(
            ["Request", "req/s", "p50", "p99", "Errors"],
            [[e(x["label"]), bar_cell(x["result"].get("all", {}).get("req_s"), top, r["slot"],
                                      fmt_int(x["result"].get("all", {}).get("req_s"))),
              e(fmt_ms(x["result"].get("all", {}).get("p50_ms"))), e(fmt_ms(x["result"].get("all", {}).get("p99_ms"))),
              e(fmt_int(x["result"].get("errors")))] for x in r["endpoints"]],
            {2, 3, 4}, raw=True))

    log = optimization_log(r)
    if log:
        headers, rows = log
        href = r.get("_log_href", "../../docs/optimization-log.md")
        body.append("<h2>Optimization history</h2>")
        body.append(f"<p class='note'>Every change tried on this stack, oldest first, from "
                    f"<a href='{e(href)}'>the optimization log</a>. Status: kept, reverted, no effect "
                    f"(measured, didn't help) or open (not acted on yet).</p>")
        body.append(html_table(headers, [[md_inline_html(c) for c in row] for row in rows],
                               raw=True, wrap={1, 2}))
    return page(f"{r['label']}: benchmark results", "".join(body))


# ---------------------------------------------------------------- files

def write_stack(root: Path, r: dict) -> None:
    """results/<stack>/report.{md,html} from the stack's result (which carries its run details)."""
    d = root / r["name"]
    d.mkdir(parents=True, exist_ok=True)
    r = {**r, "_log_href": os.path.relpath(OPTIMIZATION_LOG, d)}
    (d / "report.md").write_text(stack_markdown(r))
    (d / "report.html").write_text(stack_html(r))


def load_results(root: Path) -> list[dict]:
    results = []
    for path in root.glob("*/result.json"):
        r = json.loads(path.read_text())
        if "run" in r:
            results.append(r)
    return sorted(results, key=lambda r: r["port"])


def write_summary(root: Path) -> Path | None:
    """results/summary.{md,html,json}: every backend's current result, compared."""
    results = [annotate(r, f"{r['name']}/report.html") for r in load_results(root)]
    if not results:
        return None
    newest = max((r["_meta"] for r in results), key=lambda m: m["started_at"])
    title = "Backend benchmark: comparison"
    ok = sum(r["status"] == "ok" for r in results)
    (root / "summary.json").write_text(json.dumps({"results": [
        {k: v for k, v in r.items() if not k.startswith("_")} for r in results]}, indent=2))
    (root / "summary.md").write_text(summary_markdown(newest, results, title))
    (root / "summary.html").write_text(summary_html(
        newest, results, title, f"{ok} backends behind one API. Each backend's latest benchmark; the table at the "
        "bottom shows when and under what conditions each one was measured."))
    return root / "summary.html"


def rerender(root: Path) -> Path | None:
    """Rebuild every backend report and the summary from the JSON; nothing is re-measured."""
    for r in load_results(root):
        write_stack(root, r)
    return write_summary(root)
