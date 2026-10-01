#include "repo.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "text.h"

#define MAX_PAGE 200
#define CONTACT_ORDER "c.sort_key COLLATE NOCASE, c.first_name COLLATE NOCASE, c.id"
#define NOW "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"

/* Statements are reset right after use: one left mid-result keeps its read
 * transaction open, pinning an old snapshot and blocking WAL checkpoints. */
#define DONE(s) sqlite3_reset(s)

static const char *col_text(sqlite3_stmt *s, int i) {
    const unsigned char *t = sqlite3_column_text(s, i);
    return t ? (const char *)t : NULL;
}

static void json_col(buf_t *b, sqlite3_stmt *s, int i) {
    json_str_or_null(b, col_text(s, i));
}

/* Run a statement that returns no rows; returns the SQLite result code. */
static int exec_stmt(sqlite3_stmt *s) {
    int rc = sqlite3_step(s);
    DONE(s);
    return rc;
}

/* ---------------------------------------------------------------- filters */

typedef struct {
    char where[512];
    char *fts;          /* bind 1 when set */
    int has_tag;
    int64_t tag;
} filters_t;

static void build_filters(const list_query_t *q, filters_t *f) {
    memset(f, 0, sizeof *f);
    char *parts[3];
    int n = 0;
    f->fts = fts_query(q->q);
    if (f->fts) parts[n++] = "c.id IN (SELECT rowid FROM contacts_fts WHERE contacts_fts MATCH ?)";
    if (q->has_tag) {
        f->has_tag = 1;
        f->tag = q->tag;
        parts[n++] = "c.id IN (SELECT contact_id FROM contact_tags WHERE tag_id = ?)";
    }
    if (q->favorite) parts[n++] = "c.favorite = 1";
    for (int i = 0; i < n; i++) {
        strcat(f->where, i ? " AND " : "WHERE ");
        strcat(f->where, parts[i]);
    }
}

/* Bind the filter values starting at parameter 1; returns the next index. */
static int bind_filters(sqlite3_stmt *s, const filters_t *f) {
    int i = 1;
    if (f->fts) sqlite3_bind_text(s, i++, f->fts, -1, SQLITE_TRANSIENT);
    if (f->has_tag) sqlite3_bind_int64(s, i++, f->tag);
    return i;
}

/* ---------------------------------------------------------------- contacts */

int repo_list_contacts(conn_t *c, const list_query_t *q, buf_t *out, app_err *e) {
    int64_t limit = q->has_limit ? q->limit : 50, offset = q->has_offset ? q->offset : 0;
    if (limit < 1) limit = 1;
    if (limit > MAX_PAGE) limit = MAX_PAGE;
    if (offset < 0) offset = 0;
    filters_t f;
    build_filters(q, &f);
    char sql[2048];
    int ok = 0;

    snprintf(sql, sizeof sql, "SELECT count(*) FROM contacts c %s", f.where);
    sqlite3_stmt *s = conn_stmt(c, sql, e);
    if (!s) goto out;
    bind_filters(s, &f);
    if (sqlite3_step(s) != SQLITE_ROW) { db_fail(e, conn_db(c), "count"); DONE(s); goto out; }
    int64_t total = sqlite3_column_int64(s, 0);
    DONE(s);

    snprintf(sql, sizeof sql,
             "SELECT c.id, c.first_name, c.last_name, c.company, c.job_title, c.favorite,"
             " (SELECT value FROM emails WHERE contact_id = c.id ORDER BY position LIMIT 1),"
             " (SELECT value FROM phones WHERE contact_id = c.id ORDER BY position LIMIT 1),"
             " (SELECT group_concat(tag_id) FROM contact_tags WHERE contact_id = c.id)"
             " FROM contacts c %s ORDER BY " CONTACT_ORDER " LIMIT ? OFFSET ?",
             f.where);
    s = conn_stmt(c, sql, e);
    if (!s) goto out;
    int i = bind_filters(s, &f);
    sqlite3_bind_int64(s, i, limit);
    sqlite3_bind_int64(s, i + 1, offset);

    buf_puts(out, "{\"items\":[");
    int rc, first = 1;
    while ((rc = sqlite3_step(s)) == SQLITE_ROW) {
        if (!first) buf_putc(out, ',');
        first = 0;
        buf_puts(out, "{\"id\":");
        json_int(out, sqlite3_column_int64(s, 0));
        buf_puts(out, ",\"first_name\":"); json_col(out, s, 1);
        buf_puts(out, ",\"last_name\":"); json_col(out, s, 2);
        buf_puts(out, ",\"company\":"); json_col(out, s, 3);
        buf_puts(out, ",\"job_title\":"); json_col(out, s, 4);
        buf_puts(out, ",\"favorite\":"); json_bool(out, sqlite3_column_int(s, 5));
        buf_puts(out, ",\"email\":"); json_col(out, s, 6);
        buf_puts(out, ",\"phone\":"); json_col(out, s, 7);
        buf_puts(out, ",\"tag_ids\":[");
        const char *tags = col_text(s, 8); /* "1,4" from group_concat, already ascending */
        if (tags) buf_puts(out, tags);
        buf_puts(out, "]}");
    }
    DONE(s);
    if (rc != SQLITE_DONE) { db_fail(e, conn_db(c), "list"); goto out; }
    buf_printf(out, "],\"total\":%lld,\"limit\":%lld,\"offset\":%lld}", (long long)total, (long long)limit,
               (long long)offset);
    ok = 1;
out:
    free(f.fts);
    return ok;
}

/* Buckets come ordered '#' < 'A'..'Z' < '~'; offsets are running totals, and
 * '~' (names after Z) folds into '#' (API-L3). */
int repo_list_letters(conn_t *c, const list_query_t *q, buf_t *out, app_err *e) {
    filters_t f;
    build_filters(q, &f);
    char sql[1024];
    snprintf(sql, sizeof sql,
             "SELECT c.sort_letter, count(*) FROM contacts c %s GROUP BY c.sort_letter ORDER BY c.sort_letter",
             f.where);
    sqlite3_stmt *s = conn_stmt(c, sql, e);
    if (!s) { free(f.fts); return 0; }
    bind_filters(s, &f);

    struct { char letter; int64_t offset, count; } letters[32];
    int n = 0, rc;
    int64_t offset = 0;
    while ((rc = sqlite3_step(s)) == SQLITE_ROW && n < 32) {
        const char *l = col_text(s, 0);
        char letter = l ? l[0] : '#';
        int64_t count = sqlite3_column_int64(s, 1);
        if (letter == '~') {
            int merged = 0;
            for (int i = 0; i < n; i++)
                if (letters[i].letter == '#') { letters[i].count += count; merged = 1; }
            if (!merged) { letters[n].letter = '#'; letters[n].offset = offset; letters[n].count = count; n++; }
        } else {
            letters[n].letter = letter; letters[n].offset = offset; letters[n].count = count; n++;
        }
        offset += count;
    }
    DONE(s);
    free(f.fts);
    if (rc != SQLITE_DONE && rc != SQLITE_ROW) return db_fail(e, conn_db(c), "letters");
    buf_putc(out, '[');
    for (int i = 0; i < n; i++) {
        buf_printf(out, "%s{\"letter\":\"%c\",\"offset\":%lld,\"count\":%lld}", i ? "," : "", letters[i].letter,
                   (long long)letters[i].offset, (long long)letters[i].count);
    }
    buf_putc(out, ']');
    return 1;
}

static int labeled_rows(conn_t *c, const char *sql, int64_t id, buf_t *out, app_err *e) {
    sqlite3_stmt *s = conn_stmt(c, sql, e);
    if (!s) return 0;
    sqlite3_bind_int64(s, 1, id);
    buf_putc(out, '[');
    int rc, first = 1;
    while ((rc = sqlite3_step(s)) == SQLITE_ROW) {
        buf_puts(out, first ? "{\"label\":" : ",{\"label\":");
        first = 0;
        json_col(out, s, 0);
        buf_puts(out, ",\"value\":");
        json_col(out, s, 1);
        buf_putc(out, '}');
    }
    DONE(s);
    buf_putc(out, ']');
    return rc == SQLITE_DONE ? 1 : db_fail(e, conn_db(c), "labeled rows");
}

int repo_get_contact(conn_t *c, int64_t id, buf_t *out, app_err *e) {
    sqlite3_stmt *s = conn_stmt(c,
        "SELECT id, first_name, last_name, company, job_title, birthday, notes, favorite, created_at, updated_at"
        " FROM contacts WHERE id = ?", e);
    if (!s) return 0;
    sqlite3_bind_int64(s, 1, id);
    int rc = sqlite3_step(s);
    if (rc == SQLITE_DONE) { DONE(s); set_err(e, 404, "not found"); return 0; }
    if (rc != SQLITE_ROW) { DONE(s); return db_fail(e, conn_db(c), "get contact"); }
    buf_puts(out, "{\"id\":"); json_int(out, sqlite3_column_int64(s, 0));
    buf_puts(out, ",\"first_name\":"); json_col(out, s, 1);
    buf_puts(out, ",\"last_name\":"); json_col(out, s, 2);
    buf_puts(out, ",\"company\":"); json_col(out, s, 3);
    buf_puts(out, ",\"job_title\":"); json_col(out, s, 4);
    buf_puts(out, ",\"birthday\":"); json_col(out, s, 5);
    buf_puts(out, ",\"notes\":"); json_col(out, s, 6);
    buf_puts(out, ",\"favorite\":"); json_bool(out, sqlite3_column_int(s, 7));
    /* Timestamps come last in the JSON; keep them before resetting the statement. */
    char created[40], updated[40];
    snprintf(created, sizeof created, "%s", col_text(s, 8) ? col_text(s, 8) : "");
    snprintf(updated, sizeof updated, "%s", col_text(s, 9) ? col_text(s, 9) : "");
    DONE(s);

    buf_puts(out, ",\"emails\":");
    if (!labeled_rows(c, "SELECT label, value FROM emails WHERE contact_id = ? ORDER BY position", id, out, e)) return 0;
    buf_puts(out, ",\"phones\":");
    if (!labeled_rows(c, "SELECT label, value FROM phones WHERE contact_id = ? ORDER BY position", id, out, e)) return 0;

    s = conn_stmt(c, "SELECT label, street, city, region, postal_code, country FROM addresses"
                     " WHERE contact_id = ? ORDER BY position", e);
    if (!s) return 0;
    sqlite3_bind_int64(s, 1, id);
    buf_puts(out, ",\"addresses\":[");
    static const char *fields[] = {"label", "street", "city", "region", "postal_code", "country"};
    int first = 1;
    while ((rc = sqlite3_step(s)) == SQLITE_ROW) {
        buf_puts(out, first ? "{" : ",{");
        first = 0;
        for (int i = 0; i < 6; i++) {
            if (i) buf_putc(out, ',');
            json_key(out, fields[i]);
            json_col(out, s, i);
        }
        buf_putc(out, '}');
    }
    DONE(s);
    if (rc != SQLITE_DONE) return db_fail(e, conn_db(c), "addresses");

    s = conn_stmt(c, "SELECT t.id, t.name, t.color FROM tags t JOIN contact_tags ct ON ct.tag_id = t.id"
                     " WHERE ct.contact_id = ? ORDER BY t.name COLLATE NOCASE", e);
    if (!s) return 0;
    sqlite3_bind_int64(s, 1, id);
    buf_puts(out, "],\"tags\":[");
    first = 1;
    while ((rc = sqlite3_step(s)) == SQLITE_ROW) {
        buf_puts(out, first ? "{\"id\":" : ",{\"id\":");
        first = 0;
        json_int(out, sqlite3_column_int64(s, 0));
        buf_puts(out, ",\"name\":"); json_col(out, s, 1);
        buf_puts(out, ",\"color\":"); json_col(out, s, 2);
        buf_putc(out, '}');
    }
    DONE(s);
    if (rc != SQLITE_DONE) return db_fail(e, conn_db(c), "tags");
    buf_puts(out, "],\"created_at\":"); json_str(out, created);
    buf_puts(out, ",\"updated_at\":"); json_str(out, updated);
    buf_putc(out, '}');
    return 1;
}

static int write_children(conn_t *w, int64_t id, const contact_t *in, app_err *e) {
    sqlite3_stmt *s = conn_stmt(w, "INSERT INTO emails (contact_id, label, value, position) VALUES (?, ?, ?, ?)", e);
    if (!s) return 0;
    for (size_t i = 0; i < in->n_emails; i++) {
        sqlite3_reset(s);
        sqlite3_bind_int64(s, 1, id);
        sqlite3_bind_text(s, 2, in->emails[i].label, -1, SQLITE_STATIC);
        sqlite3_bind_text(s, 3, in->emails[i].value, -1, SQLITE_STATIC);
        sqlite3_bind_int64(s, 4, (int64_t)i);
        if (exec_stmt(s) != SQLITE_DONE) return db_fail(e, conn_db(w), "insert email");
    }
    s = conn_stmt(w, "INSERT INTO phones (contact_id, label, value, position) VALUES (?, ?, ?, ?)", e);
    if (!s) return 0;
    for (size_t i = 0; i < in->n_phones; i++) {
        sqlite3_reset(s);
        sqlite3_bind_int64(s, 1, id);
        sqlite3_bind_text(s, 2, in->phones[i].label, -1, SQLITE_STATIC);
        sqlite3_bind_text(s, 3, in->phones[i].value, -1, SQLITE_STATIC);
        sqlite3_bind_int64(s, 4, (int64_t)i);
        if (exec_stmt(s) != SQLITE_DONE) return db_fail(e, conn_db(w), "insert phone");
    }
    s = conn_stmt(w, "INSERT INTO addresses (contact_id, label, street, city, region, postal_code, country, position)"
                     " VALUES (?, ?, ?, ?, ?, ?, ?, ?)", e);
    if (!s) return 0;
    for (size_t i = 0; i < in->n_addresses; i++) {
        const address_t *a = &in->addresses[i];
        sqlite3_reset(s);
        sqlite3_bind_int64(s, 1, id);
        sqlite3_bind_text(s, 2, a->label, -1, SQLITE_STATIC);
        sqlite3_bind_text(s, 3, a->street, -1, SQLITE_STATIC);
        sqlite3_bind_text(s, 4, a->city, -1, SQLITE_STATIC);
        sqlite3_bind_text(s, 5, a->region, -1, SQLITE_STATIC);
        sqlite3_bind_text(s, 6, a->postal_code, -1, SQLITE_STATIC);
        sqlite3_bind_text(s, 7, a->country, -1, SQLITE_STATIC);
        sqlite3_bind_int64(s, 8, (int64_t)i);
        if (exec_stmt(s) != SQLITE_DONE) return db_fail(e, conn_db(w), "insert address");
    }
    s = conn_stmt(w, "INSERT INTO contact_tags (contact_id, tag_id) VALUES (?, ?)", e);
    if (!s) return 0;
    for (size_t i = 0; i < in->n_tag_ids; i++) {
        sqlite3_reset(s);
        sqlite3_bind_int64(s, 1, id);
        sqlite3_bind_int64(s, 2, in->tag_ids[i]);
        int rc = exec_stmt(s);
        if ((rc & 0xFF) == SQLITE_CONSTRAINT) {
            set_err(e, 422, "tag %lld does not exist", (long long)in->tag_ids[i]);
            return 0;
        }
        if (rc != SQLITE_DONE) return db_fail(e, conn_db(w), "insert tag link");
    }
    return 1;
}

/* Rebuild one contact's search document from its current rows (§6.1). */
static int refresh_fts(conn_t *w, int64_t id, app_err *e) {
    sqlite3_stmt *s = conn_stmt(w, "DELETE FROM contacts_fts WHERE rowid = ?", e);
    if (!s) return 0;
    sqlite3_bind_int64(s, 1, id);
    if (exec_stmt(s) != SQLITE_DONE) return db_fail(e, conn_db(w), "fts delete");
    s = conn_stmt(w,
        "INSERT INTO contacts_fts (rowid, name, company, emails, phones, places, notes)"
        " SELECT c.id, c.first_name || ' ' || c.last_name, c.company || ' ' || c.job_title,"
        " coalesce((SELECT group_concat(value, ' ') FROM emails WHERE contact_id = c.id), ''),"
        " coalesce((SELECT group_concat(value, ' ') FROM phones WHERE contact_id = c.id), ''),"
        " coalesce((SELECT group_concat(street || ' ' || city || ' ' || region || ' ' || country, ' ')"
        "           FROM addresses WHERE contact_id = c.id), ''),"
        " c.notes FROM contacts c WHERE c.id = ?", e);
    if (!s) return 0;
    sqlite3_bind_int64(s, 1, id);
    if (exec_stmt(s) != SQLITE_DONE) return db_fail(e, conn_db(w), "fts insert");
    return 1;
}

static void bind_contact(sqlite3_stmt *s, const contact_t *in) {
    sqlite3_bind_text(s, 1, in->first_name, -1, SQLITE_STATIC);
    sqlite3_bind_text(s, 2, in->last_name, -1, SQLITE_STATIC);
    sqlite3_bind_text(s, 3, in->company, -1, SQLITE_STATIC);
    sqlite3_bind_text(s, 4, in->job_title, -1, SQLITE_STATIC);
    if (in->birthday) sqlite3_bind_text(s, 5, in->birthday, -1, SQLITE_STATIC);
    else sqlite3_bind_null(s, 5);
    sqlite3_bind_text(s, 6, in->notes, -1, SQLITE_STATIC);
    sqlite3_bind_int(s, 7, in->favorite ? 1 : 0);
}

int repo_insert_contact(conn_t *w, const contact_t *in, int64_t *id, app_err *e) {
    sqlite3_stmt *s = conn_stmt(w, "INSERT INTO contacts (first_name, last_name, company, job_title, birthday, notes,"
                                   " favorite) VALUES (?, ?, ?, ?, ?, ?, ?)", e);
    if (!s) return 0;
    bind_contact(s, in);
    if (exec_stmt(s) != SQLITE_DONE) return db_fail(e, conn_db(w), "insert contact");
    *id = sqlite3_last_insert_rowid(conn_db(w));
    return write_children(w, *id, in, e) && refresh_fts(w, *id, e);
}

int repo_update_contact(conn_t *w, int64_t id, const contact_t *in, app_err *e) {
    sqlite3_stmt *s = conn_stmt(w, "UPDATE contacts SET first_name = ?, last_name = ?, company = ?, job_title = ?,"
                                   " birthday = ?, notes = ?, favorite = ?, updated_at = " NOW " WHERE id = ?", e);
    if (!s) return 0;
    bind_contact(s, in);
    sqlite3_bind_int64(s, 8, id);
    if (exec_stmt(s) != SQLITE_DONE) return db_fail(e, conn_db(w), "update contact");
    if (sqlite3_changes(conn_db(w)) == 0) { set_err(e, 404, "not found"); return 0; }
    static const char *deletes[] = {
        "DELETE FROM emails WHERE contact_id = ?", "DELETE FROM phones WHERE contact_id = ?",
        "DELETE FROM addresses WHERE contact_id = ?", "DELETE FROM contact_tags WHERE contact_id = ?"};
    for (int i = 0; i < 4; i++) {
        s = conn_stmt(w, deletes[i], e);
        if (!s) return 0;
        sqlite3_bind_int64(s, 1, id);
        if (exec_stmt(s) != SQLITE_DONE) return db_fail(e, conn_db(w), "delete children");
    }
    return write_children(w, id, in, e) && refresh_fts(w, id, e);
}

static int change_one(conn_t *w, const char *sql, int64_t id, int has_flag, int flag, app_err *e) {
    sqlite3_stmt *s = conn_stmt(w, sql, e);
    if (!s) return 0;
    int i = 1;
    if (has_flag) sqlite3_bind_int(s, i++, flag);
    sqlite3_bind_int64(s, i, id);
    if (exec_stmt(s) != SQLITE_DONE) return db_fail(e, conn_db(w), "write");
    if (sqlite3_changes(conn_db(w)) == 0) { set_err(e, 404, "not found"); return 0; }
    return 1;
}

int repo_set_favorite(conn_t *w, int64_t id, int favorite, app_err *e) {
    return change_one(w, "UPDATE contacts SET favorite = ?, updated_at = " NOW " WHERE id = ?", id, 1, favorite, e);
}

int repo_delete_contact(conn_t *w, int64_t id, app_err *e) {
    /* Children cascade; the FTS table has no foreign key. */
    sqlite3_stmt *s = conn_stmt(w, "DELETE FROM contacts_fts WHERE rowid = ?", e);
    if (!s) return 0;
    sqlite3_bind_int64(s, 1, id);
    if (exec_stmt(s) != SQLITE_DONE) return db_fail(e, conn_db(w), "fts delete");
    return change_one(w, "DELETE FROM contacts WHERE id = ?", id, 0, 0, e);
}

/* ---------------------------------------------------------------- tags */

int repo_list_tags(conn_t *c, buf_t *out, app_err *e) {
    sqlite3_stmt *s = conn_stmt(c, "SELECT t.id, t.name, t.color, count(ct.contact_id) FROM tags t"
                                   " LEFT JOIN contact_tags ct ON ct.tag_id = t.id"
                                   " GROUP BY t.id ORDER BY t.name COLLATE NOCASE", e);
    if (!s) return 0;
    buf_putc(out, '[');
    int rc, first = 1;
    while ((rc = sqlite3_step(s)) == SQLITE_ROW) {
        buf_puts(out, first ? "{\"id\":" : ",{\"id\":");
        first = 0;
        json_int(out, sqlite3_column_int64(s, 0));
        buf_puts(out, ",\"name\":"); json_col(out, s, 1);
        buf_puts(out, ",\"color\":"); json_col(out, s, 2);
        buf_puts(out, ",\"contact_count\":"); json_int(out, sqlite3_column_int64(s, 3));
        buf_putc(out, '}');
    }
    DONE(s);
    buf_putc(out, ']');
    return rc == SQLITE_DONE ? 1 : db_fail(e, conn_db(c), "list tags");
}

static int get_tag(conn_t *c, int64_t id, buf_t *out, app_err *e) {
    sqlite3_stmt *s = conn_stmt(c, "SELECT id, name, color FROM tags WHERE id = ?", e);
    if (!s) return 0;
    sqlite3_bind_int64(s, 1, id);
    int rc = sqlite3_step(s);
    if (rc == SQLITE_ROW) {
        buf_puts(out, "{\"id\":"); json_int(out, sqlite3_column_int64(s, 0));
        buf_puts(out, ",\"name\":"); json_col(out, s, 1);
        buf_puts(out, ",\"color\":"); json_col(out, s, 2);
        buf_putc(out, '}');
    }
    DONE(s);
    if (rc == SQLITE_DONE) { set_err(e, 404, "not found"); return 0; }
    return rc == SQLITE_ROW ? 1 : db_fail(e, conn_db(c), "get tag");
}

int repo_insert_tag(conn_t *w, const tag_t *t, buf_t *out, app_err *e) {
    sqlite3_stmt *s = conn_stmt(w, "INSERT INTO tags (name, color) VALUES (?, ?)", e);
    if (!s) return 0;
    sqlite3_bind_text(s, 1, t->name, -1, SQLITE_STATIC);
    sqlite3_bind_text(s, 2, t->color ? t->color : "slate", -1, SQLITE_STATIC);
    int rc = exec_stmt(s);
    if ((rc & 0xFF) == SQLITE_CONSTRAINT) { set_err(e, 409, "a tag named '%s' already exists", t->name); return 0; }
    if (rc != SQLITE_DONE) return db_fail(e, conn_db(w), "insert tag");
    return get_tag(w, sqlite3_last_insert_rowid(conn_db(w)), out, e);
}

int repo_update_tag(conn_t *w, int64_t id, const tag_t *t, buf_t *out, app_err *e) {
    sqlite3_stmt *s = conn_stmt(w, "UPDATE tags SET name = ?, color = coalesce(?, color) WHERE id = ?", e);
    if (!s) return 0;
    sqlite3_bind_text(s, 1, t->name, -1, SQLITE_STATIC);
    if (t->color) sqlite3_bind_text(s, 2, t->color, -1, SQLITE_STATIC);
    else sqlite3_bind_null(s, 2);
    sqlite3_bind_int64(s, 3, id);
    int rc = exec_stmt(s);
    if ((rc & 0xFF) == SQLITE_CONSTRAINT) { set_err(e, 409, "a tag named '%s' already exists", t->name); return 0; }
    if (rc != SQLITE_DONE) return db_fail(e, conn_db(w), "update tag");
    if (sqlite3_changes(conn_db(w)) == 0) { set_err(e, 404, "not found"); return 0; }
    return get_tag(w, id, out, e);
}

int repo_delete_tag(conn_t *w, int64_t id, app_err *e) {
    return change_one(w, "DELETE FROM tags WHERE id = ?", id, 0, 0, e);
}

/* ---------------------------------------------------------------- stats */

int repo_stats(conn_t *c, buf_t *out, app_err *e) {
    sqlite3_stmt *s = conn_stmt(c, "SELECT count(*), coalesce(sum(favorite), 0) FROM contacts", e);
    if (!s) return 0;
    int rc = sqlite3_step(s);
    if (rc == SQLITE_ROW)
        buf_printf(out, "{\"contacts\":%lld,\"favorites\":%lld}", (long long)sqlite3_column_int64(s, 0),
                   (long long)sqlite3_column_int64(s, 1));
    DONE(s);
    return rc == SQLITE_ROW ? 1 : db_fail(e, conn_db(c), "stats");
}
