# Contributing

Thanks for taking a look. Feedback and pull requests are welcome, especially
from people who know one of these stacks well. Getting set up takes about ten
minutes with Docker: see [`DEVELOPER.md`](DEVELOPER.md).

## What's most useful

- **Performance:** a setting, library or pattern that makes a stack faster while
  doing the same work.
- **Code quality:** whether a backend reads like idiomatic code in its language
  and framework. Every backend was written by AI from the spec, and judging that
  code is one of the project's goals.
- **Correctness:** anything a backend gets wrong that the parity check misses.
- **New stacks:** a backend in a language or framework that isn't here yet.

Not sure if something is worth a pull request? Open an issue first.

## Ground rules

1. **Same work, same rules.** Every backend implements
   [`docs/requirements/`](docs/requirements/README.md): the same API, SQL,
   SQLite settings, cache and gzip, on a 4-core budget. A change that's faster
   because it skips work the spec requires isn't a speed-up. If you think the
   spec itself should change, say why in the PR; it applies to every stack.
2. **The checks must pass.** `python3 bench/run.py --stacks <stack> --profile quick`
   must show **pass** for the seed checksum (VER-1) and API parity (VER-2).
3. **Show numbers for performance changes.** Include before and after from
   `python3 bench/run.py --stacks <stack>` (standard profile), on the same
   machine, from runs that weren't flagged busy. Say which mode you used
   (Docker, the default, or `--mode native`) and what machine it was.
4. **One change per PR**, so its effect can be measured on its own.
5. **Write down what you learned** in the stack's README, under **Optimizing**:
   what helped, and what you tried that didn't.
6. **Don't commit benchmark output** unless a maintainer asks for it: the
   published results in `results/` come from one machine so they stay
   comparable. Attach your `summary.md` to the PR instead.

## Adding a backend

Build it from the spec, not from the other backends, and follow the acceptance
checklist in [06-verification.md](docs/requirements/06-verification.md):
seed checksum, parity, a `Dockerfile` per
[07-containers.md](docs/requirements/07-containers.md), a `bench.json`, the
next free port, and a short README. `CLAUDE.md` has the details. Using an AI
assistant to write it is fine (that's how the others were written); you're
responsible for it passing the checks.

## Licence

By contributing, you agree that your contributions are licensed under the
[MIT License](LICENSE), like the rest of the project.
