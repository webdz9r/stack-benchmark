// Request body validation; same rules as the Rust backend.

import { AppError } from './errors.js'

export const TAG_COLORS = ['slate', 'red', 'orange', 'amber', 'green', 'teal', 'sky', 'indigo', 'violet', 'pink']

const str = (v, field) => {
  if (v === undefined || v === null) return ''
  if (typeof v !== 'string') throw AppError.validation(`${field} must be a string`)
  return v
}
const list = (v, field) => {
  if (v === undefined || v === null) return []
  if (!Array.isArray(v)) throw AppError.validation(`${field} must be a list`)
  return v
}
const label = (l) => l.trim().toLowerCase() || 'other'

function isIsoDate(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s)
  if (!m) return false
  const month = Number(m[2]), day = Number(m[3])
  return month >= 1 && month <= 12 && day >= 1 && day <= 31
}

/** Trim fields, drop empty rows, and reject obviously bad input. */
export function contactInput(body) {
  if (!body || typeof body !== 'object') throw AppError.validation('expected a JSON object')
  const c = {
    first_name: str(body.first_name, 'first_name').trim(),
    last_name: str(body.last_name, 'last_name').trim(),
    company: str(body.company, 'company').trim(),
    job_title: str(body.job_title, 'job_title').trim(),
    notes: str(body.notes, 'notes').trim(),
    favorite: body.favorite === true,
    birthday: str(body.birthday, 'birthday').trim() || null,
  }
  if (!c.first_name && !c.last_name && !c.company) throw AppError.validation('a name or company is required')
  if (c.birthday && !isIsoDate(c.birthday)) throw AppError.validation('birthday must be YYYY-MM-DD')

  const labeled = (rows, field) =>
    list(rows, field)
      .map((r) => ({ label: label(str(r?.label, 'label')), value: str(r?.value, 'value').trim() }))
      .filter((r) => r.value)
  c.emails = labeled(body.emails, 'emails')
  c.phones = labeled(body.phones, 'phones')
  for (const e of c.emails) {
    const at = e.value.indexOf('@')
    const user = at >= 0 ? e.value.slice(0, at) : ''
    const domain = at >= 0 ? e.value.slice(at + 1) : ''
    if (at < 0 || !user || !domain.includes('.') || /\s/.test(e.value)) {
      throw AppError.validation(`'${e.value}' is not a valid email`)
    }
  }

  const fields = ['street', 'city', 'region', 'postal_code', 'country']
  c.addresses = list(body.addresses, 'addresses')
    .map((a) => ({
      label: label(str(a?.label, 'label')),
      ...Object.fromEntries(fields.map((f) => [f, str(a?.[f], f).trim()])),
    }))
    .filter((a) => fields.some((f) => a[f]))

  c.tag_ids = [...new Set(list(body.tag_ids, 'tag_ids').map(Number))].sort((a, b) => a - b)
  return c
}

export function tagInput(body) {
  const name = str(body?.name, 'name').trim()
  if (!name) throw AppError.validation('tag name is required')
  if ([...name].length > 40) throw AppError.validation('tag name must be 40 characters or fewer')
  const color = body?.color ?? null
  if (color !== null && !TAG_COLORS.includes(color)) throw AppError.validation(`unknown tag color '${color}'`)
  return { name, color }
}
