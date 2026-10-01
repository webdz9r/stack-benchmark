// In-process response cache; same policy as the Rust backend's cache.rs.
//
// Keys include a copy of the write count that catches up at most once per
// maxStaleness, so other users see writes within ~1 s. `X-Fresh` requests key
// on the live count (read-your-writes). Concurrent misses for a key share one
// query. Entries carry an ETag for If-None-Match revalidation.

import { createHash } from 'node:crypto'

const TTL_MS = 30_000

export class ResponseCache {
  constructor(db, { maxBytes, maxStalenessMs }) {
    this.db = db
    this.maxBytes = maxBytes
    this.maxStalenessMs = maxStalenessMs
    this.entries = new Map() // insertion order = LRU order
    this.inflight = new Map() // key -> promise of the entry being computed
    this.bytes = 0
    this.published = 0
    this.publishedAt = -Infinity
  }

  #generation(request) {
    if (request.headers['x-fresh'] !== undefined) return this.db.generation()
    const now = performance.now()
    if (now - this.publishedAt >= this.maxStalenessMs) {
      this.published = this.db.generation()
      this.publishedAt = now
    }
    return this.published
  }

  /** Send the JSON text compute() resolves with, from cache when the data hasn't changed. */
  async json(request, reply, key, compute) {
    // Read the write count before querying: if a write lands mid-query, the
    // entry is filed under the older count, so it's replaced on the next refresh.
    const fullKey = `${this.#generation(request)}|${key}`
    let entry = this.entries.get(fullKey)
    if (entry && performance.now() - entry.at > TTL_MS) {
      this.#drop(fullKey)
      entry = undefined
    }
    if (entry) {
      this.entries.delete(fullKey) // move to the back (most recently used)
      this.entries.set(fullKey, entry)
    } else {
      let pending = this.inflight.get(fullKey)
      if (!pending) {
        pending = this.#compute(fullKey, compute).finally(() => this.inflight.delete(fullKey))
        this.inflight.set(fullKey, pending)
      }
      entry = await pending
    }

    reply.header('etag', entry.etag).header('cache-control', 'no-cache')
    if (etagMatches(request.headers['if-none-match'], entry.etag)) {
      return reply.code(304).send()
    }
    return reply.type('application/json').send(entry.body)
  }

  async #compute(fullKey, compute) {
    const body = Buffer.from(await compute())
    const etag = `"${createHash('sha1').update(body).digest('hex').slice(0, 16)}"`
    const entry = { body, etag, at: performance.now() }
    this.entries.set(fullKey, entry)
    this.bytes += body.length + fullKey.length
    for (const k of this.entries.keys()) {
      if (this.bytes <= this.maxBytes) break
      this.#drop(k)
    }
    return entry
  }

  #drop(key) {
    const e = this.entries.get(key)
    this.entries.delete(key)
    this.bytes -= e.body.length + key.length
  }
}

function etagMatches(header, etag) {
  if (!header) return false
  return header.split(',').some((t) => {
    const tag = t.trim().replace(/^W\//, '')
    return tag === '*' || tag === etag
  })
}
