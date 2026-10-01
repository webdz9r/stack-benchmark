// Plain synchronous SQL; the same statements as the Rust backend's repo.rs.

import { AppError, isConstraintError } from './errors.js'

const MAX_PAGE = 200
const CONTACT_ORDER = 'c.sort_key COLLATE NOCASE, c.first_name COLLATE NOCASE, c.id'
const NOW = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"

// ---------------------------------------------------------------- contacts

/** Free text -> safe FTS5 query: each word a quoted prefix term. `jo smi` -> `"jo"* "smi"*`.
 *  A word is made of Unicode letters, marks and numbers, plus `@ . '`. */
export function ftsQuery(text) {
  if (!text) return null
  const terms = text.split(/[^\p{L}\p{M}\p{N}@.']+/u).filter(Boolean)
  return terms.length ? terms.map((t) => `"${t.replaceAll('"', '""')}"*`).join(' ') : null
}

function filters({ q, tag, favorite }) {
  const clauses = []
  const args = []
  const fts = ftsQuery(q)
  if (fts) {
    clauses.push('c.id IN (SELECT rowid FROM contacts_fts WHERE contacts_fts MATCH ?)')
    args.push(fts)
  }
  if (tag != null) {
    clauses.push('c.id IN (SELECT contact_id FROM contact_tags WHERE tag_id = ?)')
    args.push(tag)
  }
  if (favorite) clauses.push('c.favorite = 1')
  return [clauses.length ? `WHERE ${clauses.join(' AND ')}` : '', args]
}

export function listContacts(db, query) {
  const limit = Math.max(1, Math.min(query.limit ?? 50, MAX_PAGE))
  const offset = Math.max(0, query.offset ?? 0)
  const [where, args] = filters(query)

  const total = db.get(`SELECT count(*) AS n FROM contacts c ${where}`, ...args).n
  const rows = db.all(
    `SELECT c.id, c.first_name, c.last_name, c.company, c.job_title, c.favorite,
            (SELECT value FROM emails WHERE contact_id = c.id ORDER BY position LIMIT 1) AS email,
            (SELECT value FROM phones WHERE contact_id = c.id ORDER BY position LIMIT 1) AS phone,
            (SELECT group_concat(tag_id) FROM contact_tags WHERE contact_id = c.id) AS tags
     FROM contacts c
     ${where}
     ORDER BY ${CONTACT_ORDER}
     LIMIT ? OFFSET ?`,
    ...args, limit, offset,
  )
  const items = rows.map((r) => ({
    id: r.id, first_name: r.first_name, last_name: r.last_name, company: r.company,
    job_title: r.job_title, favorite: r.favorite === 1, email: r.email, phone: r.phone,
    tag_ids: r.tags ? r.tags.split(',').map(Number) : [],
  }))
  return { items, total, limit, offset }
}

/** Where each file letter starts in the sorted, filtered list. Buckets are
 *  contiguous and sort like the list ('#' < 'A'..'Z' < '~'), so offsets are
 *  running totals; '~' (after Z) is reported as '#'. */
export function listLetters(db, query) {
  const [where, args] = filters(query)
  const buckets = db.all(
    `SELECT c.sort_letter AS letter, count(*) AS n FROM contacts c ${where}
     GROUP BY c.sort_letter ORDER BY c.sort_letter`,
    ...args,
  )
  const letters = []
  let offset = 0
  for (const { letter, n } of buckets) {
    if (letter === '~') {
      const hash = letters.find((l) => l.letter === '#')
      if (hash) hash.count += n
      else letters.push({ letter: '#', offset, count: n })
    } else {
      letters.push({ letter, offset, count: n })
    }
    offset += n
  }
  return letters
}

export function getContact(db, id) {
  const r = db.get(
    `SELECT id, first_name, last_name, company, job_title, birthday, notes, favorite, created_at, updated_at
     FROM contacts WHERE id = ?`,
    id,
  )
  if (!r) throw AppError.notFound()
  const labeled = (table) =>
    db.all(`SELECT label, value FROM ${table} WHERE contact_id = ? ORDER BY position`, id)
      .map(({ label, value }) => ({ label, value }))
  return {
    id: r.id, first_name: r.first_name, last_name: r.last_name, company: r.company,
    job_title: r.job_title, birthday: r.birthday, notes: r.notes, favorite: r.favorite === 1,
    emails: labeled('emails'),
    phones: labeled('phones'),
    addresses: db
      .all(
        `SELECT label, street, city, region, postal_code, country
         FROM addresses WHERE contact_id = ? ORDER BY position`,
        id,
      )
      .map((a) => ({ ...a })),
    tags: db
      .all(
        `SELECT t.id, t.name, t.color FROM tags t
         JOIN contact_tags ct ON ct.tag_id = t.id
         WHERE ct.contact_id = ? ORDER BY t.name COLLATE NOCASE`,
        id,
      )
      .map((t) => ({ ...t })),
    created_at: r.created_at,
    updated_at: r.updated_at,
  }
}

export function insertContact(db, c) {
  const { lastInsertRowid } = db.run(
    `INSERT INTO contacts (first_name, last_name, company, job_title, birthday, notes, favorite)
     VALUES (?, ?, ?, ?, ?, ?, ?)`,
    c.first_name, c.last_name, c.company, c.job_title, c.birthday, c.notes, c.favorite ? 1 : 0,
  )
  const id = Number(lastInsertRowid)
  writeChildren(db, id, c)
  refreshFts(db, id)
  return id
}

export function updateContact(db, id, c) {
  const { changes } = db.run(
    `UPDATE contacts SET first_name = ?, last_name = ?, company = ?, job_title = ?,
        birthday = ?, notes = ?, favorite = ?, updated_at = ${NOW}
     WHERE id = ?`,
    c.first_name, c.last_name, c.company, c.job_title, c.birthday, c.notes, c.favorite ? 1 : 0, id,
  )
  if (changes === 0) throw AppError.notFound()
  for (const table of ['emails', 'phones', 'addresses', 'contact_tags']) {
    db.run(`DELETE FROM ${table} WHERE contact_id = ?`, id)
  }
  writeChildren(db, id, c)
  refreshFts(db, id)
}

export function setFavorite(db, id, favorite) {
  const { changes } = db.run(`UPDATE contacts SET favorite = ?, updated_at = ${NOW} WHERE id = ?`, favorite ? 1 : 0, id)
  if (changes === 0) throw AppError.notFound()
}

export function deleteContact(db, id) {
  // Children go via ON DELETE CASCADE; the FTS table has no foreign key.
  db.run('DELETE FROM contacts_fts WHERE rowid = ?', id)
  if (db.run('DELETE FROM contacts WHERE id = ?', id).changes === 0) throw AppError.notFound()
}

function writeChildren(db, id, c) {
  c.emails.forEach((e, i) =>
    db.run('INSERT INTO emails (contact_id, label, value, position) VALUES (?, ?, ?, ?)', id, e.label, e.value, i))
  c.phones.forEach((p, i) =>
    db.run('INSERT INTO phones (contact_id, label, value, position) VALUES (?, ?, ?, ?)', id, p.label, p.value, i))
  c.addresses.forEach((a, i) =>
    db.run(
      `INSERT INTO addresses (contact_id, label, street, city, region, postal_code, country, position)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
      id, a.label, a.street, a.city, a.region, a.postal_code, a.country, i,
    ))
  for (const tagId of c.tag_ids) {
    try {
      db.run('INSERT INTO contact_tags (contact_id, tag_id) VALUES (?, ?)', id, tagId)
    } catch (e) {
      if (isConstraintError(e)) throw AppError.validation(`tag ${tagId} does not exist`)
      throw e
    }
  }
}

/** Rebuild one contact's search document from its current rows. */
function refreshFts(db, id) {
  db.run('DELETE FROM contacts_fts WHERE rowid = ?', id)
  db.run(
    `INSERT INTO contacts_fts (rowid, name, company, emails, phones, places, notes)
     SELECT c.id,
            c.first_name || ' ' || c.last_name,
            c.company || ' ' || c.job_title,
            coalesce((SELECT group_concat(value, ' ') FROM emails WHERE contact_id = c.id), ''),
            coalesce((SELECT group_concat(value, ' ') FROM phones WHERE contact_id = c.id), ''),
            coalesce((SELECT group_concat(street || ' ' || city || ' ' || region || ' ' || country, ' ')
                      FROM addresses WHERE contact_id = c.id), ''),
            c.notes
     FROM contacts c WHERE c.id = ?`,
    id,
  )
}

// ---------------------------------------------------------------- tags

export const listTags = (db) =>
  db.all(
    `SELECT t.id, t.name, t.color, count(ct.contact_id) AS contact_count
     FROM tags t LEFT JOIN contact_tags ct ON ct.tag_id = t.id
     GROUP BY t.id ORDER BY t.name COLLATE NOCASE`,
  ).map((t) => ({ ...t }))

export function getTag(db, id) {
  const t = db.get('SELECT id, name, color FROM tags WHERE id = ?', id)
  if (!t) throw AppError.notFound()
  return { ...t }
}

const tagConflict = (e, name) =>
  isConstraintError(e) ? AppError.conflict(`a tag named '${name}' already exists`) : e

export function insertTag(db, t) {
  let result
  try {
    result = db.run('INSERT INTO tags (name, color) VALUES (?, ?)', t.name, t.color ?? 'slate')
  } catch (e) {
    throw tagConflict(e, t.name)
  }
  return getTag(db, Number(result.lastInsertRowid))
}

export function updateTag(db, id, t) {
  let result
  try {
    result = db.run('UPDATE tags SET name = ?, color = coalesce(?, color) WHERE id = ?', t.name, t.color, id)
  } catch (e) {
    throw tagConflict(e, t.name)
  }
  if (result.changes === 0) throw AppError.notFound()
  return getTag(db, id)
}

export function deleteTag(db, id) {
  if (db.run('DELETE FROM tags WHERE id = ?', id).changes === 0) throw AppError.notFound()
}

// ---------------------------------------------------------------- stats

export function stats(db) {
  const r = db.get('SELECT count(*) AS contacts, coalesce(sum(favorite), 0) AS favorites FROM contacts')
  return { contacts: r.contacts, favorites: r.favorites }
}
