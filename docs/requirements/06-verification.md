# 06 — Verification, benchmark integration and acceptance

A backend is done when every item in §5 passes. Run all commands from the repo
root unless a step says otherwise.

## 1. Seed checksum (data parity)

Seed an empty database with 10,000 contacts, then hash its contents, leaving out
the timestamps, with [`seed-checksum.sql`](seed-checksum.sql). The query covers
contacts, emails, phones, addresses, tags, tag links **and the FTS rows**.

```sh
cd backend/<stack>
DATABASE_PATH=/tmp/seed-check.db <seeder> 10000
sqlite3 /tmp/seed-check.db < ../../docs/requirements/seed-checksum.sql | shasum -a 256
```

- **VER-1** The hash MUST be:

```
4757200eff847274560a4359166b3c6977b0fb45b0bd5f7286c11a53a91fc86a
```

Every stack's seeder produces it: Rust, Go, C#, Node, Python, Rails and
Rails + ActiveRecord. If it differs, compare
`sqlite3 … < seed-checksum.sql` line by line against the Rust seeder's output. The
first differing contact tells you which random draw went wrong.

## 2. API parity check

`bench/parity.py` checks a candidate against the Rust server (`:7878`) in two
parts:

1. **Identical responses.** 71 requests go to both servers, and the status codes
   and parsed JSON must match. Ids and timestamps are ignored, but only in the
   write checks. The requests cover reads, paging edge cases, 16 search strings
   (including the tokenizer cases from DB-12), filters, the letter index, creates
   (including a row without `value`, API-U1), every validation error, tag
   conflicts and 404s. Every request sends `X-Fresh`.
2. **Contract checks.** 21 checks, each run against **both** servers (42 in all),
   so a failing reference shows up as well. They cover:
   - framework-level statuses ([03-api.md §7](03-api.md#7-framework-level-behavior))
   - `/api/health` being `text/plain`, and unknown `/api` paths giving a JSON 404
   - ETags on cached responses only, and an empty 304 on revalidation
   - gzip with `Vary` at 32 bytes and over, and no gzip under 32 bytes
   - when a frontend is built: the SPA fallback for deep links, and gzipped
     static files

The benchmark suite runs this for every stack. To run it by hand, both servers
must serve **identical data**:

```sh
sqlite3 backend/rust/data/address-book.db ".backup backend/<stack>/data/address-book.db"
# start Rust on :7878 and the candidate on its port, then:
python3 bench/parity.py http://127.0.0.1:<port>/api
```

- **VER-2** The output MUST end with
  `71 identical, 0 mismatched; 42/42 contract checks passed` (38/38 when neither
  server has a built frontend, so the two frontend checks are skipped).
- The check creates contacts on both servers and deletes them again. If a run
  aborts, re-copy the database.

Still check these by hand, since they depend on timing or a browser:

| Check | Expected |
| --- | --- |
| Staleness: PUT a contact, then GET a filtered list without and with `X-Fresh` | with `X-Fresh`: the new data at once; without: the new data within about 1 s |
| Frontend: `cd frontend && npm run dev` with the Vite proxy pointed at the stack's port | browse, search, jump through A–Z, edit, tag: all work |

## 3. Load generator smoke test

```sh
cd loadtest && cargo build --release
./target/release/loadtest url=http://127.0.0.1:<port> users=500 think=3000 duration=20 edits=5
```

- **VER-3** No errors reported. The load generator follows the UI's real request
  mix (35% scroll or A–Z jump, 30% typed search, 25% open a contact, 5% switch view,
  5% edit and save), sends `If-None-Match` and `X-Fresh` like a browser, and PUTs
  back full contacts with `tag_ids` added.

## 4. Benchmark integration

- **VER-4** Register the stack with the benchmark suite by adding
  `backend/<stack>/bench.json`: name, label, port, required tools, build, start
  and seed commands, and the environment that applies the core budget through
  `{cores}` (ARCH-10). The format and a full example are in
  [`bench/README.md`](../../bench/README.md#adding-a-backend). Then check it with
  `python3 bench/run.py --stacks <stack> --profile quick`: the stack's report must
  show **pass** for both the seed checksum (VER-1) and API parity (VER-2). The
  suite runs both checks itself.
- **VER-5** Add the stack to the root `README.md`: the "Results" table (once a
  clean standard-profile run exists), the README links under "Running it", and
  the repository layout. If optimizing it taught something new, add a row to
  "What we learned about performance".
- **VER-6** Give the stack its own short README with the run commands and the
  environment variables, and with anything the spec lets it do differently (for
  example, no `SQLITE_DEFAULT_MEMSTATUS=0`, or cached gzip bodies). It SHOULD
  also have an **Optimizing** section: what was measured, what helped, what
  didn't, and the profiling tools that work for this runtime. Record the things
  that didn't help too, so nobody tries them again blind.
- **VER-7** Before publishing a new stack's results, compare it with the
  existing stacks and investigate any large gap. It SHOULD be within reach on
  single-endpoint throughput (`loadtest endpoint=...`). If it falls well behind
  on the simulated-user ramp, find out why before accepting the number. Each
  stack so far had at least one avoidable bottleneck, usually one of the
  "Check these first" items in [`docs/optimizing.md`](../optimizing.md): a
  global SQLite lock, a cache that rejects or duplicates entries, or blocking
  work on the event loop. The fix must keep VER-1 and VER-2 passing and must
  not skip work the spec requires.

## 5. Acceptance checklist

Architecture ([01](01-architecture.md))
- [ ] Lives in `backend/<stack>/`; `data/` and build output are git-ignored
- [ ] Reads `DATABASE_PATH`, `BIND_ADDR`/`PORT`, `STATIC_DIR`, `DB_READERS`, and has a concurrency knob
- [ ] One serialized writer connection plus a read-only reader pool; no SQLite calls on the event loop
- [ ] Reader threads in one process rather than worker processes, where the runtime can (ARCH-11)
- [ ] Serves `frontend/dist` as an SPA; unknown `/api/*` paths → JSON 404; no CORS

Database ([02](02-database.md))
- [ ] Applies `backend/migrations/*.sql` in order, tracked with `PRAGMA user_version`
- [ ] All 8 pragmas on every connection
- [ ] WAL checkpoint task every 5 s (PASSIVE, then TRUNCATE past 16,384 pages with a 50 ms busy timeout)
- [ ] Canonical SQL; tag filter uses `IN (subquery)`; FTS row rebuilt in the same transaction as every contact write
- [ ] `fts_query` word characters are Unicode Letters, Marks and Numbers (per code point) plus `@ . '`
- [ ] `PRAGMA compile_options` through the stack's driver: memory statistics off (`DEFAULT_MEMSTATUS=0`, or `SQLITE_CONFIG_MEMSTATUS` at startup), no `ENABLE_MEMORY_MANAGEMENT`, and C flags that keep `-O2` (DB-2)

API ([03](03-api.md))
- [ ] All 13 routes, with their status codes (201, 204)
- [ ] `limit` clamped to [1, 200], negative `offset` → 0, echoed back
- [ ] Letter index folds `~` into `#`
- [ ] Validation order and messages exactly as specified
- [ ] Framework-level errors use the allowed status codes, and never 500

Cache and HTTP ([04](04-caching-and-http.md))
- [ ] The cached endpoints and keys as specified, with normalized search in the key
- [ ] 64 MiB, 30 s TTL, 1 s published generation, `X-Fresh` → live generation
- [ ] LRU eviction that admits every new entry, and expired or evicted entries free their bytes (CACHE-5)
- [ ] Multi-process: generation from `PRAGMA data_version`
- [ ] `ETag` and `Cache-Control: no-cache` on cached responses only; `If-None-Match` → 304
- [ ] gzip only, level 6, ≥ 32 bytes

Seeder ([05](05-seeder.md))
- [ ] One transaction, the same insert path, `wal_checkpoint(TRUNCATE)` at the end
- [ ] **VER-1** seed checksum matches

Verification (this document)
- [ ] **VER-2** `71 identical, 0 mismatched; 42/42 contract checks passed`
- [ ] **VER-3** load test smoke run without errors
- [ ] **VER-4/5/6** `bench.json` manifest added, quick profile passes, READMEs updated (with an Optimizing section)
- [ ] **VER-7** compared with the existing stacks; any large gap investigated ([`docs/optimizing.md`](../optimizing.md))

Containers ([07](07-containers.md))
- [ ] `backend/<stack>/Dockerfile`: repo-root context, multi-stage, Debian 13 slim runtime, no budget variables (CTR-1..5)
- [ ] Repository layout under `/app`, `/app/sqlite-version` written, entrypoint `serve` / `seed <count>` (CTR-6, 7, 9)
- [ ] `docker` block in `bench.json`; listens on `0.0.0.0` in the container (CTR-10, 14)
- [ ] VER-1 and VER-2 pass in Docker mode: `bench/run.py --stacks <stack> --profile quick` (Docker is the default)
- [ ] VER-1 and VER-2 also pass natively: the same with `--mode native`
