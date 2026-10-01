# Results

`bench/run.py` writes here. Each backend has **one current result**, and
rerunning a backend replaces it. Docker mode (the default) writes to this
folder; native mode (`--mode native`) writes the same layout to `native/`.

```
results/
  summary.html   compare every backend (self-contained; open it or share it)
  summary.md     the same tables as Markdown
  summary.json   every backend's current result, machine-readable
  <stack>/
    report.html  that backend in detail: latency percentiles, throughput, CPU and memory charts
    report.md
    result.json  its measurements, plus the machine, profile, core budget, date and background load
    ramp-<users>.json, *.log   raw load-test output and logs
  native/        the same, from native-mode runs
```

Backends are often measured at different times, so each `result.json` records
its own conditions. The summary shows them per backend, and warns when results
aren't comparable: a different machine, profile or core budget, or a busy
machine. `.cache/` holds the generated dataset, and is reused between runs.

## Published results

The reports committed here (Docker mode, and native mode in `native/`) are the
**reference results**, measured on the maintainer's machine: an Apple M5 Max (18 cores: 6 Super, 12 Performance),
36 GB, macOS 27.0, on AC power, with every server held to a 4-core budget.
Each report starts with these specs. Start with [`summary.md`](summary.md),
or download `summary.html` for the charts.

Your machine will give different absolute numbers. Run the suite yourself to
compare, then commit the reports only if you're updating the reference results
on the same machine.

Not committed: `.cache/` (the ~80 MB generated dataset), `.work/` (databases
used during a run) and the `*.log` files, which contain absolute local paths.
See [`bench/README.md`](../bench/README.md) for how to run the suite.
