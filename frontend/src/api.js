// The server's response cache may lag writes by up to a second. For a short
// while after this browser saves something, ask it to skip the cache so the
// user always sees their own change.
const FRESH_WINDOW_MS = 2000
let lastWriteAt = -Infinity

async function request(method, path, body) {
  const headers = {}
  if (body) headers['Content-Type'] = 'application/json'
  if (method === 'GET' && performance.now() - lastWriteAt < FRESH_WINDOW_MS) headers['X-Fresh'] = '1'
  if (method !== 'GET') lastWriteAt = performance.now()

  const res = await fetch(`/api${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (method !== 'GET') lastWriteAt = performance.now()
  if (res.status === 204) return null
  const data = await res.json().catch(() => null)
  if (!res.ok) throw new Error(data?.error ?? `Request failed (${res.status})`)
  return data
}

function filterParams({ q, tag, favorite } = {}, extra = {}) {
  const params = new URLSearchParams(extra)
  if (q) params.set('q', q)
  if (tag) params.set('tag', tag)
  if (favorite) params.set('favorite', 'true')
  return params
}

export const api = {
  stats: () => request('GET', '/stats'),

  listContacts: ({ limit = 60, offset = 0, ...filters } = {}) =>
    request('GET', `/contacts?${filterParams(filters, { limit, offset })}`),
  /** Where each letter starts in the filtered list: [{ letter, offset, count }]. */
  contactLetters: (filters) => request('GET', `/contacts/letters?${filterParams(filters)}`),
  getContact: (id) => request('GET', `/contacts/${id}`),
  createContact: (input) => request('POST', '/contacts', input),
  updateContact: (id, input) => request('PUT', `/contacts/${id}`, input),
  deleteContact: (id) => request('DELETE', `/contacts/${id}`),
  setFavorite: (id, favorite) => request('PUT', `/contacts/${id}/favorite`, { favorite }),

  listTags: () => request('GET', '/tags'),
  createTag: (input) => request('POST', '/tags', input),
  updateTag: (id, input) => request('PUT', `/tags/${id}`, input),
  deleteTag: (id) => request('DELETE', `/tags/${id}`),
}
