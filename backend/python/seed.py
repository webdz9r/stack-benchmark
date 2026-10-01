"""Fill the database with fake contacts, all inside one transaction.

    uv run python seed.py 10000

A port of the Rust seeder (same generator, same data for the same starting
state), so the two can be compared on insert speed.
"""

import os
import sys
import time

from app import repo
from app.db import Db
from app.models import Address, ContactInput, LabeledValue

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
    ("Austin", "TX", "USA"), ("Portland", "OR", "USA"), ("Denver", "CO", "USA"),
    ("Toronto", "ON", "Canada"), ("London", "", "UK"), ("Berlin", "", "Germany"),
    ("Chicago", "IL", "USA"), ("Seattle", "WA", "USA"), ("Sydney", "NSW", "Australia"),
]
NOTES = [
    "", "", "", "Met at the conference last spring.", "Prefers email over phone.",
    "Old college friend.", "Introduced by a mutual friend.", "Follow up about the proposal.",
]
TAGS = [
    ("Family", "red"), ("Friends", "amber"), ("Work", "sky"), ("Clients", "green"),
    ("Vendors", "violet"), ("Neighbors", "teal"),
]

MASK = (1 << 64) - 1


class Rng:
    """The Rust seeder's xorshift PRNG, bit for bit."""

    def __init__(self, seed: int):
        self.state = seed & MASK

    def next(self) -> int:
        s = self.state
        s ^= (s << 13) & MASK
        s ^= s >> 7
        s ^= (s << 17) & MASK
        self.state = s
        return s

    def below(self, n: int) -> int:
        return self.next() % n

    def pick(self, items):
        return items[self.below(len(items))]

    def chance(self, percent: int) -> bool:
        return self.next() % 100 < percent


def main() -> None:
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 10_000
    path = os.environ.get("DATABASE_PATH", "data/address-book.db")
    db = Db(path)
    with db.transaction() as tx:
        existing = tx.execute("SELECT count(*) FROM contacts").fetchone()[0]
    rng = Rng(0x9E37_79B9_7F4A_7C15 ^ ((existing * 0x2545_F491_4F6C_DD1D) & MASK))

    started = time.perf_counter()
    with db.transaction() as tx:
        tag_ids = []
        for name, color in TAGS:
            tx.execute("INSERT OR IGNORE INTO tags (name, color) VALUES (?, ?)", (name, color))
            tag_ids.append(tx.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()[0])

        for i in range(existing, existing + count):
            first = rng.pick(FIRST)
            last = rng.pick(LAST)
            handle = f"{first}.{last.replace(chr(39), '').replace('ü', '')}{i}".lower()
            has_company = rng.chance(70)
            city, region, country = rng.pick(CITIES)

            company = rng.pick(COMPANIES) if has_company else ""
            job_title = rng.pick(TITLES) if has_company else ""
            birthday = None
            if rng.chance(40):
                birthday = f"{1950 + rng.below(55)}-{1 + rng.below(12):02}-{1 + rng.below(28):02}"
            notes = rng.pick(NOTES)
            favorite = rng.chance(5)
            phone = f"+1 555-{rng.below(1000):03}-{rng.below(10_000):04}"

            c = ContactInput(
                first_name=first, last_name=last, company=company, job_title=job_title,
                birthday=birthday, notes=notes, favorite=favorite,
                emails=[LabeledValue(label="home", value=f"{handle}@example.com")],
                phones=[LabeledValue(label="mobile", value=phone)],
            )
            if has_company and rng.chance(50):
                domain = company.lower().replace(" ", "")
                c.emails.append(LabeledValue(label="work", value=f"{handle}@{domain}.com"))
            if rng.chance(60):
                c.addresses.append(Address(
                    label="home",
                    street=f"{1 + rng.below(9999)} {rng.pick(STREETS)}",
                    city=city, region=region,
                    postal_code=f"{rng.below(100_000):05}",
                    country=country,
                ))
            c.tag_ids = [t for t in tag_ids if rng.chance(12)]

            repo.insert_contact(tx, c)

    # One big transaction leaves an equally big WAL; fold it in now.
    db.truncate_wal()

    secs = time.perf_counter() - started
    print(
        f"Inserted {count} contacts into {path} in {secs * 1000:.1f} ms "
        f"({count / secs:.0f} contacts/sec, each with its emails, phones, addresses, tags and search index row)"
    )


if __name__ == "__main__":
    main()
