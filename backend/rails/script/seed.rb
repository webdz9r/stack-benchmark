# Fill the database with fake contacts, all inside one transaction.
#
#   RAILS_ENV=production SECRET_KEY_BASE_DUMMY=1 bin/rails runner script/seed.rb 10000
#
# With RAILS_DATA=activerecord, contacts are created through the ActiveRecord
# models (Contact#assign_input + save!) instead of the shared SQL.
#
# A port of the Rust seeder (same generator, same data for the same starting
# state), so the two can be compared on insert speed.

FIRST = [
    "Ava", "Liam", "Olivia", "Noah", "Emma", "Oliver", "Sophia", "Elijah", "Isabella", "James",
    "Mia", "Lucas", "Amelia", "Mateo", "Harper", "Benjamin", "Evelyn", "Henry", "Aria", "Theo",
    "Chloe", "Samuel", "Priya", "Arjun", "Mei", "Hiroshi", "Fatima", "Omar", "Zoe", "Diego",
    "Sofia", "Jonas", "Ingrid", "Kwame", "Amara", "Chen", "Yuki", "Leila", "Rafael", "Nadia",
    "Grace", "Ethan", "Hannah", "Isaac", "Julia", "Kofi", "Lena", "Marcus", "Nina", "Oscar",
    "Paula", "Quinn", "Rosa", "Sean", "Tara", "Umar", "Vera", "Wes", "Ximena", "Yusuf",
]
LAST = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez",
    "Martinez", "Hernandez", "Lopez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson",
    "Martin", "Lee", "Patel", "Nguyen", "Kim", "Tanaka", "Okafor", "Müller", "Rossi", "Dubois",
    "Kowalski", "Haddad", "O'Brien", "Andersen", "Silva", "Cohen", "Novak", "Park", "Singh",
    "Bakker", "Castillo", "Dimitrov", "Eriksson", "Fischer", "Gonzaga", "Horvat", "Ivanova",
    "Jensen", "Kaur", "Larsen", "Mendes", "Nakamura", "Osei", "Petrov", "Quintero", "Reyes",
    "Sato", "Tremblay", "Ueda", "Varga", "Walsh", "Xu", "Yilmaz", "Zhou", "Abara", "Byrne",
]
COMPANIES = [
    "Acme Corp", "Globex", "Initech", "Umbrella", "Hooli", "Stark Industries", "Wayne Enterprises",
    "Pied Piper", "Soylent", "Wonka Industries", "Cyberdyne", "Tyrell Corp", "Vandelay Industries",
    "Dunder Mifflin", "Massive Dynamic", "Aperture Science", "Oscorp", "Gringotts",
]
TITLES = [
    "Engineer", "Designer", "Product Manager", "Sales Lead", "CTO", "Founder", "Accountant",
    "Consultant", "Recruiter", "Data Scientist", "Marketing Director", "Support Specialist",
]
STREETS = ["Main St", "Oak Ave", "Maple Dr", "Cedar Ln", "Pine St", "Elm St", "Park Ave", "Lake Rd"]
CITIES = [
    ["Austin", "TX", "USA"], ["Portland", "OR", "USA"], ["Denver", "CO", "USA"],
    ["Toronto", "ON", "Canada"], ["London", "", "UK"], ["Berlin", "", "Germany"],
    ["Chicago", "IL", "USA"], ["Seattle", "WA", "USA"], ["Sydney", "NSW", "Australia"],
]
NOTES = [
    "", "", "", "Met at the conference last spring.", "Prefers email over phone.",
    "Old college friend.", "Introduced by a mutual friend.", "Follow up about the proposal.",
]
TAGS = [
    ["Family", "red"], ["Friends", "amber"], ["Work", "sky"], ["Clients", "green"],
    ["Vendors", "violet"], ["Neighbors", "teal"],
]

MASK = (1 << 64) - 1

# The Rust seeder's xorshift PRNG, bit for bit.
class SeedRng
  def initialize(seed) = @state = seed & MASK

  def next_u64
    s = @state
    s ^= (s << 13) & MASK
    s ^= s >> 7
    s ^= (s << 17) & MASK
    @state = s
  end

  def below(n) = next_u64 % n
  def pick(items) = items[below(items.length)]
  def chance(percent) = next_u64 % 100 < percent
end

count = Integer(ARGV[0] || 10_000)
db = Db.instance
existing = db.transaction { |tx| tx.query_row("SELECT count(*) FROM contacts")[0] }
rng = SeedRng.new(0x9E37_79B9_7F4A_7C15 ^ ((existing * 0x2545_F491_4F6C_DD1D) & MASK))

active_record = ENV["RAILS_DATA"] == "activerecord"
# Both paths run everything in one transaction; the block gets a way to save a contact.
in_transaction = lambda do |&body|
  if active_record
    Contact.transaction do
      tag_ids = TAGS.map { |name, color| Tag.find_or_create_by!(name:) { _1.color = color }.id }
      body.call(tag_ids, ->(c) { Contact.new.tap { _1.assign_input(c) }.save! })
    end
  else
    db.transaction do |tx|
      tag_ids = TAGS.map do |name, color|
        tx.run("INSERT OR IGNORE INTO tags (name, color) VALUES (?, ?)", name, color)
        tx.query_row("SELECT id FROM tags WHERE name = ?", name)[0]
      end
      body.call(tag_ids, ->(c) { Repo.insert_contact(tx, c) })
    end
  end
end

started = Process.clock_gettime(Process::CLOCK_MONOTONIC)
in_transaction.call do |tag_ids, insert|

  (existing...(existing + count)).each do |i|
    first = rng.pick(FIRST)
    last = rng.pick(LAST)
    handle = "#{first}.#{last.delete("'").delete("ü")}#{i}".downcase
    has_company = rng.chance(70)
    city, region, country = rng.pick(CITIES)

    company = has_company ? rng.pick(COMPANIES) : ""
    job_title = has_company ? rng.pick(TITLES) : ""
    birthday = rng.chance(40) ? format("%d-%02d-%02d", 1950 + rng.below(55), 1 + rng.below(12), 1 + rng.below(28)) : nil
    notes = rng.pick(NOTES)
    favorite = rng.chance(5)
    phone = format("+1 555-%03d-%04d", rng.below(1000), rng.below(10_000))

    c = {
      first_name: first, last_name: last, company:, job_title:, birthday:, notes:, favorite:,
      emails: [{ label: "home", value: "#{handle}@example.com" }],
      phones: [{ label: "mobile", value: phone }],
      addresses: [], tag_ids: []
    }
    if has_company && rng.chance(50)
      c[:emails] << { label: "work", value: "#{handle}@#{company.downcase.delete(" ")}.com" }
    end
    if rng.chance(60)
      c[:addresses] << {
        label: "home", street: "#{1 + rng.below(9999)} #{rng.pick(STREETS)}",
        city:, region:, postal_code: format("%05d", rng.below(100_000)), country:
      }
    end
    c[:tag_ids] = tag_ids.select { rng.chance(12) }

    insert.call(c)
  end
end
# One big transaction leaves an equally big WAL; fold it in now.
db.truncate_wal

secs = Process.clock_gettime(Process::CLOCK_MONOTONIC) - started
path = ENV.fetch("DATABASE_PATH", "data/address-book.db")
puts format("Inserted %d contacts into %s in %.1f ms (%d contacts/sec, each with its emails, phones, addresses, tags and search index row)",
            count, path, secs * 1000, (count / secs).round)
