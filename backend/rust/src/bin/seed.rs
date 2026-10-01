//! Fill the database with fake contacts, all inside one transaction.
//!
//!     cargo run --release --bin seed -- 10000
//!
//! Batching every insert into a single transaction is what makes this fast:
//! one fsync at commit instead of one per contact.

use std::time::Instant;

use address_book::{database_path, db::Db, models::*, repo};

const FIRST: &[&str] = &[
    "Ava", "Liam", "Olivia", "Noah", "Emma", "Oliver", "Sophia", "Elijah", "Isabella", "James",
    "Mia", "Lucas", "Amelia", "Mateo", "Harper", "Benjamin", "Evelyn", "Henry", "Aria", "Theo",
    "Chloe", "Samuel", "Priya", "Arjun", "Mei", "Hiroshi", "Fatima", "Omar", "Zoe", "Diego",
    "Sofia", "Jonas", "Ingrid", "Kwame", "Amara", "Chen", "Yuki", "Leila", "Rafael", "Nadia",
    "Grace", "Ethan", "Hannah", "Isaac", "Julia", "Kofi", "Lena", "Marcus", "Nina", "Oscar",
    "Paula", "Quinn", "Rosa", "Sean", "Tara", "Umar", "Vera", "Wes", "Ximena", "Yusuf",
];
const LAST: &[&str] = &[
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez",
    "Martinez", "Hernandez", "Lopez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson",
    "Martin", "Lee", "Patel", "Nguyen", "Kim", "Tanaka", "Okafor", "Müller", "Rossi", "Dubois",
    "Kowalski", "Haddad", "O'Brien", "Andersen", "Silva", "Cohen", "Novak", "Park", "Singh",
    "Bakker", "Castillo", "Dimitrov", "Eriksson", "Fischer", "Gonzaga", "Horvat", "Ivanova",
    "Jensen", "Kaur", "Larsen", "Mendes", "Nakamura", "Osei", "Petrov", "Quintero", "Reyes",
    "Sato", "Tremblay", "Ueda", "Varga", "Walsh", "Xu", "Yilmaz", "Zhou", "Abara", "Byrne",
];
const COMPANIES: &[&str] = &[
    "Acme Corp", "Globex", "Initech", "Umbrella", "Hooli", "Stark Industries", "Wayne Enterprises",
    "Pied Piper", "Soylent", "Wonka Industries", "Cyberdyne", "Tyrell Corp", "Vandelay Industries",
    "Dunder Mifflin", "Massive Dynamic", "Aperture Science", "Oscorp", "Gringotts",
];
const TITLES: &[&str] = &[
    "Engineer", "Designer", "Product Manager", "Sales Lead", "CTO", "Founder", "Accountant",
    "Consultant", "Recruiter", "Data Scientist", "Marketing Director", "Support Specialist",
];
const STREETS: &[&str] = &["Main St", "Oak Ave", "Maple Dr", "Cedar Ln", "Pine St", "Elm St", "Park Ave", "Lake Rd"];
const CITIES: &[(&str, &str, &str)] = &[
    ("Austin", "TX", "USA"), ("Portland", "OR", "USA"), ("Denver", "CO", "USA"),
    ("Toronto", "ON", "Canada"), ("London", "", "UK"), ("Berlin", "", "Germany"),
    ("Chicago", "IL", "USA"), ("Seattle", "WA", "USA"), ("Sydney", "NSW", "Australia"),
];
const NOTES: &[&str] = &[
    "", "", "", "Met at the conference last spring.", "Prefers email over phone.",
    "Old college friend.", "Introduced by a mutual friend.", "Follow up about the proposal.",
];
const TAGS: &[(&str, &str)] = &[
    ("Family", "red"), ("Friends", "amber"), ("Work", "sky"), ("Clients", "green"),
    ("Vendors", "violet"), ("Neighbors", "teal"),
];

/// Small xorshift PRNG; good enough for fake data and avoids a dependency.
struct Rng(u64);

impl Rng {
    fn next(&mut self) -> u64 {
        self.0 ^= self.0 << 13;
        self.0 ^= self.0 >> 7;
        self.0 ^= self.0 << 17;
        self.0
    }
    fn below(&mut self, n: usize) -> usize {
        (self.next() % n as u64) as usize
    }
    fn pick<'a, T>(&mut self, items: &'a [T]) -> &'a T {
        &items[self.below(items.len())]
    }
    fn chance(&mut self, percent: u64) -> bool {
        self.next() % 100 < percent
    }
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let count: usize = std::env::args().nth(1).map(|s| s.parse()).transpose()?.unwrap_or(10_000);
    let path = database_path();
    let db = Db::open(&path, 1)?;
    // Continue numbering after existing rows, and vary the RNG per run, so
    // repeated runs add new people instead of duplicating the same ones.
    let existing: i64 =
        db.write_blocking(|c| Ok(c.query_row("SELECT count(*) FROM contacts", [], |r| r.get(0))?))?;
    let mut rng = Rng(0x9E37_79B9_7F4A_7C15 ^ (existing as u64).wrapping_mul(0x2545_F491_4F6C_DD1D));

    let started = Instant::now();
    db.write_blocking(|conn| {
        let tx = conn.transaction()?;

        let mut tag_ids = Vec::new();
        for (name, color) in TAGS {
            tx.execute("INSERT OR IGNORE INTO tags (name, color) VALUES (?, ?)", [name, color])?;
            tag_ids.push(tx.query_row("SELECT id FROM tags WHERE name = ?", [name], |r| r.get(0))?);
        }

        for i in existing as usize..existing as usize + count {
            let first = *rng.pick(FIRST);
            let last = *rng.pick(LAST);
            let handle = format!("{}.{}{}", first, last.replace(['\'', 'ü'], ""), i).to_lowercase();
            let has_company = rng.chance(70);
            let (city, region, country) = *rng.pick(CITIES);

            let mut input = ContactInput {
                first_name: first.into(),
                last_name: last.into(),
                company: if has_company { rng.pick(COMPANIES).to_string() } else { String::new() },
                job_title: if has_company { rng.pick(TITLES).to_string() } else { String::new() },
                birthday: rng.chance(40).then(|| {
                    format!("{}-{:02}-{:02}", 1950 + rng.below(55), 1 + rng.below(12), 1 + rng.below(28))
                }),
                notes: rng.pick(NOTES).to_string(),
                favorite: rng.chance(5),
                emails: vec![LabeledValue { label: "home".into(), value: format!("{handle}@example.com") }],
                phones: vec![LabeledValue {
                    label: "mobile".into(),
                    value: format!("+1 555-{:03}-{:04}", rng.below(1000), rng.below(10_000)),
                }],
                addresses: vec![],
                tag_ids: vec![],
            };
            if has_company && rng.chance(50) {
                let domain = input.company.to_lowercase().replace(' ', "");
                input.emails.push(LabeledValue { label: "work".into(), value: format!("{handle}@{domain}.com") });
            }
            if rng.chance(60) {
                input.addresses.push(Address {
                    label: "home".into(),
                    street: format!("{} {}", 1 + rng.below(9999), rng.pick(STREETS)),
                    city: city.into(),
                    region: region.into(),
                    postal_code: format!("{:05}", rng.below(100_000)),
                    country: country.into(),
                });
            }
            for tag in &tag_ids {
                if rng.chance(12) {
                    input.tag_ids.push(*tag);
                }
            }

            repo::insert_contact(&tx, &input)?;
        }

        tx.commit()?;
        // One big transaction leaves an equally big WAL. Fold it into the
        // database now so a running server's reads don't have to search it.
        conn.query_row("PRAGMA wal_checkpoint(TRUNCATE)", [], |_| Ok(()))?;
        Ok(())
    })?;

    let secs = started.elapsed().as_secs_f64();
    println!(
        "Inserted {count} contacts into {path} in {:.1} ms ({:.0} contacts/sec, each with its emails, phones, addresses, tags and search index row)",
        secs * 1000.0,
        count as f64 / secs
    );
    Ok(())
}
