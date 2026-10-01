export function displayName(c) {
  const name = [c.first_name, c.last_name].filter(Boolean).join(' ')
  return name || c.company || 'Unnamed'
}

export function initials(c) {
  const parts = [c.first_name, c.last_name].filter(Boolean)
  const source = parts.length ? parts : [c.company || '?']
  return source.map((p) => p[0]).join('').slice(0, 2).toUpperCase()
}

/**
 * The letter tab a contact files under. Must match the API's letter index:
 * last name, else first name, else company; anything not A–Z is '#'.
 */
export function fileLetter(c) {
  const key = c.last_name || c.first_name || c.company || '#'
  const ch = key[0].toUpperCase()
  return /[A-Z]/.test(ch) ? ch : '#'
}

export const ALPHABET = [...'ABCDEFGHIJKLMNOPQRSTUVWXYZ#']

export function formatBirthday(iso) {
  if (!iso) return ''
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString(undefined, {
    year: 'numeric', month: 'long', day: 'numeric',
  })
}

export function formatAddress(a) {
  const cityLine = [a.city, [a.region, a.postal_code].filter(Boolean).join(' ')]
    .filter(Boolean).join(', ')
  return [a.street, cityLine, a.country].filter(Boolean)
}

export function mapsUrl(a) {
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(formatAddress(a).join(', '))}`
}

/** Tailwind needs literal class names, so each tag color maps to full strings. */
export const TAG_STYLES = {
  slate:  { dot: 'bg-slate-500',  chip: 'bg-slate-100 text-slate-800' },
  red:    { dot: 'bg-red-500',    chip: 'bg-red-100 text-red-800' },
  orange: { dot: 'bg-orange-500', chip: 'bg-orange-100 text-orange-800' },
  amber:  { dot: 'bg-amber-500',  chip: 'bg-amber-100 text-amber-900' },
  green:  { dot: 'bg-green-600',  chip: 'bg-green-100 text-green-800' },
  teal:   { dot: 'bg-teal-500',   chip: 'bg-teal-100 text-teal-800' },
  sky:    { dot: 'bg-sky-500',    chip: 'bg-sky-100 text-sky-800' },
  indigo: { dot: 'bg-indigo-500', chip: 'bg-indigo-100 text-indigo-800' },
  violet: { dot: 'bg-violet-500', chip: 'bg-violet-100 text-violet-800' },
  pink:   { dot: 'bg-pink-500',   chip: 'bg-pink-100 text-pink-800' },
}
export const TAG_COLORS = Object.keys(TAG_STYLES)
export const tagStyle = (color) => TAG_STYLES[color] ?? TAG_STYLES.slate
