# 05 — Seeder (deterministic fake data)

Every stack ships a seeder that inserts fake contacts. Two runs of the seeder on
empty databases, in **any** two stacks, MUST produce identical data: the same rows,
the same ids and the same values. Only `created_at` and `updated_at` may differ.
This is what makes one stack's benchmark comparable with another's, and it lets
each stack seed its own database.

The algorithm below is exact. Follow the order of random draws precisely: one
extra or missing `next()` call shifts every later contact.

## 1. CLI

- **SEED-1** Invocation: `<seeder> [COUNT]`. `COUNT` defaults to `10000`. The seeder
  reads `DATABASE_PATH` (same default as the server), creates the file and runs the
  migrations if needed.
- **SEED-2** When done it prints one line to stdout:
  `Inserted {count} contacts into {path} in {ms:.1} ms ({rate:.0} contacts/sec, each with its emails, phones, addresses, tags and search index row)`.
  The benchmark script only echoes this line, but keep the format.
- **SEED-3** It exits non-zero on error.

## 2. Transaction and index maintenance

- **SEED-4** Everything, tags and contacts, is inserted in **one transaction**, with a
  single commit. That means one fsync, instead of one per contact.
- **SEED-5** Contacts MUST be inserted through the **same insert path as `POST
  /api/contacts`** (§7.5 of [02-database.md](02-database.md#75-insert-and-replace-a-contact)):
  the contact row, then emails, phones, addresses and tag links with positions,
  then the FTS rebuild. The generated input is already clean, so validation is
  skipped.
- **SEED-6** After the commit, run `PRAGMA wal_checkpoint(TRUNCATE)`. One big
  transaction leaves an equally big WAL.
- **SEED-7** The ORM variant is the only one that may insert through its models.

## 3. Random number generator

A 64-bit **xorshift** generator. All arithmetic is on unsigned 64-bit integers, and
left shifts drop overflowing bits.

```
state: u64

next():
    state ^= state << 13
    state ^= state >> 7        // logical (unsigned) shift
    state ^= state << 17
    return state

below(n):  return next() % n               // n is a small positive integer
pick(arr): return arr[below(len(arr))]
chance(p): return next() % 100 < p         // p is a percentage
```

Initial state:

```
existing = SELECT count(*) FROM contacts            // before seeding
state    = 0x9E3779B97F4A7C15 XOR (existing * 0x2545F4914F6CDD1D mod 2^64)
```

So repeated runs append new people instead of repeating the same ones.

> Language notes: in JavaScript use `BigInt` and mask with `& 0xFFFFFFFFFFFFFFFFn`
> after every left shift. In Python mask with `& 0xFFFFFFFFFFFFFFFF`. In Java or
> Kotlin use `long` with `>>>` and `Long.remainderUnsigned`. In C# use `ulong`.

## 4. Word lists (exact, in order)

```
FIRST (60) = Ava, Liam, Olivia, Noah, Emma, Oliver, Sophia, Elijah, Isabella, James,
  Mia, Lucas, Amelia, Mateo, Harper, Benjamin, Evelyn, Henry, Aria, Theo,
  Chloe, Samuel, Priya, Arjun, Mei, Hiroshi, Fatima, Omar, Zoe, Diego,
  Sofia, Jonas, Ingrid, Kwame, Amara, Chen, Yuki, Leila, Rafael, Nadia,
  Grace, Ethan, Hannah, Isaac, Julia, Kofi, Lena, Marcus, Nina, Oscar,
  Paula, Quinn, Rosa, Sean, Tara, Umar, Vera, Wes, Ximena, Yusuf

LAST (64) = Smith, Johnson, Williams, Brown, Jones, Garcia, Miller, Davis, Rodriguez,
  Martinez, Hernandez, Lopez, Wilson, Anderson, Thomas, Taylor, Moore, Jackson,
  Martin, Lee, Patel, Nguyen, Kim, Tanaka, Okafor, Müller, Rossi, Dubois,
  Kowalski, Haddad, O'Brien, Andersen, Silva, Cohen, Novak, Park, Singh,
  Bakker, Castillo, Dimitrov, Eriksson, Fischer, Gonzaga, Horvat, Ivanova,
  Jensen, Kaur, Larsen, Mendes, Nakamura, Osei, Petrov, Quintero, Reyes,
  Sato, Tremblay, Ueda, Varga, Walsh, Xu, Yilmaz, Zhou, Abara, Byrne

COMPANIES (18) = Acme Corp, Globex, Initech, Umbrella, Hooli, Stark Industries,
  Wayne Enterprises, Pied Piper, Soylent, Wonka Industries, Cyberdyne, Tyrell Corp,
  Vandelay Industries, Dunder Mifflin, Massive Dynamic, Aperture Science, Oscorp,
  Gringotts

TITLES (12) = Engineer, Designer, Product Manager, Sales Lead, CTO, Founder, Accountant,
  Consultant, Recruiter, Data Scientist, Marketing Director, Support Specialist

STREETS (8) = Main St, Oak Ave, Maple Dr, Cedar Ln, Pine St, Elm St, Park Ave, Lake Rd

CITIES (9) = (Austin, TX, USA), (Portland, OR, USA), (Denver, CO, USA),
  (Toronto, ON, Canada), (London, "", UK), (Berlin, "", Germany),
  (Chicago, IL, USA), (Seattle, WA, USA), (Sydney, NSW, Australia)

NOTES (8) = "", "", "", "Met at the conference last spring.", "Prefers email over phone.",
  "Old college friend.", "Introduced by a mutual friend.", "Follow up about the proposal."

TAGS (6) = (Family, red), (Friends, amber), (Work, sky), (Clients, green),
  (Vendors, violet), (Neighbors, teal)
```

`Müller` is `M` + U+00FC + `ller` (precomposed, not a combining mark). `O'Brien`
uses an ASCII apostrophe (U+0027).

## 5. Algorithm

```
tag_ids = []
for (name, color) in TAGS:
    INSERT OR IGNORE INTO tags (name, color) VALUES (name, color)
    tag_ids.push( SELECT id FROM tags WHERE name = name )

for i in existing ..< existing + count:
    first       = pick(FIRST)                                   // draw 1
    last        = pick(LAST)                                    // draw 2
    handle      = lowercase(first + "." + remove_chars(last, ["'", "ü"]) + str(i))
    has_company = chance(70)                                    // draw 3
    (city, region, country) = pick(CITIES)                      // draw 4

    company   = has_company ? pick(COMPANIES) : ""              // draw only if has_company
    job_title = has_company ? pick(TITLES)    : ""              // draw only if has_company

    if chance(40):                                              // birthday?
        y = 1950 + below(55)
        m = 1 + below(12)
        d = 1 + below(28)
        birthday = format("%04d-%02d-%02d", y, m, d)
    else:
        birthday = null

    notes    = pick(NOTES)
    favorite = chance(5)

    emails = [ {label: "home", value: handle + "@example.com"} ]
    phones = [ {label: "mobile",
                value: format("+1 555-%03d-%04d", below(1000), below(10000))} ]   // two draws, in this order
    addresses = []
    tags      = []

    if has_company and chance(50):                              // chance drawn ONLY if has_company
        domain = lowercase(company).remove(" ")                 // "Acme Corp" -> "acmecorp"
        emails.push({label: "work", value: handle + "@" + domain + ".com"})

    if chance(60):
        number      = 1 + below(9999)
        street_name = pick(STREETS)
        postal      = format("%05d", below(100000))
        addresses.push({label: "home", street: str(number) + " " + street_name,
                        city, region, postal_code: postal, country})

    for tag in tag_ids:                                         // always 6 draws, in TAGS order
        if chance(12): tags.push(tag)

    insert_contact(first, last, company, job_title, birthday, notes, favorite,
                   emails, phones, addresses, tags)

COMMIT
PRAGMA wal_checkpoint(TRUNCATE)
```

Easy things to get wrong:

- `handle` removes the apostrophe and the `ü` from the **last name before**
  lowercasing, so `Müller` becomes `mller` and `O'Brien` becomes `obrien`. Example:
  `ava.mller17`.
- `i` is the global contact index, starting at `existing`, not at 1.
- The `chance(50)` for a work email is **not drawn** when `has_company` is false
  (short-circuit).
- The birthday draws happen in the order year, month, day. The phone draws happen
  in the order 3-digit part, then 4-digit part.
- The street draws happen in the order number, street name, postal code.
- `favorite` is stored as 0/1, and `birthday` as NULL when absent.
- Positions: the home email is 0, the work email is 1; phone 0; address 0.

On an empty database, tags get ids 1–6 in `TAGS` order, and contacts get ids
`1..count`.
