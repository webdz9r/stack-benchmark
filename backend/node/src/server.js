// Fastify version of the address book API; same routes and JSON as the Rust backend.
// SQLite runs on the threads in pool.js; this event loop only does HTTP, the
// response cache and gzip.

import Fastify from 'fastify'
import compress from '@fastify/compress'
import fastifyStatic from '@fastify/static'
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'

import { availableParallelism } from 'node:os'

import { DbPool } from './pool.js'
import { AppError } from './errors.js'
import { ResponseCache } from './cache.js'
import * as repo from './repo.js'
import { contactInput, tagInput } from './validate.js'

export async function buildServer() {
  const readers = Number(process.env.DB_READERS ?? availableParallelism())
  const db = await DbPool.open(process.env.DATABASE_PATH ?? 'data/address-book.db', readers)
  // Other users see a write within ~1 s; the writer sees it at once (X-Fresh).
  const cache = new ResponseCache(db, { maxBytes: 64 * 1024 * 1024, maxStalenessMs: 1000 })

  const app = Fastify()
  // Like the other backends, accept an empty body even when it's labeled JSON
  // (e.g. a DELETE sent with Content-Type: application/json).
  app.removeContentTypeParser('application/json')
  app.addContentTypeParser('application/json', { parseAs: 'string' }, (_req, body, done) => {
    if (!body) return done(null, undefined)
    try {
      done(null, JSON.parse(body))
    } catch (e) {
      e.statusCode = 400
      done(e)
    }
  })
  // gzip only, level 6, 32-byte floor: matches tower-http's defaults on the Rust side.
  await app.register(compress, { encodings: ['gzip'], threshold: 32, zlibOptions: { level: 6 } })

  const json = (reply, data, status = 200) =>
    reply.code(status).type('application/json').send(JSON.stringify(data))
  // A body that's already JSON text (from a database thread).
  const raw = (reply, text, status = 200) => reply.code(status).type('application/json').send(text)

  app.setErrorHandler((e, _req, reply) => {
    if (e instanceof AppError) return json(reply, { error: e.message }, e.status)
    if (e.statusCode && e.statusCode < 500) return json(reply, { error: e.message }, e.statusCode)
    app.log.error(e)
    return json(reply, { error: 'internal server error' }, 500)
  })

  // Query parameters: absent -> undefined; not an integer -> 400 (spec §7).
  const int = (q, name) => {
    const v = q[name]
    if (v === undefined || v === '') return undefined
    if (!/^-?\d+$/.test(v)) throw new AppError(400, `${name} must be an integer`)
    return Number(v)
  }
  const listQuery = (q) => {
    if (q.favorite !== undefined && q.favorite !== 'true' && q.favorite !== 'false') {
      throw new AppError(400, 'favorite must be true or false')
    }
    return {
      q: q.q,
      tag: int(q, 'tag'),
      favorite: q.favorite === 'true',
      limit: int(q, 'limit'),
      offset: int(q, 'offset'),
    }
  }
  const filterKey = (f) => `${repo.ftsQuery(f.q) ?? ''}|${f.tag}|${f.favorite}`
  const id = (req) => {
    if (!/^-?\d+$/.test(req.params.id)) throw new AppError(400, 'invalid id')
    return Number(req.params.id)
  }

  // ---------------------------------------------------------------- reads

  app.get('/api/health', (_req, reply) => reply.send('ok'))

  app.get('/api/stats', (req, reply) => cache.json(req, reply, 'stats', () => db.read('stats')))

  app.get('/api/contacts', async (req, reply) => {
    const f = listQuery(req.query)
    if (f.tag === undefined && !f.favorite && !repo.ftsQuery(f.q)) {
      // Unfiltered pages walk the sort index and are cheap; not worth caching.
      return raw(reply, await db.read('listContacts', f))
    }
    return cache.json(req, reply, `list|${filterKey(f)}|${f.limit}|${f.offset}`, () => db.read('listContacts', f))
  })

  app.get('/api/contacts/letters', (req, reply) => {
    const f = listQuery(req.query)
    return cache.json(req, reply, `letters|${filterKey(f)}`, () => db.read('listLetters', f))
  })

  app.get('/api/contacts/:id', async (req, reply) => raw(reply, await db.read('getContact', id(req))))

  app.get('/api/tags', (req, reply) => cache.json(req, reply, 'tags', () => db.read('listTags')))

  // ---------------------------------------------------------------- writes

  app.post('/api/contacts', async (req, reply) => {
    const c = contactInput(req.body)
    return raw(reply, await db.write('createContact', c), 201)
  })

  app.put('/api/contacts/:id', async (req, reply) => {
    const c = contactInput(req.body)
    return raw(reply, await db.write('updateContact', id(req), c))
  })

  app.put('/api/contacts/:id/favorite', async (req, reply) => {
    if (typeof req.body?.favorite !== 'boolean') throw AppError.validation('favorite must be true or false')
    await db.write('setFavorite', id(req), req.body.favorite)
    return reply.code(204).send()
  })

  app.delete('/api/contacts/:id', async (req, reply) => {
    await db.write('deleteContact', id(req))
    return reply.code(204).send()
  })

  app.post('/api/tags', async (req, reply) => {
    const t = tagInput(req.body)
    return raw(reply, await db.write('insertTag', t), 201)
  })

  app.put('/api/tags/:id', async (req, reply) => {
    const t = tagInput(req.body)
    return raw(reply, await db.write('updateTag', id(req), t))
  })

  app.delete('/api/tags/:id', async (req, reply) => {
    await db.write('deleteTag', id(req))
    return reply.code(204).send()
  })

  // Serve the built frontend, like the Rust binary does; unknown /api paths get JSON 404s.
  const staticDir = resolve(process.env.STATIC_DIR ?? '../../frontend/dist')
  if (existsSync(resolve(staticDir, 'index.html'))) {
    await app.register(fastifyStatic, { root: staticDir })
  }
  app.setNotFoundHandler((req, reply) =>
    req.url.startsWith('/api/') || !existsSync(resolve(staticDir, 'index.html'))
      ? json(reply, { error: 'not found' }, 404)
      : reply.sendFile('index.html'),
  )

  return app
}
