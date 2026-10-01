# Results

`bench/run.py` writes here. Each backend has **one current result**, and
rerunning a backend replaces it:

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
```

Backends are often measured at different times, so each `result.json` records
its own conditions. The summary shows them per backend, and warns when results
aren't comparable: a different machine, profile or core budget, or a busy
machine. `.cache/` holds the generated dataset, and is reused between runs.

Everything in this folder except this README and `.gitignore` is **git-ignored**.
See [`bench/README.md`](../bench/README.md) for how to run the suite.
