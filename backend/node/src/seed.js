// Fill the database with fake contacts, all inside one transaction.
//
//   node src/seed.js 10000
//
// A port of the Rust seeder (same generator, same data for the same starting
// state), so the two can be compared on insert speed.

import { Db } from './db.js'
import * as repo from './repo.js'

const FIRST = [
    "Ava", "Liam", "Olivia", "Noah", "Emma", "Oliver", "Sophia", "Elijah", "Isabella", "James",
    "Mia", "Lucas", "Amelia", "Mateo", "Harper", "Benjamin", "Evelyn", "Henry", "Aria", "Theo",
    "Chloe", "Samuel", "Priya", "Arjun", "Mei", "Hiroshi", "Fatima", "Omar", "Zoe", "Diego",
    "Sofia", "Jonas", "Ingrid", "Kwame", "Amara", "Chen", "Yuki", "Leila", "Rafael", "Nadia",
    "Grace", "Ethan", "Hannah", "Isaac", "Julia", "Kofi", "Lena", "Marcus", "Nina", "Oscar",
    "Paula", "Quinn", "Rosa", "Sean", "Tara", "Umar", "Vera", "Wes", "Ximena", "Yusuf",
]
const LAST = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez",
    "Martinez", "Hernandez", "Lopez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson",
    "Martin", "Lee", "Patel", "Nguyen", "Kim", "Tanaka", "Okafor", "Müller", "Rossi", "Dubois",
    "Kowalski", "Haddad", "O'Brien", "Andersen", "Silva", "Cohen", "Novak", "Park", "Singh",
    "Bakker", "Castillo", "Dimitrov", "Eriksson", "Fischer", "Gonzaga", "Horvat", "Ivanova",
    "Jensen", "Kaur", "Larsen", "Mendes", "Nakamura", "Osei", "Petrov", "Quintero", "Reyes",
    "Sato", "Tremblay", "Ueda", "Varga", "Walsh", "Xu", "Yilmaz", "Zhou", "Abara", "Byrne",
]
const COMPANIES = [
    "Acme Corp", "Globex", "Initech", "Umbrella", "Hooli", "Stark Industries", "Wayne Enterprises",
    "Pied Piper", "Soylent", "Wonka Industries", "Cyberdyne", "Tyrell Corp", "Vandelay Industries",
    "Dunder Mifflin", "Massive Dynamic", "Aperture Science", "Oscorp", "Gringotts",
]
const TITLES = [
    "Engineer", "Designer", "Product Manager", "Sales Lead", "CTO", "Founder", "Accountant",
    "Consultant", "Recruiter", "Data Scientist", "Marketing Director", "Support Specialist",
]
const STREETS = ["Main St", "Oak Ave", "Maple Dr", "Cedar Ln", "Pine St", "Elm St", "Park Ave", "Lake Rd"]
const CITIES = [
    ["Austin", "TX", "USA"], ["Portland", "OR", "USA"], ["Denver", "CO", "USA"],
    ["Toronto", "ON", "Canada"], ["London", "", "UK"], ["Berlin", "", "Germany"],
    ["Chicago", "IL", "USA"], ["Seattle", "WA", "USA"], ["Sydney", "NSW", "Australia"],
]
const NOTES = [
    "", "", "", "Met at the conference last spring.", "Prefers email over phone.",
    "Old college friend.", "Introduced by a mutual friend.", "Follow up about the proposal.",
]
const TAGS = [
    ["Family", "red"], ["Friends", "amber"], ["Work", "sky"], ["Clients", "green"],
    ["Vendors", "violet"], ["Neighbors", "teal"],
]

const MASK = (1n << 64n) - 1n

/** The Rust seeder's xorshift PRNG, bit for bit. */
class Rng {
  constructor(seed) { this.state = seed & MASK }
  next() {
    let s = this.state
    s ^= (s << 13n) & MASK
    s ^= s >> 7n
    s ^= (s << 17n) & MASK
    this.state = s
    return s
  }
  below(n) { return Number(this.next() % BigInt(n)) }
  pick(items) { return items[this.below(items.length)] }
  chance(percent) { return this.next() % 100n < BigInt(percent) }
}

const pad = (n, width) => String(n).padStart(width, '0')

const count = Number(process.argv[2] ?? 10_000)
const path = process.env.DATABASE_PATH ?? 'data/address-book.db'
const db = new Db(path)
const existing = db.get('SELECT count(*) AS n FROM contacts').n
const rng = new Rng(0x9E3779B97F4A7C15n ^ ((BigInt(existing) * 0x2545F4914F6CDD1Dn) & MASK))

const started = performance.now()
db.transaction(() => {
  const tagIds = TAGS.map(([name, color]) => {
    db.run('INSERT OR IGNORE INTO tags (name, color) VALUES (?, ?)', name, color)
    return db.get('SELECT id FROM tags WHERE name = ?', name).id
  })

  for (let i = existing; i < existing + count; i++) {
    const first = rng.pick(FIRST)
    const last = rng.pick(LAST)
    const handle = `${first}.${last.replaceAll("'", '').replaceAll('ü', '')}${i}`.toLowerCase()
    const hasCompany = rng.chance(70)
    const [city, region, country] = rng.pick(CITIES)

    const company = hasCompany ? rng.pick(COMPANIES) : ''
    const jobTitle = hasCompany ? rng.pick(TITLES) : ''
    const birthday = rng.chance(40)
      ? `${1950 + rng.below(55)}-${pad(1 + rng.below(12), 2)}-${pad(1 + rng.below(28), 2)}`
      : null
    const notes = rng.pick(NOTES)
    const favorite = rng.chance(5)
    const phone = `+1 555-${pad(rng.below(1000), 3)}-${pad(rng.below(10_000), 4)}`

    const c = {
      first_name: first, last_name: last, company, job_title: jobTitle, birthday, notes, favorite,
      emails: [{ label: 'home', value: `${handle}@example.com` }],
      phones: [{ label: 'mobile', value: phone }],
      addresses: [],
      tag_ids: [],
    }
    if (hasCompany && rng.chance(50)) {
      c.emails.push({ label: 'work', value: `${handle}@${company.toLowerCase().replaceAll(' ', '')}.com` })
    }
    if (rng.chance(60)) {
      c.addresses.push({
        label: 'home',
        street: `${1 + rng.below(9999)} ${rng.pick(STREETS)}`,
        city, region, postal_code: pad(rng.below(100_000), 5), country,
      })
    }
    c.tag_ids = tagIds.filter(() => rng.chance(12))

    repo.insertContact(db, c)
  }
})
// One big transaction leaves an equally big WAL; fold it in now.
db.truncateWal()

const secs = (performance.now() - started) / 1000
console.log(
  `Inserted ${count} contacts into ${path} in ${(secs * 1000).toFixed(1)} ms ` +
  `(${Math.round(count / secs)} contacts/sec, each with its emails, phones, addresses, tags and search index row)`,
)
