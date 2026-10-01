#!/usr/bin/env python3
"""Rebuild the benchmark reports from the result JSON; nothing is re-measured.

    python3 bench/report.py              # results/: every backend's report and the summary
    python3 bench/report.py <folder>     # the same for another results folder (e.g. from --out)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from suite import report  # noqa: E402
from suite.runner import RESULTS  # noqa: E402

if __name__ == "__main__":
    if len(sys.argv) > 2 or (len(sys.argv) == 2 and sys.argv[1].startswith("-")):
        raise SystemExit(__doc__)
    root = Path(sys.argv[1]).resolve() if len(sys.argv) == 2 else RESULTS
    path = report.rerender(root)
    print(f"wrote {path}" if path else f"no backend results found in {root}")
