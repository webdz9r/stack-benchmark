// A database thread (see pool.js): owns one connection and runs repo
// operations on it, one message at a time. Results come back as JSON text, so
// serialization happens here too rather than on the event loop.

import { parentPort, workerData } from 'node:worker_threads'

import { Db } from './db.js'
import { AppError } from './errors.js'
import * as repo from './repo.js'

const { path, role } = workerData
const db = new Db(path, { readOnly: role === 'reader' })

const READS = {
  listContacts: (f) => repo.listContacts(db, f),
  listLetters: (f) => repo.listLetters(db, f),
  getContact: (id) => repo.getContact(db, id),
  listTags: () => repo.listTags(db),
  stats: () => repo.stats(db),
}

// Each write is one BEGIN IMMEDIATE ... COMMIT transaction.
const WRITES = {
  createContact: (c) => repo.getContact(db, repo.insertContact(db, c)),
  updateContact: (id, c) => {
    repo.updateContact(db, id, c)
    return repo.getContact(db, id)
  },
  setFavorite: (id, favorite) => repo.setFavorite(db, id, favorite),
  deleteContact: (id) => repo.deleteContact(db, id),
  insertTag: (t) => repo.insertTag(db, t),
  updateTag: (id, t) => repo.updateTag(db, id, t),
  deleteTag: (id) => repo.deleteTag(db, id),
}

if (role === 'writer') {
  setInterval(() => {
    try {
      db.checkpoint()
    } catch (e) {
      console.warn(`warning: WAL checkpoint failed: ${e.message}`)
    }
  }, 5000)
}

parentPort.on('message', ({ id, op, args }) => {
  try {
    const result = role === 'writer' ? db.transaction(() => WRITES[op](...args)) : READS[op](...args)
    parentPort.postMessage({ id, body: result === undefined ? undefined : JSON.stringify(result) })
  } catch (e) {
    if (!(e instanceof AppError)) console.error(e)
    const error = e instanceof AppError ? { status: e.status, message: e.message } : { status: 500, message: 'internal server error' }
    parentPort.postMessage({ id, error })
  }
})

parentPort.postMessage({ ready: true })
