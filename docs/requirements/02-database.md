# 02 — Database

SQLite is the only datastore. Every backend uses the same schema, the same pragmas,
the same checkpoint policy and the same SQL. The SQL below is canonical. Copy it
exactly, and change only the placeholder syntax (`?`, `$1`, `@p`) to suit the
driver.

## 1. SQLite build

- **DB-1** SQLite MUST be version 3.38 or newer, with FTS5 compiled in. The schema
  uses generated columns, FTS5 and `unicode61 remove_diacritics 2`.
- **DB-2** If the stack bundles or compiles SQLite itself, it SHOULD compile with
  `-DSQLITE_DEFAULT_MEMSTATUS=0`. Otherwise every malloc and free takes a global
  mutex, which serializes parallel reads. The Rust reference sets this in
  `backend/rust/.cargo/config.toml`; Go sets it with `CGO_CFLAGS` in its build
  commands. Keep the optimization level when adding the flag: setting
  `CGO_CFLAGS` (or `CFLAGS`) usually *replaces* the defaults, and an unoptimized
  SQLite runs about 3x slower. If the stack uses a prebuilt SQLite, it SHOULD
  instead call `sqlite3_config(SQLITE_CONFIG_MEMSTATUS, 0)` before the first
  connection opens, if its driver exposes that call (C# does, through
  `SQLitePCL.raw.sqlite3_config`; Python can reach it with `ctypes`, before
  `import sqlite3`, which initializes SQLite). This is not a minor tweak: in C# it cut p99 at
  4,000 simulated users from about 350 ms to 11 ms. If neither is possible
  (Rails today; Node gets it by using `better-sqlite3`, Python sets it at runtime through `ctypes`), record that in the stack's README.
  `PRAGMA compile_options` shows whether the build flag took effect
  (`DEFAULT_MEMSTATUS=0`); the runtime call doesn't show up there.
  Also make sure `SQLITE_ENABLE_MEMORY_MANAGEMENT` is **not** defined: with it,
  every connection shares one page cache behind a global mutex taken on each page
  fetch, which serializes the readers too. Rust's `libsqlite3-sys` defines it by
  default, so the reference undefines it (`-USQLITE_ENABLE_MEMORY_MANAGEMENT`);
  `PRAGMA compile_options` lists `ENABLE_MEMORY_MANAGEMENT` if it's on.

## 2. Migrations

The schema lives in `backend/migrations/NNN_name.sql`. There are currently two files:

- `001_init.sql`: the tables, indexes and FTS table
- `002_sort_letter.sql`: the `sort_letter` generated column and its index

- **DB-3** Migrations MUST be discovered from `backend/migrations/` (read at runtime,
  or embedded at build time) and applied in filename order.
- **DB-4** `PRAGMA user_version` records how many migrations have run. On startup,
  for each migration `i` (1-based) with `i > user_version`:
  1. begin a transaction
  2. execute the whole file (it contains several statements)
  3. `PRAGMA user_version = i`
  4. commit

  Migrations MUST be atomic: either each one in its own transaction (as above, the
  Rust reference), or all pending migrations in one transaction (the other stacks).
  Use `BEGIN IMMEDIATE`, so that workers starting at the same time don't both run
  the same migration. A database created by any stack MUST be usable by every other
  stack.
- **DB-5** Migrations run on the writer connection, before readers open
  (ARCH-14).

### Resulting schema (for reference; the SQL files are authoritative)

```
contacts(id INTEGER PK, first_name, last_name, company, job_title TEXT NOT NULL DEFAULT '',
         birthday TEXT NULL /* YYYY-MM-DD */, notes TEXT NOT NULL DEFAULT '',
         favorite INTEGER NOT NULL DEFAULT 0 CHECK (0,1),
         created_at, updated_at TEXT NOT NULL DEFAULT strftime('%Y-%m-%dT%H:%M:%fZ','now'),
         sort_key    GENERATED VIRTUAL = last_name, else first_name, else company,
         sort_letter GENERATED VIRTUAL = '#' | 'A'..'Z' | '~')
  idx_contacts_sort     (sort_key COLLATE NOCASE, first_name COLLATE NOCASE, id)
  idx_contacts_favorite (favorite) WHERE favorite = 1
  idx_contacts_letter   (sort_letter)

emails   (id PK, contact_id FK→contacts ON DELETE CASCADE, label DEFAULT 'home',   value NOT NULL, position)
phones   (id PK, contact_id FK→contacts ON DELETE CASCADE, label DEFAULT 'mobile', value NOT NULL, position)
addresses(id PK, contact_id FK→contacts ON DELETE CASCADE, label DEFAULT 'home',
          street, city, region, postal_code, country, position)
  each indexed on (contact_id, position)

tags        (id PK, name TEXT NOT NULL UNIQUE COLLATE NOCASE, color DEFAULT 'slate')
contact_tags(contact_id FK CASCADE, tag_id FK CASCADE, PK(contact_id, tag_id)) WITHOUT ROWID
  idx_contact_tags_tag (tag_id, contact_id)

contacts_fts USING fts5(name, company, emails, phones, places, notes,
                        tokenize='unicode61 remove_diacritics 2', prefix='2 3')
  rowid = contacts.id; maintained by the application, not by triggers
```

`sort_letter` buckets follow the list's NOCASE sort order, so each bucket is
contiguous in the list:

- `'#'`: names whose first character sorts before `a` (digits, punctuation)
- `'A'`..`'Z'`
- `'~'`: names whose first character sorts after `z` (accented and non-Latin
  letters)

The API reports `'~'` as `'#'` (see API-L3).

## 3. Connection pragmas

- **DB-6** Every connection, both writer and readers, MUST run this when it opens.
  The busy timeout MAY instead be set through the driver's own busy handler with
  the same 5 s limit (for example the sqlite3 gem's `busy_handler_timeout`, which
  releases Ruby's lock while it waits):

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA busy_timeout = 5000;
PRAGMA foreign_keys = ON;
PRAGMA cache_size = -64000;        -- 64 MB page cache
PRAGMA temp_store = MEMORY;
PRAGMA mmap_size = 268435456;      -- 256 MB
PRAGMA journal_size_limit = 67108864;  -- 64 MB
```

`foreign_keys = ON` is required for correct behavior: it drives cascading deletes
and the "tag does not exist" validation error.

## 4. WAL checkpointing

SQLite's automatic checkpoint only runs right after a commit, and it can't finish
while readers are still using older pages. If writes then stop, the WAL stays large
and every read has to search it. In load tests, a leftover 365 MB WAL made list
reads about 8x slower. Under constant reads the WAL also never restarts from the
top, so the file keeps growing.

- **DB-7** A background task MUST run every **5 seconds** on the **writer
  connection** (so it is serialized with writes), doing the following:

```
const RESET_AT_PAGES = 16384          // 64 MB of 4 KB pages

(busy, wal_pages, copied) = PRAGMA wal_checkpoint(PASSIVE)
if wal_pages < RESET_AT_PAGES or copied < wal_pages:
    return
set busy_timeout = 50 ms
PRAGMA wal_checkpoint(TRUNCATE)       // ignore a busy result; try again next tick
set busy_timeout = 5000 ms            // always restore, even on error
```

- **DB-8** Checkpoint errors MUST be logged as warnings and MUST NOT stop the task.
- **DB-9** In multi-process stacks, every process MAY run the task. Concurrent
  checkpoints are safe.
- **DB-10** After its single big transaction, the seeder MUST run
  `PRAGMA wal_checkpoint(TRUNCATE)` (see [05-seeder.md](05-seeder.md)).

## 5. Transactions

| Operation | Transaction |
| --- | --- |
| Create contact | One transaction: insert contact, insert children, rebuild the FTS row, read the contact back, commit |
| Replace contact | One transaction: update contact, delete children, insert children, rebuild the FTS row, read back, commit |
| Delete contact | One transaction: delete the FTS row, delete the contact (children cascade) |
| Set favorite | A single statement (autocommit, or wrapped in a transaction) |
| Tag create, update, delete | A single statement each (plus the read-back of the tag); a transaction MAY wrap it |
| Seeder | Everything in **one** transaction |

- **DB-11** A failed write MUST roll back completely. No partial contact, child row
  or FTS row may be left behind.

## 6. Full-text search

### 6.1 Index maintenance

The FTS row for a contact (`rowid = contacts.id`) MUST be rebuilt inside the same
transaction as **every** contact insert and replace, **after** the child rows have
been written:

```sql
DELETE FROM contacts_fts WHERE rowid = ?;

INSERT INTO contacts_fts (rowid, name, company, emails, phones, places, notes)
SELECT c.id,
       c.first_name || ' ' || c.last_name,
       c.company || ' ' || c.job_title,
       coalesce((SELECT group_concat(value, ' ') FROM emails WHERE contact_id = c.id), ''),
       coalesce((SELECT group_concat(value, ' ') FROM phones WHERE contact_id = c.id), ''),
       coalesce((SELECT group_concat(street || ' ' || city || ' ' || region || ' ' || country, ' ')
                 FROM addresses WHERE contact_id = c.id), ''),
       c.notes
FROM contacts c WHERE c.id = ?;
```

Note that `postal_code` is **not** indexed, and tags are not part of the search.

On contact delete: `DELETE FROM contacts_fts WHERE rowid = ?` (the FTS table has
no foreign key, so it doesn't cascade). `PUT /favorite` and tag changes don't touch
the FTS table.

### 6.2 Query building (`fts_query`)

User search text becomes a safe FTS5 expression. Every word becomes a quoted
prefix term, and all terms must match.

```
fts_query(input):
  split input on every character that is NOT a word character, where a word
  character is a code point whose Unicode general category is a Letter (L*),
  a Mark (M*) or a Number (N*), or one of '@', '.', '\'' (apostrophe)
  drop empty pieces
  for each piece t:  term = '"' + t.replace('"', '""') + '"*'
  if there are no terms: return NONE      // treated as "no search filter"
  return terms joined with a single space
```

Examples:

| Input | FTS expression |
| --- | --- |
| `jo smi` | `"jo"* "smi"*` |
| `Smith ` | `"Smith"*` |
| `o'bri` | `"o'bri"*` |
| `martinez@` | `"martinez@"*` |
| `ava.walsh1` | `"ava.walsh1"*` |
| `555-12` | `"555"* "12"*` |
| `"quoted"` | `"quoted"*` |
| `***` | NONE (no filter; all contacts) |
| `müller` | `"müller"*` (ü is a letter) |
| `xu²` | `"xu²"*` (² is a Number, No) |
| `Ⅻ` | `"Ⅻ"*` (a Letter Number, Nl) |
| `cafe` + U+0301 | `"café"*` (the combining accent is a Mark, Mn) |
| `नमस्ते` | `"नमस्ते"*` (the vowel signs are Marks, Mc/Mn) |

- **DB-12** Word characters MUST be decided by Unicode general category, per
  **code point** (not per UTF-16 unit, or astral characters get split). Keeping
  marks matches FTS5's `unicode61` tokenizer, which treats them as part of a
  token. The parity check tests `xu²`, `Ⅻ`, a combining accent and Devanagari.

  | Language | Word character test |
  | --- | --- |
  | Rust | `unicode_general_category::get_general_category(c)` is a Letter, Mark or Number |
  | C | a generated table of L/M/N code point ranges, searched per decoded code point (`backend/c/scripts/gen_unicode.py`) |
  | Go | `unicode.IsLetter(r) \|\| unicode.IsMark(r) \|\| unicode.IsNumber(r)` |
  | C# | iterate `EnumerateRunes()`; `Rune.GetUnicodeCategory(r) <= UnicodeCategory.OtherNumber` |
  | Java | `Character.getType(cp)` is one of the five letter, three mark or three number types, per code point |
  | JS | `/[\p{L}\p{M}\p{N}]/u` |
  | Python | `unicodedata.category(ch)[0] in "LMN"` |
  | Ruby | `/[\p{L}\p{M}\p{N}]/` |

  Don't use "alphanumeric" helpers: Python's `str.isalnum()` misses marks; C#'s
  `char.IsLetterOrDigit` misses marks, `²` and `Ⅻ`; Ruby's `\p{Alnum}` misses `²`.
- **DB-13** Case is left alone. FTS5's `unicode61` tokenizer folds case and
  diacritics itself.

## 7. Canonical queries

`CONTACT_ORDER` = `c.sort_key COLLATE NOCASE, c.first_name COLLATE NOCASE, c.id`
(covered by `idx_contacts_sort`). It is the one sort order for contact lists.

### 7.1 Filters (shared by list and letters)

Build a WHERE clause from these fragments, joined with `AND`, in this order, each
included only when it applies:

| Condition | Fragment | Bind |
| --- | --- | --- |
| `fts_query(q)` is not NONE | `c.id IN (SELECT rowid FROM contacts_fts WHERE contacts_fts MATCH ?)` | the FTS expression |
| `tag` given | `c.id IN (SELECT contact_id FROM contact_tags WHERE tag_id = ?)` | tag id |
| `favorite == true` | `c.favorite = 1` | — |

Use `IN (subquery)`, not `EXISTS`: the tag-filtered list goes from 16 ms to 7 ms.

### 7.2 List page

```sql
SELECT count(*) FROM contacts c {where};

SELECT c.id, c.first_name, c.last_name, c.company, c.job_title, c.favorite,
       (SELECT value FROM emails WHERE contact_id = c.id ORDER BY position LIMIT 1),
       (SELECT value FROM phones WHERE contact_id = c.id ORDER BY position LIMIT 1),
       (SELECT group_concat(tag_id) FROM contact_tags WHERE contact_id = c.id)
FROM contacts c
{where}
ORDER BY c.sort_key COLLATE NOCASE, c.first_name COLLATE NOCASE, c.id
LIMIT ? OFFSET ?;
```

`group_concat(tag_id)` gives a comma-separated string, or NULL. Parse it into an
integer array, `[]` for NULL. Because `contact_tags` is a WITHOUT ROWID table keyed
on `(contact_id, tag_id)`, the ids come back in ascending order.

### 7.3 Letter index

```sql
SELECT c.sort_letter, count(*) FROM contacts c {where}
GROUP BY c.sort_letter ORDER BY c.sort_letter;
```

The folding into the response is described in API-L3.

### 7.4 Single contact

```sql
SELECT id, first_name, last_name, company, job_title, birthday, notes, favorite,
       created_at, updated_at
FROM contacts WHERE id = ?;

SELECT label, value FROM emails WHERE contact_id = ? ORDER BY position;
SELECT label, value FROM phones WHERE contact_id = ? ORDER BY position;
SELECT label, street, city, region, postal_code, country
  FROM addresses WHERE contact_id = ? ORDER BY position;
SELECT t.id, t.name, t.color FROM tags t
  JOIN contact_tags ct ON ct.tag_id = t.id
  WHERE ct.contact_id = ? ORDER BY t.name COLLATE NOCASE;
```

### 7.5 Insert and replace a contact

```sql
-- insert
INSERT INTO contacts (first_name, last_name, company, job_title, birthday, notes, favorite)
VALUES (?, ?, ?, ?, ?, ?, ?);
-- id = last_insert_rowid()

-- replace (0 rows changed → 404)
UPDATE contacts SET first_name = ?, last_name = ?, company = ?, job_title = ?,
    birthday = ?, notes = ?, favorite = ?,
    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE id = ?;
DELETE FROM emails       WHERE contact_id = ?;
DELETE FROM phones       WHERE contact_id = ?;
DELETE FROM addresses    WHERE contact_id = ?;
DELETE FROM contact_tags WHERE contact_id = ?;

-- children (both paths); position = 0-based index in the validated input array
INSERT INTO emails    (contact_id, label, value, position) VALUES (?, ?, ?, ?);
INSERT INTO phones    (contact_id, label, value, position) VALUES (?, ?, ?, ?);
INSERT INTO addresses (contact_id, label, street, city, region, postal_code, country, position)
  VALUES (?, ?, ?, ?, ?, ?, ?, ?);
INSERT INTO contact_tags (contact_id, tag_id) VALUES (?, ?);   -- in ascending tag_id order

-- then rebuild the FTS row (§6.1)
```

Children are inserted in this order: emails, phones, addresses, tags.

If a `contact_tags` insert fails a constraint (a foreign key, because the tag
doesn't exist), the error MUST become `422 {"error":"tag <id> does not exist"}`
for that tag id, and the transaction rolls back.

`favorite` is stored as `0` or `1`. `birthday` is stored as NULL when absent.

### 7.6 Other writes

```sql
-- favorite (0 rows → 404)
UPDATE contacts SET favorite = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?;

-- delete contact (in one transaction; 0 rows from the second statement → 404)
DELETE FROM contacts_fts WHERE rowid = ?;
DELETE FROM contacts WHERE id = ?;
```

### 7.7 Tags

```sql
-- list
SELECT t.id, t.name, t.color, count(ct.contact_id)
FROM tags t LEFT JOIN contact_tags ct ON ct.tag_id = t.id
GROUP BY t.id ORDER BY t.name COLLATE NOCASE;

-- get
SELECT id, name, color FROM tags WHERE id = ?;

-- create (color defaults to 'slate'), then get(last_insert_rowid())
INSERT INTO tags (name, color) VALUES (?, ?);

-- update: a NULL color keeps the current one (0 rows → 404), then get(id)
UPDATE tags SET name = ?, color = coalesce(?, color) WHERE id = ?;

-- delete (0 rows → 404); contact_tags rows cascade
DELETE FROM tags WHERE id = ?;
```

### 7.8 Stats

```sql
SELECT count(*), coalesce(sum(favorite), 0) FROM contacts;
```

## 8. Driver usage

- **DB-14** Prepared statements SHOULD be cached per connection (for example
  rusqlite's `prepare_cached`, or a statement cache in the driver).
- **DB-15** The ORM variant (Rails + ActiveRecord) is the only stack allowed to
  replace this SQL with ORM calls. A new direct-SQL stack MUST NOT use an ORM or
  query builder that changes the SQL sent to SQLite.
