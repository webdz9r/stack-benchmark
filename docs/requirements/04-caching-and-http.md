# 04 — Response cache, freshness and HTTP transport

The response cache was the largest single performance gain measured: it took the
Rust server from about 2,000 to about 4,000 simulated users at p99 < 100 ms. Every
stack MUST implement the same policy, or the stacks aren't doing the same work.

## 1. What is cached

| Endpoint | Cache key (before the generation is added) |
| --- | --- |
| `GET /api/stats` | `stats` |
| `GET /api/tags` | `tags` |
| `GET /api/contacts/letters` | `letters|<filter_key>` |
| `GET /api/contacts` **when filtered** | `list|<filter_key>|<limit>|<offset>` |

`filter_key = <fts_query(q) or ""> | <tag or none> | <favorite == true>`

- **CACHE-1** The search part of the key MUST be the **normalized** FTS expression,
  so `Smith`, `smith ` and `Smith!` share one entry. (FTS matching ignores case,
  but the key keeps the case of the expression, so `Smith` and `smith` MAY get
  separate entries, as they do in the reference.)
- **CACHE-2** `limit` and `offset` MAY go into the key raw (as sent) or clamped. The
  reference uses the raw values.
- **CACHE-3** The cached value is the **serialized JSON body bytes**, not the result
  objects, so a cache hit doesn't serialize anything.
- **CACHE-4** `GET /api/contacts/{id}` and unfiltered list pages MUST NOT be
  cached.

## 2. Cache structure

- **CACHE-5** In-process and bounded by **size**: max 64 MiB, where an entry's size
  is `len(key) + len(body)`. Evict in LRU order, and always admit new entries.
  Don't use a frequency-based admission policy such as TinyLFU (moka's default):
  each generation bump (CACHE-7) makes every key new, so such a policy rejects the
  current entries in favour of stale ones that can never be hit again, and the hit
  rate drops as soon as the cache is full. The reference uses moka with
  `EvictionPolicy::lru()`.
- **CACHE-6** Entries expire **30 s** after they are inserted (TTL). This also
  covers writes the process can't see, such as a seeder run or a manual `sqlite3`
  session.
- **CACHE-7** The full key is `(generation, key)`, where `generation` is described
  below. Old-generation entries are never looked up again; they age out through
  the TTL and the size limit.
- **CACHE-8** Concurrent misses on the same key SHOULD share a single computation
  (single-flight or request coalescing). Stacks whose request handling is
  single-threaded and synchronous, like Node, get this for free.

## 3. Change detection (the generation)

### 3.1 Single-process stacks (the reference)

- **CACHE-9** The database layer keeps a counter, `generation`, that is incremented
  **after every write**, whether it succeeded or failed (a failed write may still
  have changed data). The increment happens on the writer path, after the write
  closure returns.

### 3.2 Multi-process stacks

A per-process counter doesn't see writes made by other workers.

- **CACHE-10** Multi-process stacks MUST detect changes through SQLite: hold a
  dedicated connection and read `PRAGMA data_version`. Whenever the value differs
  from the last one seen, increment a local generation. `data_version` on a
  separate connection changes when **any** connection commits, including this
  worker's own writer, other workers and the seeder. (Node, Python and Rails do
  this; see for example `backend/node/src/db.js`.)

### 3.3 Published generation (bounded staleness)

Emptying the cache on every write collapsed the hit rate at just 8 writes/s. So
cache keys use a **published** copy of the generation, which catches up with the
real one at most once per `max_staleness` (**1 s**):

```
key_generation(request):
    if request has header "X-Fresh" (any value):
        return live_generation()                 // read-your-writes
    now = monotonic_ms()
    if now - published_at >= 1000:
        published_generation = live_generation() // racing refreshes are harmless
        published_at = now
    return published_generation
```

- **CACHE-11** Read the generation **before** running the query. If a write lands
  mid-query, the entry is filed under the older generation, and it is replaced at
  the next refresh.
- **CACHE-12** `X-Fresh` is detected by the header's presence, not its value. The
  frontend sends `X-Fresh: 1` on every GET for 2 s after the browser's last
  write, so the person who saved always sees their change. Other users see it
  within about 1 s.

## 4. ETags and conditional requests

- **CACHE-13** Every cached response MUST carry:
  - `ETag: "<16 lowercase hex chars>"`: a 64-bit hash of the body bytes, quoted.
    Any stable, fast hash works (the reference uses Rust's `DefaultHasher`; Node
    uses the first 16 hex characters of a SHA-1). ETags don't need to match across
    stacks.
  - `Cache-Control: no-cache` (the client may store it, but must revalidate).
  - `Content-Type: application/json`
- **CACHE-14** If the request's `If-None-Match` matches, respond **304 Not
  Modified** with `ETag` and `Cache-Control` and **no body**. Matching works like
  this:
  ```
  split If-None-Match on ','
  for each token: trim whitespace, strip a leading "W/"
  match if any token == "*" or token == etag (quotes included)
  ```
- **CACHE-15** Uncached responses (unfiltered lists, a single contact, writes) MUST
  NOT carry an ETag.
- The load generator and browsers revalidate this way, so a real share of
  simulated-user traffic is 304s. Leaving the ETag out changes the benchmark.

## 5. Compression

- **HTTP-1** gzip **only**. No brotli, zstd or deflate.
- **HTTP-2** Compression **level 6**.
- **HTTP-3** Compress only when the request's `Accept-Encoding` includes `gzip`,
  and only responses whose body is **32 bytes or more**. Responses smaller than
  that, and bodyless responses (204, 304), are sent uncompressed.
- **HTTP-4** Compressed responses carry `Content-Encoding: gzip` and `Vary:
  accept-encoding`. Streaming or chunked transfer is fine.
- **HTTP-5** Compression applies to **every** response, API and static files alike,
  including cached ones. The only exceptions are `image/*` (except
  `image/svg+xml`), `text/event-stream` and `application/grpc` content types,
  which is tower-http's default predicate. The reference compresses a cache hit again on each
  request; it does not store gzipped bodies. A stack MAY also cache the gzipped
  bytes, but should note that it does, since it's an optimization the others don't
  have.
- A 60-row list page shrinks from about 11.5 KB to about 1.7 KB.

## 6. HTTP transport

- **HTTP-6** HTTP/1.1 with keep-alive. HTTP/2 and TLS are not required.
- **HTTP-7** No CORS headers (ARCH-20).
- **HTTP-8** No per-request middleware that does real work (sessions, CSRF, body
  logging, and so on). Rails runs in API mode for this reason.
