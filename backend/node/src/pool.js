// One writer thread plus DB_READERS reader threads (ARCH-11/12), so SQLite
// never runs on the event loop. The HTTP server, the response cache and gzip
// stay in one process, which lets every request share a single cache.

import { Worker } from 'node:worker_threads'

import { AppError } from './errors.js'

const THREAD = new URL('./dbthread.js', import.meta.url)

/** A database thread that runs one operation at a time. */
class Thread {
  constructor(path, role) {
    this.worker = new Worker(THREAD, { workerData: { path, role } })
    this.pending = new Map()
    this.nextId = 0
    this.ready = new Promise((resolve, reject) => {
      this.worker.once('error', reject)
      this.worker.on('message', (m) => {
        if (m.ready) return resolve()
        const { resolve: done, reject: fail } = this.pending.get(m.id)
        this.pending.delete(m.id)
        if (m.error) fail(new AppError(m.error.status, m.error.message))
        else done(m.body)
      })
    })
    this.worker.on('exit', (code) => {
      console.error(`database thread (${role}) exited with code ${code}`)
      process.exit(1)
    })
  }

  /** Resolves with the result as JSON text (undefined for no result). */
  call(op, args) {
    const id = this.nextId++
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject })
      this.worker.postMessage({ id, op, args })
    })
  }

  get busy() {
    return this.pending.size > 0
  }
}

export class DbPool {
  static async open(path, readers) {
    const pool = new DbPool()
    // The writer runs the migrations, so it has to be up before any reader opens.
    pool.writer = new Thread(path, 'writer')
    await pool.writer.ready
    pool.readers = Array.from({ length: readers }, () => new Thread(path, 'reader'))
    await Promise.all(pool.readers.map((r) => r.ready))
    return pool
  }

  constructor() {
    this.queue = [] // reads waiting for an idle reader, oldest first
    this.writes = 0
  }

  /** Run a read on the next idle reader; resolves with JSON text. */
  read(op, ...args) {
    return new Promise((resolve, reject) => {
      this.queue.push({ op, args, resolve, reject })
      this.#dispatch()
    })
  }

  #dispatch() {
    for (const reader of this.readers) {
      if (this.queue.length === 0) return
      if (reader.busy) continue
      const job = this.queue.shift()
      reader.call(job.op, job.args).then(job.resolve, job.reject).finally(() => this.#dispatch())
    }
  }

  /** Run a write in its own transaction on the writer thread. */
  async write(op, ...args) {
    try {
      return await this.writer.call(op, args)
    } finally {
      // Bump even on error: a failed write may still have changed data.
      this.writes++
    }
  }

  /** How many writes this process has made; response caches key on it. */
  generation() {
    return this.writes
  }
}
