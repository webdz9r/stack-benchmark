"""Plain synchronous SQL; the same statements as the Rust backend's repo.rs."""

import sqlite3
import unicodedata

from .errors import AppError
from .models import ContactInput, TagInput

MAX_PAGE = 200
CONTACT_ORDER = "c.sort_key COLLATE NOCASE, c.first_name COLLATE NOCASE, c.id"
NOW = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"

# ---------------------------------------------------------------- contacts


def fts_query(text: str | None) -> str | None:
    """Free text -> safe FTS5 query: each word a quoted prefix term.
    `jo smi` -> `"jo"* "smi"*`. A word is made of Unicode letters, marks and
    numbers (general categories L*, M*, N*), plus `@ . '`."""
    if not text:
        return None
    terms, word = [], []
    for ch in text + " ":
        if ch in "@.'" or unicodedata.category(ch)[0] in "LMN":
            word.append(ch)
        elif word:
            terms.append("".join(word))
            word = []
    if not terms:
        return None
    return " ".join('"' + t.replace('"', '""') + '"*' for t in terms)


def _filters(q: str | None, tag: int | None, favorite: bool | None) -> tuple[str, list]:
    clauses, args = [], []
    fts = fts_query(q)
    if fts:
        clauses.append("c.id IN (SELECT rowid FROM contacts_fts WHERE contacts_fts MATCH ?)")
        args.append(fts)
    if tag is not None:
        clauses.append("c.id IN (SELECT contact_id FROM contact_tags WHERE tag_id = ?)")
        args.append(tag)
    if favorite:
        clauses.append("c.favorite = 1")
    return ("WHERE " + " AND ".join(clauses) if clauses else ""), args


def list_contacts(conn, q, tag, favorite, limit, offset) -> dict:
    limit = max(1, min(limit if limit is not None else 50, MAX_PAGE))
    offset = max(0, offset or 0)
    where, args = _filters(q, tag, favorite)

    total = conn.execute(f"SELECT count(*) FROM contacts c {where}", args).fetchone()[0]
    rows = conn.execute(
        f"""SELECT c.id, c.first_name, c.last_name, c.company, c.job_title, c.favorite,
                (SELECT value FROM emails WHERE contact_id = c.id ORDER BY position LIMIT 1),
                (SELECT value FROM phones WHERE contact_id = c.id ORDER BY position LIMIT 1),
                (SELECT group_concat(tag_id) FROM contact_tags WHERE contact_id = c.id)
            FROM contacts c
            {where}
            ORDER BY {CONTACT_ORDER}
            LIMIT ? OFFSET ?""",
        [*args, limit, offset],
    ).fetchall()
    items = [
        {
            "id": r[0], "first_name": r[1], "last_name": r[2], "company": r[3],
            "job_title": r[4], "favorite": bool(r[5]), "email": r[6], "phone": r[7],
            "tag_ids": [int(t) for t in r[8].split(",")] if r[8] else [],
        }
        for r in rows
    ]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def list_letters(conn, q, tag, favorite) -> list[dict]:
    """Where each file letter starts in the sorted, filtered list. Buckets
    are contiguous and sort like the list ('#' < 'A'..'Z' < '~'), so offsets
    are running totals; '~' (after Z) is reported as '#'."""
    where, args = _filters(q, tag, favorite)
    buckets = conn.execute(
        f"SELECT c.sort_letter, count(*) FROM contacts c {where} "
        "GROUP BY c.sort_letter ORDER BY c.sort_letter",
        args,
    ).fetchall()
    letters, offset = [], 0
    for letter, count in buckets:
        if letter == "~":
            existing = next((l for l in letters if l["letter"] == "#"), None)
            if existing:
                existing["count"] += count
            else:
                letters.append({"letter": "#", "offset": offset, "count": count})
        else:
            letters.append({"letter": letter, "offset": offset, "count": count})
        offset += count
    return letters


def get_contact(conn, contact_id: int) -> dict:
    r = conn.execute(
        """SELECT id, first_name, last_name, company, job_title, birthday, notes, favorite,
                  created_at, updated_at
           FROM contacts WHERE id = ?""",
        (contact_id,),
    ).fetchone()
    if r is None:
        raise AppError.not_found()
    labeled = lambda table: [  # noqa: E731
        {"label": label, "value": value}
        for label, value in conn.execute(
            f"SELECT label, value FROM {table} WHERE contact_id = ? ORDER BY position", (contact_id,)
        )
    ]
    return {
        "id": r[0], "first_name": r[1], "last_name": r[2], "company": r[3], "job_title": r[4],
        "birthday": r[5], "notes": r[6], "favorite": bool(r[7]),
        "emails": labeled("emails"),
        "phones": labeled("phones"),
        "addresses": [
            dict(zip(("label", "street", "city", "region", "postal_code", "country"), a))
            for a in conn.execute(
                """SELECT label, street, city, region, postal_code, country
                   FROM addresses WHERE contact_id = ? ORDER BY position""",
                (contact_id,),
            )
        ],
        "tags": [
            {"id": t[0], "name": t[1], "color": t[2]}
            for t in conn.execute(
                """SELECT t.id, t.name, t.color FROM tags t
                   JOIN contact_tags ct ON ct.tag_id = t.id
                   WHERE ct.contact_id = ? ORDER BY t.name COLLATE NOCASE""",
                (contact_id,),
            )
        ],
        "created_at": r[8],
        "updated_at": r[9],
    }


def insert_contact(tx, c: ContactInput) -> int:
    cur = tx.execute(
        """INSERT INTO contacts (first_name, last_name, company, job_title, birthday, notes, favorite)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (c.first_name, c.last_name, c.company, c.job_title, c.birthday, c.notes, c.favorite),
    )
    contact_id = cur.lastrowid
    _write_children(tx, contact_id, c)
    _refresh_fts(tx, contact_id)
    return contact_id


def update_contact(tx, contact_id: int, c: ContactInput) -> None:
    cur = tx.execute(
        f"""UPDATE contacts SET first_name = ?, last_name = ?, company = ?, job_title = ?,
               birthday = ?, notes = ?, favorite = ?, updated_at = {NOW}
            WHERE id = ?""",
        (c.first_name, c.last_name, c.company, c.job_title, c.birthday, c.notes, c.favorite, contact_id),
    )
    if cur.rowcount == 0:
        raise AppError.not_found()
    for table in ("emails", "phones", "addresses", "contact_tags"):
        tx.execute(f"DELETE FROM {table} WHERE contact_id = ?", (contact_id,))
    _write_children(tx, contact_id, c)
    _refresh_fts(tx, contact_id)


def set_favorite(tx, contact_id: int, favorite: bool) -> None:
    cur = tx.execute(
        f"UPDATE contacts SET favorite = ?, updated_at = {NOW} WHERE id = ?", (favorite, contact_id)
    )
    if cur.rowcount == 0:
        raise AppError.not_found()


def delete_contact(tx, contact_id: int) -> None:
    # Children go via ON DELETE CASCADE; the FTS table has no foreign key.
    tx.execute("DELETE FROM contacts_fts WHERE rowid = ?", (contact_id,))
    if tx.execute("DELETE FROM contacts WHERE id = ?", (contact_id,)).rowcount == 0:
        raise AppError.not_found()


def _write_children(tx, contact_id: int, c: ContactInput) -> None:
    tx.executemany(
        "INSERT INTO emails (contact_id, label, value, position) VALUES (?, ?, ?, ?)",
        [(contact_id, e.label, e.value, i) for i, e in enumerate(c.emails)],
    )
    tx.executemany(
        "INSERT INTO phones (contact_id, label, value, position) VALUES (?, ?, ?, ?)",
        [(contact_id, p.label, p.value, i) for i, p in enumerate(c.phones)],
    )
    tx.executemany(
        """INSERT INTO addresses (contact_id, label, street, city, region, postal_code, country, position)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (contact_id, a.label, a.street, a.city, a.region, a.postal_code, a.country, i)
            for i, a in enumerate(c.addresses)
        ],
    )
    for tag_id in c.tag_ids:
        try:
            tx.execute("INSERT INTO contact_tags (contact_id, tag_id) VALUES (?, ?)", (contact_id, tag_id))
        except sqlite3.IntegrityError:
            raise AppError.validation(f"tag {tag_id} does not exist") from None


def _refresh_fts(tx, contact_id: int) -> None:
    """Rebuild one contact's search document from its current rows."""
    tx.execute("DELETE FROM contacts_fts WHERE rowid = ?", (contact_id,))
    tx.execute(
        """INSERT INTO contacts_fts (rowid, name, company, emails, phones, places, notes)
           SELECT c.id,
                  c.first_name || ' ' || c.last_name,
                  c.company || ' ' || c.job_title,
                  coalesce((SELECT group_concat(value, ' ') FROM emails WHERE contact_id = c.id), ''),
                  coalesce((SELECT group_concat(value, ' ') FROM phones WHERE contact_id = c.id), ''),
                  coalesce((SELECT group_concat(street || ' ' || city || ' ' || region || ' ' || country, ' ')
                            FROM addresses WHERE contact_id = c.id), ''),
                  c.notes
           FROM contacts c WHERE c.id = ?""",
        (contact_id,),
    )


# ---------------------------------------------------------------- tags


def list_tags(conn) -> list[dict]:
    return [
        {"id": r[0], "name": r[1], "color": r[2], "contact_count": r[3]}
        for r in conn.execute(
            """SELECT t.id, t.name, t.color, count(ct.contact_id)
               FROM tags t LEFT JOIN contact_tags ct ON ct.tag_id = t.id
               GROUP BY t.id ORDER BY t.name COLLATE NOCASE"""
        )
    ]


def get_tag(conn, tag_id: int) -> dict:
    r = conn.execute("SELECT id, name, color FROM tags WHERE id = ?", (tag_id,)).fetchone()
    if r is None:
        raise AppError.not_found()
    return {"id": r[0], "name": r[1], "color": r[2]}


def insert_tag(tx, t: TagInput) -> dict:
    try:
        cur = tx.execute("INSERT INTO tags (name, color) VALUES (?, ?)", (t.name, t.color or "slate"))
    except sqlite3.IntegrityError:
        raise AppError.conflict(f"a tag named '{t.name}' already exists") from None
    return get_tag(tx, cur.lastrowid)


def update_tag(tx, tag_id: int, t: TagInput) -> dict:
    try:
        cur = tx.execute(
            "UPDATE tags SET name = ?, color = coalesce(?, color) WHERE id = ?", (t.name, t.color, tag_id)
        )
    except sqlite3.IntegrityError:
        raise AppError.conflict(f"a tag named '{t.name}' already exists") from None
    if cur.rowcount == 0:
        raise AppError.not_found()
    return get_tag(tx, tag_id)


def delete_tag(tx, tag_id: int) -> None:
    if tx.execute("DELETE FROM tags WHERE id = ?", (tag_id,)).rowcount == 0:
        raise AppError.not_found()


# ---------------------------------------------------------------- stats


def stats(conn) -> dict:
    contacts, favorites = conn.execute(
        "SELECT count(*), coalesce(sum(favorite), 0) FROM contacts"
    ).fetchone()
    return {"contacts": contacts, "favorites": favorites}
