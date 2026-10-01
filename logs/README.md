# Logs

`bench/run.py` appends its progress to **`logs/bench.log`**: which backend is
building, being verified or under load, warnings about other programs using the
CPU, and where the reports were written. Each run starts with a header line.
Follow a run with:

```sh
tail -f logs/bench.log
```

Per-backend logs (server output, builds, the seeder, parity) are kept with that
backend's results, in `results/<stack>/`.

Everything here except this README and `.gitignore` is git-ignored.
