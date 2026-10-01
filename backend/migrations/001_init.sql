CREATE TABLE contacts (
    id          INTEGER PRIMARY KEY,
    first_name  TEXT NOT NULL DEFAULT '',
    last_name   TEXT NOT NULL DEFAULT '',
    company     TEXT NOT NULL DEFAULT '',
    job_title   TEXT NOT NULL DEFAULT '',
    birthday    TEXT,                          -- YYYY-MM-DD
    notes       TEXT NOT NULL DEFAULT '',
    favorite    INTEGER NOT NULL DEFAULT 0 CHECK (favorite IN (0, 1)),
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    -- What the contact files under: last name, else first name, else company.
    sort_key    TEXT GENERATED ALWAYS AS (
        CASE WHEN last_name <> '' THEN last_name
             WHEN first_name <> '' THEN first_name
             ELSE company END
    ) VIRTUAL
);

CREATE INDEX idx_contacts_sort ON contacts (sort_key COLLATE NOCASE, first_name COLLATE NOCASE, id);
CREATE INDEX idx_contacts_favorite ON contacts (favorite) WHERE favorite = 1;

CREATE TABLE emails (
    id          INTEGER PRIMARY KEY,
    contact_id  INTEGER NOT NULL REFERENCES contacts (id) ON DELETE CASCADE,
    label       TEXT NOT NULL DEFAULT 'home',
    value       TEXT NOT NULL,
    position    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_emails_contact ON emails (contact_id, position);

CREATE TABLE phones (
    id          INTEGER PRIMARY KEY,
    contact_id  INTEGER NOT NULL REFERENCES contacts (id) ON DELETE CASCADE,
    label       TEXT NOT NULL DEFAULT 'mobile',
    value       TEXT NOT NULL,
    position    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_phones_contact ON phones (contact_id, position);

CREATE TABLE addresses (
    id          INTEGER PRIMARY KEY,
    contact_id  INTEGER NOT NULL REFERENCES contacts (id) ON DELETE CASCADE,
    label       TEXT NOT NULL DEFAULT 'home',
    street      TEXT NOT NULL DEFAULT '',
    city        TEXT NOT NULL DEFAULT '',
    region      TEXT NOT NULL DEFAULT '',
    postal_code TEXT NOT NULL DEFAULT '',
    country     TEXT NOT NULL DEFAULT '',
    position    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_addresses_contact ON addresses (contact_id, position);

CREATE TABLE tags (
    id     INTEGER PRIMARY KEY,
    name   TEXT NOT NULL UNIQUE COLLATE NOCASE,
    color  TEXT NOT NULL DEFAULT 'slate'
);

CREATE TABLE contact_tags (
    contact_id  INTEGER NOT NULL REFERENCES contacts (id) ON DELETE CASCADE,
    tag_id      INTEGER NOT NULL REFERENCES tags (id) ON DELETE CASCADE,
    PRIMARY KEY (contact_id, tag_id)
) WITHOUT ROWID;
CREATE INDEX idx_contact_tags_tag ON contact_tags (tag_id, contact_id);

-- Full-text search index. rowid = contacts.id. Rebuilt per contact by the
-- application inside the same transaction as every contact write.
CREATE VIRTUAL TABLE contacts_fts USING fts5 (
    name, company, emails, phones, places, notes,
    tokenize = 'unicode61 remove_diacritics 2',
    prefix = '2 3'
);
