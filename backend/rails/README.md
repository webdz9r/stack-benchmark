# Rails

Ruby 4.0 (YJIT), Rails 8.1 in API mode, Puma, and the sqlite3 gem. There are
two data layers in one app, chosen by `RAILS_DATA`:

- **`raw`** (the default, `RawStore`): the spec's SQL sent directly through the
  sqlite3 gem, like the other stacks.
- **`activerecord`** (`ActiveRecordStore`): ActiveRecord models with
  associations, scopes, `includes` and callbacks, written the usual Rails way.
  It's the one stack the spec allows to use an ORM (DB-15).

## Run

```sh
bundle install                                # Ruby 4.0.1 is pinned in .ruby-version
RAILS_ENV=production SECRET_KEY_BASE_DUMMY=1 bin/rails runner script/seed.rb 110000   # optional
RAILS_ENV=production SECRET_KEY_BASE_DUMMY=1 RUBY_YJIT_ENABLE=1 \
  WEB_CONCURRENCY=4 RAILS_MAX_THREADS=1 bundle exec puma                              # :7881
# The ActiveRecord variant, on its own database copy:
RAILS_DATA=activerecord DATABASE_PATH=data/address-book-ar.db PORT=7882 RAILS_ENV=production \
  SECRET_KEY_BASE_DUMMY=1 RUBY_YJIT_ENABLE=1 WEB_CONCURRENCY=4 RAILS_MAX_THREADS=1 bundle exec puma
```

| Variable | Default | |
| --- | --- | --- |
| `DATABASE_PATH` | `data/address-book.db` | SQLite file (both data layers) |
| `PORT` | `7881` | listen port (bound to 127.0.0.1) |
| `STATIC_DIR` | `../../frontend/dist` | built frontend (Rails' public folder) |
| `RAILS_DATA` | `raw` | `raw` or `activerecord` |
| `WEB_CONCURRENCY` | `4` | Puma worker processes (the core budget) |
| `RAILS_MAX_THREADS` | `1` | threads per worker (see Optimizing) |

## Notes and deviations

- Each Puma worker has its own response cache, and detects writes by any
  process through `PRAGMA data_version` (CACHE-10).
- The busy timeout is set with the sqlite3 gem's `busy_handler_timeout`, which
  releases Ruby's lock while waiting (DB-6 allows this).
- **DB-2 not applied:** the sqlite3 gem ships a precompiled SQLite. Compiling the
  gem from source with `SQLITE_DEFAULT_MEMSTATUS=0` would apply it.
- gzip (`Rack::Deflater`) sits in front of `ActionDispatch::Static`, so static
  files are compressed too, and `Rack::ContentLength` supplies the length for the
  32-byte minimum.
- A JSON body without a `Content-Type` is accepted, and a wrong method returns 404
  (the `/api` catch-all). Both are allowed by the spec.
- The ActiveRecord variant rebuilds the search row on every save, including a
  favorite toggle: that's the cost of using callbacks.

## Optimizing

Findings (see also [`docs/optimizing.md`](../../docs/optimizing.md)):

- **The sqlite3 gem holds the GVL while a query runs.** Four threads running
  the same query took 4x as long as one (5.55 s vs 1.35 s): queries never
  overlap within a process. So a worker is limited to one core, SQLite
  included, and under load the 4 workers sit at exactly ~4.0 cores.
- **One thread per worker** (`RAILS_MAX_THREADS=1`). Extra threads only queue
  behind the GVL and add switching. Raw data layer: p99 at 3,000 users went
  from ~590 ms to ~140 ms, and at 2,500 from ~138 ms to ~54 ms; in the suite,
  capacity went from ~2,250 to ~3,000 users. ActiveRecord: trials suggested
  ~5% more throughput, but a clean suite run matched the 4-thread result
  (~1,950 users, p99 ~104 ms at 2,000, ~1,420 req/s peak), so for it the
  setting is neutral. It stays at 1 because both variants share `puma.rb`.
- **Where the CPU goes** (ActiveRecord, 2,000 users, macOS `sample`): 58%
  SQLite, 15% Ruby VM, 14% malloc, 6% GC. Most SQLite time is search misses
  (the filtered list, its count and the letters query), and each of the 4
  workers misses on its own because each has its own cache.
- **Didn't help:** GC tuning (`RUBY_GC_HEAP_*_INIT_SLOTS`, larger malloc
  limits) and removing middleware this API doesn't need (`Rack::Runtime`,
  `RequestId`, `RemoteIp`, `Sendfile`, `Rails::Rack::Logger`). Neither moved
  throughput (~1,430 req/s either way), because Ruby's overhead isn't the limit.
- **Not applicable here:** turning off SQLite's memory statistics. The gem's
  SQLite has them on (no `DEFAULT_MEMSTATUS=0`, and `sqlite3_config` isn't
  exported for Fiddle), but with the GVL held only one thread is ever inside
  SQLite, so the lock is never contended.
- **The lever that's left:** a driver that releases the GVL during queries
  (such as `extralite`) would let one process run queries on several threads
  and share one cache. That works for the raw data layer only; ActiveRecord's
  SQLite adapter needs the sqlite3 gem.
- **Tools:** macOS `sample <worker pid> 6` for native CPU; an
  `ActiveSupport::Notifications.subscribe("sql.active_record")` probe that
  times queries by SQL shape (dumped on a signal); `ps -o pcpu` per worker.

## Docker

`Dockerfile` builds this stack on Debian 13 slim with the same settings as
native ([07-containers.md](../../docs/requirements/07-containers.md)). One image serves both variants; `RAILS_DATA` picks the data layer, and `HOST=0.0.0.0` makes Puma listen outside the container.
Run it with `docker compose --profile rails up --build` from the repo root, or
benchmark it with `python3 bench/run.py --mode docker --stacks rails`.

## Verify and benchmark

```sh
python3 bench/run.py --stacks rails,rails-ar --profile quick   # from the repo root
```

The report must show **pass** for the seed checksum (VER-1) and API parity
(VER-2). The spec is in [`docs/requirements/`](../../docs/requirements/README.md).
