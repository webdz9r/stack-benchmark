# C#

.NET 10, ASP.NET Core minimal APIs, `Microsoft.Data.Sqlite`, and
source-generated System.Text.Json.

## Run

```sh
dotnet build -c Release
dotnet bin/Release/net10.0/AddressBook.dll seed 110000                        # optional: fake contacts
DOTNET_PROCESSOR_COUNT=4 DB_READERS=4 dotnet bin/Release/net10.0/AddressBook.dll   # :7884
```

| Variable | Default | |
| --- | --- | --- |
| `DATABASE_PATH` | `data/address-book.db` | SQLite file |
| `BIND_ADDR` | `127.0.0.1:7884` | listen address |
| `STATIC_DIR` | `../../frontend/dist` | built frontend |
| `MIGRATIONS_DIR` | `../migrations` | shared migrations, read at runtime |
| `DB_READERS` | CPU count | read connections |
| `DOTNET_PROCESSOR_COUNT` | CPU count | the core budget (thread pool and GC heaps) |

## Notes and deviations

- **DB-2 at runtime:** the SQLite library comes prebuilt with SQLitePCLRaw, so
  `SQLITE_DEFAULT_MEMSTATUS=0` can't be compiled in. `Db.cs` calls
  `sqlite3_config(SQLITE_CONFIG_MEMSTATUS, 0)` before the first connection
  instead. Without it, the global malloc mutex serializes the readers and p99 at
  4,000 users is about 30x worse.
- Microsoft.Data.Sqlite's own pooling is off; `Db.cs` keeps its connections open,
  with their pragmas set and their prepared commands cached. The driver also
  retries `SQLITE_BUSY` up to its command timeout, on top of the 5 s busy timeout.
- A JSON body without a `Content-Type` is accepted (a small middleware, before
  routing), and a non-integer id or a wrong method returns 404. All are allowed
  by the spec (03-api.md §7).
- Responses under 32 bytes aren't compressed: `MinimumSizeCompressionProvider`
  checks the Content-Length that the cache and error paths set.

## Optimizing

- **SQLite memory statistics** (see Notes): the prebuilt e_sqlite3 keeps them
  on, and with 4 reader threads the global malloc mutex made queries average
  2–3 ms with 100 ms+ outliers. `Db.cs` turns them off at startup. That moved
  C# from ~3,250 users to 6,000+ (p99 ~15 ms at 6,000). Check the build with
  `PRAGMA compile_options` or by loading
  `bin/Release/net10.0/runtimes/<rid>/native/libe_sqlite3.dylib` and calling
  `sqlite3_compileoption_get`. It has no `ENABLE_MEMORY_MANAGEMENT`.
- **Cache byte accounting:** entries dropped for being past their TTL now
  subtract their size; before, ~20% of the 64 MiB went to dead entries.
- **Ruled out:** thread-pool starvation (`DOTNET_ThreadPool_ForceMinWorkerThreads=0x10`
  made p99 worse), and GC (Server GC paused 53 ms in total over a full ramp,
  measured with `GC.GetTotalPauseDuration()`).
- **Benchmarking:** the build runs with `--disable-build-servers`; otherwise
  the Roslyn compiler server keeps running and the suite flags the run as busy.
- **Tools:** a probe timing the `_readSlots` wait against query time in
  `Db.Read`; `ThreadPool.ThreadCount`/`PendingWorkItemCount`. See
  [`docs/optimizing.md`](../../docs/optimizing.md).

## Verify and benchmark

```sh
python3 bench/run.py --stacks csharp --profile quick   # from the repo root
```

The report must show **pass** for the seed checksum (VER-1) and API parity
(VER-2). The spec is in [`docs/requirements/`](../../docs/requirements/README.md).
