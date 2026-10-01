//! Plain synchronous SQL functions. Callers run these on the read pool or the
//! write connection via `Db::read` / `Db::write`.

use r2d2_sqlite::rusqlite::types::Value;
use r2d2_sqlite::rusqlite::{self, Connection, Row, Transaction, params, params_from_iter};

use crate::error::AppError;
use crate::models::*;

const MAX_PAGE: i64 = 200;

/// The one sort order for contact lists. `idx_contacts_sort` covers it.
const CONTACT_ORDER: &str = "c.sort_key COLLATE NOCASE, c.first_name COLLATE NOCASE, c.id";

// ---------------------------------------------------------------- contacts

/// WHERE clause and bind values for the search/tag/favorite filters.
fn contact_filters(q: &ListQuery) -> (String, Vec<Value>) {
    let mut filters = Vec::new();
    let mut args: Vec<Value> = Vec::new();

    if let Some(fts) = q.q.as_deref().and_then(fts_query) {
        filters.push("c.id IN (SELECT rowid FROM contacts_fts WHERE contacts_fts MATCH ?)");
        args.push(fts.into());
    }
    if let Some(tag) = q.tag {
        filters.push("c.id IN (SELECT contact_id FROM contact_tags WHERE tag_id = ?)");
        args.push(tag.into());
    }
    if q.favorite == Some(true) {
        filters.push("c.favorite = 1");
    }
    let where_sql = if filters.is_empty() {
        String::new()
    } else {
        format!("WHERE {}", filters.join(" AND "))
    };
    (where_sql, args)
}

/// For each file letter, where its first contact sits in the sorted, filtered
/// list, so the UI can jump there by fetching the page at that offset.
///
/// `sort_letter` buckets are contiguous in list order and sort the same way
/// ('#' < 'A'..'Z' < '~'), so offsets are running totals of the counts.
pub fn list_letters(conn: &Connection, q: &ListQuery) -> Result<Vec<LetterIndex>, AppError> {
    let (where_sql, args) = contact_filters(q);
    let sql = format!(
        "SELECT c.sort_letter, count(*) FROM contacts c {where_sql}
         GROUP BY c.sort_letter ORDER BY c.sort_letter"
    );
    let buckets = conn
        .prepare_cached(&sql)?
        .query_map(params_from_iter(&args), |r| Ok((r.get::<_, String>(0)?, r.get::<_, i64>(1)?)))?
        .collect::<Result<Vec<_>, _>>()?;

    let mut letters: Vec<LetterIndex> = Vec::with_capacity(buckets.len());
    let mut offset = 0;
    for (letter, count) in buckets {
        if letter == "~" {
            // Names after Z also file under '#'; keep the first '#' offset.
            if let Some(hash) = letters.iter_mut().find(|l| l.letter == "#") {
                hash.count += count;
            } else {
                letters.push(LetterIndex { letter: "#".into(), offset, count });
            }
        } else {
            letters.push(LetterIndex { letter, offset, count });
        }
        offset += count;
    }
    Ok(letters)
}

pub fn list_contacts(conn: &Connection, q: &ListQuery) -> Result<ContactPage, AppError> {
    let limit = q.limit.unwrap_or(50).clamp(1, MAX_PAGE);
    let offset = q.offset.unwrap_or(0).max(0);

    let (where_sql, mut args) = contact_filters(q);

    let total: i64 = conn.query_row(
        &format!("SELECT count(*) FROM contacts c {where_sql}"),
        params_from_iter(&args),
        |r| r.get(0),
    )?;

    let sql = format!(
        "SELECT c.id, c.first_name, c.last_name, c.company, c.job_title, c.favorite,
                (SELECT value FROM emails WHERE contact_id = c.id ORDER BY position LIMIT 1),
                (SELECT value FROM phones WHERE contact_id = c.id ORDER BY position LIMIT 1),
                (SELECT group_concat(tag_id) FROM contact_tags WHERE contact_id = c.id)
         FROM contacts c
         {where_sql}
         ORDER BY {CONTACT_ORDER}
         LIMIT ? OFFSET ?"
    );
    args.push(limit.into());
    args.push(offset.into());

    let mut stmt = conn.prepare_cached(&sql)?;
    let items = stmt
        .query_map(params_from_iter(&args), |r| {
            let tags: Option<String> = r.get(8)?;
            Ok(ContactSummary {
                id: r.get(0)?,
                first_name: r.get(1)?,
                last_name: r.get(2)?,
                company: r.get(3)?,
                job_title: r.get(4)?,
                favorite: r.get(5)?,
                email: r.get(6)?,
                phone: r.get(7)?,
                tag_ids: tags
                    .map(|t| t.split(',').filter_map(|s| s.parse().ok()).collect())
                    .unwrap_or_default(),
            })
        })?
        .collect::<Result<Vec<_>, _>>()?;

    Ok(ContactPage { items, total, limit, offset })
}

pub fn get_contact(conn: &Connection, id: i64) -> Result<Contact, AppError> {
    let mut contact = conn.query_row(
        "SELECT id, first_name, last_name, company, job_title, birthday, notes, favorite,
                created_at, updated_at
         FROM contacts WHERE id = ?",
        [id],
        |r| {
            Ok(Contact {
                id: r.get(0)?,
                first_name: r.get(1)?,
                last_name: r.get(2)?,
                company: r.get(3)?,
                job_title: r.get(4)?,
                birthday: r.get(5)?,
                notes: r.get(6)?,
                favorite: r.get(7)?,
                created_at: r.get(8)?,
                updated_at: r.get(9)?,
                emails: vec![],
                phones: vec![],
                addresses: vec![],
                tags: vec![],
            })
        },
    )?;

    contact.emails = labeled_values(conn, "emails", id)?;
    contact.phones = labeled_values(conn, "phones", id)?;
    contact.addresses = conn
        .prepare_cached(
            "SELECT label, street, city, region, postal_code, country
             FROM addresses WHERE contact_id = ? ORDER BY position",
        )?
        .query_map([id], |r| {
            Ok(Address {
                label: r.get(0)?,
                street: r.get(1)?,
                city: r.get(2)?,
                region: r.get(3)?,
                postal_code: r.get(4)?,
                country: r.get(5)?,
            })
        })?
        .collect::<Result<_, _>>()?;
    contact.tags = conn
        .prepare_cached(
            "SELECT t.id, t.name, t.color FROM tags t
             JOIN contact_tags ct ON ct.tag_id = t.id
             WHERE ct.contact_id = ? ORDER BY t.name COLLATE NOCASE",
        )?
        .query_map([id], tag_from_row)?
        .collect::<Result<_, _>>()?;

    Ok(contact)
}

fn labeled_values(conn: &Connection, table: &str, id: i64) -> Result<Vec<LabeledValue>, AppError> {
    let sql = format!("SELECT label, value FROM {table} WHERE contact_id = ? ORDER BY position");
    let rows = conn
        .prepare_cached(&sql)?
        .query_map([id], |r| Ok(LabeledValue { label: r.get(0)?, value: r.get(1)? }))?
        .collect::<Result<_, _>>()?;
    Ok(rows)
}

pub fn insert_contact(tx: &Transaction, input: &ContactInput) -> Result<i64, AppError> {
    tx.prepare_cached(
        "INSERT INTO contacts (first_name, last_name, company, job_title, birthday, notes, favorite)
         VALUES (?, ?, ?, ?, ?, ?, ?)",
    )?
    .execute(params![
        input.first_name,
        input.last_name,
        input.company,
        input.job_title,
        input.birthday,
        input.notes,
        input.favorite,
    ])?;
    let id = tx.last_insert_rowid();
    write_children(tx, id, input)?;
    refresh_fts(tx, id)?;
    Ok(id)
}

pub fn update_contact(tx: &Transaction, id: i64, input: &ContactInput) -> Result<(), AppError> {
    let changed = tx
        .prepare_cached(
            "UPDATE contacts SET first_name = ?, last_name = ?, company = ?, job_title = ?,
                birthday = ?, notes = ?, favorite = ?,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
             WHERE id = ?",
        )?
        .execute(params![
            input.first_name,
            input.last_name,
            input.company,
            input.job_title,
            input.birthday,
            input.notes,
            input.favorite,
            id,
        ])?;
    if changed == 0 {
        return Err(AppError::NotFound);
    }
    for table in ["emails", "phones", "addresses", "contact_tags"] {
        tx.execute(&format!("DELETE FROM {table} WHERE contact_id = ?"), [id])?;
    }
    write_children(tx, id, input)?;
    refresh_fts(tx, id)?;
    Ok(())
}

pub fn set_favorite(conn: &Connection, id: i64, favorite: bool) -> Result<(), AppError> {
    let changed = conn.execute(
        "UPDATE contacts SET favorite = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
         WHERE id = ?",
        params![favorite, id],
    )?;
    if changed == 0 { Err(AppError::NotFound) } else { Ok(()) }
}

pub fn delete_contact(tx: &Transaction, id: i64) -> Result<(), AppError> {
    // Children go via ON DELETE CASCADE; the FTS table has no foreign key.
    tx.execute("DELETE FROM contacts_fts WHERE rowid = ?", [id])?;
    let changed = tx.execute("DELETE FROM contacts WHERE id = ?", [id])?;
    if changed == 0 { Err(AppError::NotFound) } else { Ok(()) }
}

fn write_children(tx: &Transaction, id: i64, input: &ContactInput) -> Result<(), AppError> {
    let mut email = tx.prepare_cached(
        "INSERT INTO emails (contact_id, label, value, position) VALUES (?, ?, ?, ?)",
    )?;
    for (pos, e) in input.emails.iter().enumerate() {
        email.execute(params![id, e.label, e.value, pos as i64])?;
    }

    let mut phone = tx.prepare_cached(
        "INSERT INTO phones (contact_id, label, value, position) VALUES (?, ?, ?, ?)",
    )?;
    for (pos, p) in input.phones.iter().enumerate() {
        phone.execute(params![id, p.label, p.value, pos as i64])?;
    }

    let mut addr = tx.prepare_cached(
        "INSERT INTO addresses (contact_id, label, street, city, region, postal_code, country, position)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
    )?;
    for (pos, a) in input.addresses.iter().enumerate() {
        addr.execute(params![
            id, a.label, a.street, a.city, a.region, a.postal_code, a.country, pos as i64
        ])?;
    }

    let mut tag = tx.prepare_cached("INSERT INTO contact_tags (contact_id, tag_id) VALUES (?, ?)")?;
    for tag_id in &input.tag_ids {
        tag.execute(params![id, tag_id]).map_err(|e| match AppError::from(e) {
            AppError::Conflict(_) => AppError::Validation(format!("tag {tag_id} does not exist")),
            other => other,
        })?;
    }
    Ok(())
}

/// Rebuild one contact's search document from its current rows.
fn refresh_fts(tx: &Transaction, id: i64) -> Result<(), AppError> {
    tx.prepare_cached("DELETE FROM contacts_fts WHERE rowid = ?")?.execute([id])?;
    tx.prepare_cached(
        "INSERT INTO contacts_fts (rowid, name, company, emails, phones, places, notes)
         SELECT c.id,
                c.first_name || ' ' || c.last_name,
                c.company || ' ' || c.job_title,
                coalesce((SELECT group_concat(value, ' ') FROM emails WHERE contact_id = c.id), ''),
                coalesce((SELECT group_concat(value, ' ') FROM phones WHERE contact_id = c.id), ''),
                coalesce((SELECT group_concat(street || ' ' || city || ' ' || region || ' ' || country, ' ')
                          FROM addresses WHERE contact_id = c.id), ''),
                c.notes
         FROM contacts c WHERE c.id = ?",
    )?
    .execute([id])?;
    Ok(())
}

/// Turn free text into a safe FTS5 query: every word becomes a quoted prefix
/// term, and all terms must match. `jo smi` -> `"jo"* "smi"*`.
pub fn fts_query(input: &str) -> Option<String> {
    let terms: Vec<String> = input
        .split(|c: char| !is_word_char(c))
        .filter(|t| !t.is_empty())
        .map(|t| format!("\"{}\"*", t.replace('"', "\"\"")))
        .collect();
    if terms.is_empty() { None } else { Some(terms.join(" ")) }
}

/// A search word is made of Unicode letters, marks and numbers (general
/// categories L*, M*, N*), plus `@ . '`. See docs/requirements/02-database.md §6.2.
fn is_word_char(c: char) -> bool {
    use unicode_general_category::{GeneralCategory as G, get_general_category};
    matches!(c, '@' | '.' | '\'')
        || matches!(
            get_general_category(c),
            G::UppercaseLetter | G::LowercaseLetter | G::TitlecaseLetter | G::ModifierLetter | G::OtherLetter
                | G::NonspacingMark | G::SpacingMark | G::EnclosingMark
                | G::DecimalNumber | G::LetterNumber | G::OtherNumber
        )
}

// ---------------------------------------------------------------- tags

fn tag_from_row(r: &Row) -> rusqlite::Result<Tag> {
    Ok(Tag { id: r.get(0)?, name: r.get(1)?, color: r.get(2)? })
}

pub fn list_tags(conn: &Connection) -> Result<Vec<TagWithCount>, AppError> {
    let rows = conn
        .prepare_cached(
            "SELECT t.id, t.name, t.color, count(ct.contact_id)
             FROM tags t LEFT JOIN contact_tags ct ON ct.tag_id = t.id
             GROUP BY t.id ORDER BY t.name COLLATE NOCASE",
        )?
        .query_map([], |r| Ok(TagWithCount { tag: tag_from_row(r)?, contact_count: r.get(3)? }))?
        .collect::<Result<_, _>>()?;
    Ok(rows)
}

pub fn get_tag(conn: &Connection, id: i64) -> Result<Tag, AppError> {
    Ok(conn.query_row("SELECT id, name, color FROM tags WHERE id = ?", [id], tag_from_row)?)
}

pub fn insert_tag(conn: &Connection, input: &TagInput) -> Result<Tag, AppError> {
    conn.execute(
        "INSERT INTO tags (name, color) VALUES (?, ?)",
        params![input.name, input.color.as_deref().unwrap_or("slate")],
    )
    .map_err(|e| tag_conflict(e, &input.name))?;
    get_tag(conn, conn.last_insert_rowid())
}

pub fn update_tag(conn: &Connection, id: i64, input: &TagInput) -> Result<Tag, AppError> {
    let changed = conn
        .execute(
            "UPDATE tags SET name = ?, color = coalesce(?, color) WHERE id = ?",
            params![input.name, input.color, id],
        )
        .map_err(|e| tag_conflict(e, &input.name))?;
    if changed == 0 {
        return Err(AppError::NotFound);
    }
    get_tag(conn, id)
}

pub fn delete_tag(conn: &Connection, id: i64) -> Result<(), AppError> {
    let changed = conn.execute("DELETE FROM tags WHERE id = ?", [id])?;
    if changed == 0 { Err(AppError::NotFound) } else { Ok(()) }
}

fn tag_conflict(e: rusqlite::Error, name: &str) -> AppError {
    match AppError::from(e) {
        AppError::Conflict(_) => AppError::Conflict(format!("a tag named '{name}' already exists")),
        other => other,
    }
}

// ---------------------------------------------------------------- stats

pub fn stats(conn: &Connection) -> Result<serde_json::Value, AppError> {
    let (contacts, favorites): (i64, i64) = conn.query_row(
        "SELECT count(*), coalesce(sum(favorite), 0) FROM contacts",
        [],
        |r| Ok((r.get(0)?, r.get(1)?)),
    )?;
    Ok(serde_json::json!({ "contacts": contacts, "favorites": favorites }))
}
