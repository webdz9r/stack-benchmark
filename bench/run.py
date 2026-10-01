#!/usr/bin/env python3
"""Run the backend benchmark suite and write reports to results/.

By default every stack runs in its Docker container (docs/requirements/07-containers.md),
so all you need is Docker and Python 3.10+.

    python3 bench/run.py                          # every stack, standard profile, in Docker
    python3 bench/run.py --stacks go,rust         # just these stacks
    python3 bench/run.py --profile quick          # a fast smoke run
    python3 bench/run.py --list                   # show the registered stacks
    python3 bench/run.py --mode native            # with each stack's own toolchain (results/native/)

Native mode also needs a Rust toolchain (for the load generator) and each
stack's toolchain; stacks whose tools are missing are skipped and reported as
such. See bench/README.md.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from suite import runner, stacks  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stacks", help="comma-separated stack names (default: all)")
    parser.add_argument("--profile", choices=runner.PROFILES, default="standard")
    parser.add_argument("--levels", help="comma-separated user counts for the ramp, e.g. 1000,2000,4000")
    parser.add_argument("--cores", type=int, default=4, help="core budget per server (default 4)")
    parser.add_argument("--dataset", type=int, default=110_000, help="contacts in the benchmark dataset")
    parser.add_argument("--stop-p99", type=float, default=2000, help="end a stack's ramp once p99 exceeds this (ms)")
    parser.add_argument("--reference", default="rust", help="stack used for the dataset and the parity check")
    parser.add_argument("--out", type=Path, help="results folder (default: results/<date>_<cpu>)")
    parser.add_argument("--notes", default="", help="free text recorded in the reports")
    parser.add_argument("--mode", choices=("docker", "native"), default="docker",
                        help="run each stack in its Docker container (default; results/) or with its "
                             "native toolchain on this machine (results/native/)")
    parser.add_argument("--loadgen", choices=("host", "network"), default="network",
                        help="docker mode: run the load generator in a container on the Docker network (default), "
                             "or on the host against published ports. On macOS, published ports go through "
                             "Docker Desktop's port forwarder, which caps fast endpoints well below the server")
    parser.add_argument("--wait-quiet", type=int, default=0, metavar="MIN",
                        help="before each stack, wait up to MIN minutes for other programs to go quiet")
    parser.add_argument("--memory", default="4g", help="docker mode: memory limit per server container (default 4g)")
    for step in ("build", "parity", "conformance", "endpoints", "ramp", "seed"):
        parser.add_argument(f"--skip-{step}", action="store_true", help=f"skip the {step} step")
    parser.add_argument("--list", action="store_true", help="list registered stacks and exit")
    args = parser.parse_args()

    all_stacks = stacks.discover()
    if args.list:
        for s in all_stacks:
            missing = s.missing_tools(args.mode)
            state = f"missing {', '.join(missing)}" if missing else "ready"
            if args.mode == "docker" and not s.docker:
                state = "no docker block"
            print(f"{s.name:<10} :{s.port}  {s.label:<22} {state:<18} {s.dir.relative_to(stacks.ROOT)}")
        return

    selected = all_stacks
    if args.stacks:
        names = [n.strip() for n in args.stacks.split(",") if n.strip()]
        unknown = [n for n in names if n not in {s.name for s in all_stacks}]
        if unknown:
            raise SystemExit(f"unknown stack(s): {', '.join(unknown)} (see --list)")
        selected = [s for s in all_stacks if s.name in names]

    profile = runner.PROFILES[args.profile]
    if args.levels:
        profile.levels = sorted(int(x) for x in args.levels.split(","))

    opts = runner.Options(
        profile=profile, cores=args.cores, dataset=args.dataset, reference=args.reference,
        stop_p99_ms=args.stop_p99, out=args.out, notes=args.notes,
        mode=args.mode, loadgen=args.loadgen, memory=args.memory, wait_quiet=args.wait_quiet,
        build=not args.skip_build, parity=not args.skip_parity, conformance=not args.skip_conformance,
        endpoints=not args.skip_endpoints, ramp=not args.skip_ramp, seed=not args.skip_seed,
    )
    try:
        runner.run(selected, all_stacks, opts)
    except BaseException as e:  # also record crashes and Ctrl-C in logs/bench.log
        if not isinstance(e, SystemExit) or e.code not in (0, None):
            runner.log(f"run stopped: {type(e).__name__}: {e}")
        raise


if __name__ == "__main__":
    main()
