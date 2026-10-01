# Backend Requirements Specification

This folder is the complete, language-neutral specification for an address-book
backend in this repository. It was derived from the reference implementation in
`backend/rust/` (Rust + Axum + rusqlite). Any new backend (`backend/<stack>/`)
must be buildable from these documents alone, and must be indistinguishable from
the Rust server to the frontend, the load generator and the parity check.

The repository exists to **benchmark backend stacks on equal terms**. So the spec
covers more than behavior: it also pins down the work each request does (schema,
SQL, SQLite tuning, caching, compression). Differences between stacks should come
from the language runtime and web framework, not from one stack doing less work.

## How to use this spec

If you are an agent implementing a new backend, read the documents in order:

| # | Document | Covers |
| --- | --- | --- |
| 1 | [01-architecture.md](01-architecture.md) | Process model, configuration, startup, database access, static files, shutdown, logging |
| 2 | [02-database.md](02-database.md) | Schema, migrations, SQLite pragmas, WAL checkpointing, full-text search, the canonical SQL |
| 3 | [03-api.md](03-api.md) | Every endpoint: request, response, validation, errors, edge cases |
| 4 | [04-caching-and-http.md](04-caching-and-http.md) | Response cache, `X-Fresh`, ETags and 304s, gzip, headers |
| 5 | [05-seeder.md](05-seeder.md) | The deterministic data generator, specified exactly |
| 6 | [06-verification.md](06-verification.md) | Parity check, seed checksum, benchmark integration, acceptance checklist |
| 7 | [07-containers.md](07-containers.md) | Docker mode: Dockerfile rules, running and measuring stacks in containers |

Then build the backend, register it with the benchmark suite (a `bench.json`
manifest, see [`bench/README.md`](../../bench/README.md#adding-a-backend)), and
verify it against [06-verification.md](06-verification.md). `python3 bench/run.py
--stacks <stack> --profile quick` runs the seed checksum and the parity check for
you. The work is done only when every item on the acceptance checklist passes.

For performance, read [`docs/optimizing.md`](../optimizing.md) before tuning
anything. It has the method, the pitfalls, and the bottlenecks every stack so
far has hit. Each stack's README records what was tried there.

## Requirement language

- **MUST** / **MUST NOT**: required for conformance. The parity check, the frontend
  or the benchmark depends on it, or leaving it out would make the comparison unfair.
- **SHOULD**: expected. Deviate only for a concrete reason, and write the reason
  down in the stack's code or README.
- **MAY**: left to the implementation.

Requirements have IDs such as `API-12` or `DB-4` so reviews and commits can cite them.

## Summary of what a backend is

- An HTTP/1.1 JSON API under `/api`, with 13 routes (see [03-api.md](03-api.md)).
- One SQLite database file, with its schema defined by the shared SQL files in
  `backend/migrations/`.
- Hand-written SQL that matches the reference queries (the ORM variant is the one
  deliberate exception).
- An in-process response cache for expensive reads. Other users may see a write up
  to about 1 s late; the user who made it sees it immediately.
- gzip (level 6) on responses over 32 bytes.
- Serving the built Vue frontend (`frontend/dist`) as a single-page app, when it
  exists.
- A seeder CLI that generates the same fake contacts, byte for byte, as every other
  stack.

## Existing implementations and ports

| Stack | Folder | Port |
| --- | --- | --- |
| Rust (reference) | `backend/rust/` | 7878 |
| Python | `backend/python/` | 7879 |
| Node | `backend/node/` | 7880 |
| Rails | `backend/rails/` | 7881 |
| Rails + ActiveRecord | `backend/rails/` (`RAILS_DATA=activerecord`) | 7882 |
| Go | `backend/go/` | 7883 |
| C# | `backend/csharp/` | 7884 |
| C | `backend/c/` | 7885 |
| Java (Spring Boot) | `backend/java-spring/` | 7886 |

A new stack takes the next free port (7887 and up).

## When the spec and the reference disagree

The Rust code is the reference. If this spec and `backend/rust/` disagree on
anything the parity check can observe, the Rust behavior wins, and this spec
should be fixed. Framework-level behavior, where frameworks legitimately differ (such as the
status for malformed JSON), is specified as a set of allowed answers in
[03-api.md §7](03-api.md#7-framework-level-behavior), and the parity check's
contract section tests it.
