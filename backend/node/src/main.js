// Entry point: one process. Fastify, the response cache and gzip run on the
// event loop; SQLite runs on DB_READERS reader threads plus one writer thread
// (see pool.js).
//
//   DB_READERS=4 PORT=7880 node src/main.js

import { buildServer } from './server.js'

const port = Number(process.env.PORT ?? 7880)
const host = process.env.HOST ?? '127.0.0.1'

const app = await buildServer()
await app.listen({ port, host })
console.log(`listening on http://${host}:${port}`)
