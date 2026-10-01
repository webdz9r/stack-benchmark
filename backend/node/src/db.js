// One SQLite connection with better-sqlite3 (synchronous).
//
// The server never uses this on its event loop: each thread in pool.js owns
// one Db (the writer, or a read-only reader). The seeder uses it directly.

import Database from 'better-sqlite3'
import { mkdirSync, readdirSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const PRAGMAS = `
  PRAGMA journal_mode = WAL;
  PRAGMA synchronous = NORMAL;
  PRAGMA busy_timeout = 5000;
  PRAGMA foreign_keys = ON;
  PRAGMA cache_size = -64000;
  PRAGMA temp_store = MEMORY;
  PRAGMA mmap_size = 268435456;
  PRAGMA journal_size_limit = 67108864;
`

// The shared migration files (backend/migrations), so the schema can't drift.
const MIGRATIONS_DIR = join(dirname(fileURLToPath(import.meta.url)), '../../migrations')

export class Db {
  /** The writer runs migrations when it opens; open it before any reader. */
  constructor(path, { readOnly = false } = {}) {
    if (!readOnly) mkdirSync(dirname(path), { recursive: true })
    this.conn = new Database(path, { readonly: readOnly })
    this.conn.exec(PRAGMAS)
    this.statements = new Map()
    if (!readOnly) this.#migrate()
  }

  #migrate() {
    const files = readdirSync(MIGRATIONS_DIR).filter((f) => f.endsWith('.sql')).sort()
    this.transaction(() => {
      const current = this.conn.prepare('PRAGMA user_version').get().user_version
      files.slice(current).forEach((file, i) => {
        this.conn.exec(readFileSync(join(MIGRATIONS_DIR, file), 'utf8'))
        this.conn.exec(`PRAGMA user_version = ${current + i + 1}`)
      })
    })
  }

  /** A cached prepared statement. */
  stmt(sql) {
    let s = this.statements.get(sql)
    if (!s) {
      s = this.conn.prepare(sql)
      this.statements.set(sql, s)
    }
    return s
  }

  all(sql, ...params) { return this.stmt(sql).all(...params) }
  get(sql, ...params) { return this.stmt(sql).get(...params) }
  run(sql, ...params) { return this.stmt(sql).run(...params) }

  /** Run fn inside BEGIN IMMEDIATE ... COMMIT (ROLLBACK on throw). */
  transaction(fn) {
    this.conn.exec('BEGIN IMMEDIATE')
    try {
      const result = fn()
      this.conn.exec('COMMIT')
      return result
    } catch (e) {
      this.conn.exec('ROLLBACK')
      throw e
    }
  }

  /** Same policy as the Rust backend: PASSIVE, then TRUNCATE once the WAL
   *  passes 64 MB and has been fully copied, waiting at most 50 ms. */
  checkpoint() {
    const r = this.conn.prepare('PRAGMA wal_checkpoint(PASSIVE)').get()
    if (r.log < 16_384 || r.checkpointed < r.log) return
    this.conn.exec('PRAGMA busy_timeout = 50')
    try {
      this.conn.prepare('PRAGMA wal_checkpoint(TRUNCATE)').get()
    } finally {
      this.conn.exec('PRAGMA busy_timeout = 5000')
    }
  }

  truncateWal() {
    this.conn.prepare('PRAGMA wal_checkpoint(TRUNCATE)').get()
  }
}
