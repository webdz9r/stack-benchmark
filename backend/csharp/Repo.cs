using System.Text;
using Microsoft.Data.Sqlite;

namespace AddressBook;

/// <summary>Plain SQL; the same statements as the Rust backend's repo.rs.</summary>
public static class Repo
{
    const int MaxPage = 200;
    const string ContactOrder = "c.sort_key COLLATE NOCASE, c.first_name COLLATE NOCASE, c.id";
    const string Now = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')";

    // ---------------------------------------------------------------- contacts

    /// <summary>Free text -> safe FTS5 query: each word a quoted prefix term.
    /// `jo smi` -> `"jo"* "smi"*`. Null when there's nothing to search for.
    /// A word is made of Unicode letters, marks and numbers (by code point, not
    /// UTF-16 unit), plus `@ . '`.</summary>
    public static string? FtsQuery(string? text)
    {
        if (string.IsNullOrEmpty(text)) return null;
        var terms = new List<string>();
        var word = new StringBuilder();
        foreach (var rune in (text + " ").EnumerateRunes())
        {
            if (IsWordRune(rune)) word.Append(rune.ToString());
            else if (word.Length > 0)
            {
                terms.Add($"\"{word.ToString().Replace("\"", "\"\"")}\"*");
                word.Clear();
            }
        }
        return terms.Count > 0 ? string.Join(' ', terms) : null;
    }

    // UnicodeCategory orders letters (0-4), marks (5-7), then numbers (8-10).
    static bool IsWordRune(Rune r) =>
        r.Value is '@' or '.' or '\'' || Rune.GetUnicodeCategory(r) <= System.Globalization.UnicodeCategory.OtherNumber;

    static (string Where, List<object?> Args) Filters(ListQuery q)
    {
        var clauses = new List<string>();
        var args = new List<object?>();
        if (FtsQuery(q.Q) is { } fts)
        {
            clauses.Add("c.id IN (SELECT rowid FROM contacts_fts WHERE contacts_fts MATCH ?)");
            args.Add(fts);
        }
        if (q.Tag is { } tag)
        {
            clauses.Add("c.id IN (SELECT contact_id FROM contact_tags WHERE tag_id = ?)");
            args.Add(tag);
        }
        if (q.Favorite) clauses.Add("c.favorite = 1");
        return (clauses.Count > 0 ? "WHERE " + string.Join(" AND ", clauses) : "", args);
    }

    public static ContactPage ListContacts(Conn db, ListQuery q)
    {
        var limit = Math.Clamp(q.Limit ?? 50, 1, MaxPage);
        var offset = Math.Max(q.Offset ?? 0, 0);
        var (where, args) = Filters(q);

        var total = db.Scalar<long>($"SELECT count(*) FROM contacts c {where}", [.. args]);
        var items = db.Rows($"""
            SELECT c.id, c.first_name, c.last_name, c.company, c.job_title, c.favorite,
                   (SELECT value FROM emails WHERE contact_id = c.id ORDER BY position LIMIT 1),
                   (SELECT value FROM phones WHERE contact_id = c.id ORDER BY position LIMIT 1),
                   (SELECT group_concat(tag_id) FROM contact_tags WHERE contact_id = c.id)
            FROM contacts c
            {where}
            ORDER BY {ContactOrder}
            LIMIT ? OFFSET ?
            """, [.. args, limit, offset], r => new ContactSummary(
            r.GetInt64(0), r.GetString(1), r.GetString(2), r.GetString(3), r.GetString(4), r.GetInt64(5) == 1,
            Str(r, 6), Str(r, 7),
            r.IsDBNull(8) ? [] : r.GetString(8).Split(',').Select(long.Parse).ToList()));
        return new ContactPage(items, total, limit, offset);
    }

    /// <summary>Where each file letter starts in the sorted, filtered list.
    /// Buckets are contiguous and sort like the list ('#' &lt; 'A'..'Z' &lt; '~'),
    /// so offsets are running totals; '~' (after Z) is reported as '#'.</summary>
    public static List<LetterIndex> ListLetters(Conn db, ListQuery q)
    {
        var (where, args) = Filters(q);
        var buckets = db.Rows(
            $"SELECT c.sort_letter, count(*) FROM contacts c {where} GROUP BY c.sort_letter ORDER BY c.sort_letter",
            [.. args], r => (Letter: r.GetString(0), Count: r.GetInt64(1)));
        var letters = new List<LetterIndex>();
        long offset = 0;
        foreach (var (letter, count) in buckets)
        {
            if (letter == "~")
            {
                var i = letters.FindIndex(l => l.Letter == "#");
                if (i >= 0) letters[i] = letters[i] with { Count = letters[i].Count + count };
                else letters.Add(new LetterIndex("#", offset, count));
            }
            else letters.Add(new LetterIndex(letter, offset, count));
            offset += count;
        }
        return letters;
    }

    public static Contact GetContact(Conn db, long id)
    {
        var c = db.Row("""
            SELECT id, first_name, last_name, company, job_title, birthday, notes, favorite, created_at, updated_at
            FROM contacts WHERE id = ?
            """, [id], r => new Contact(
            r.GetInt64(0), r.GetString(1), r.GetString(2), r.GetString(3), r.GetString(4), Str(r, 5),
            r.GetString(6), r.GetInt64(7) == 1, [], [], [], [], r.GetString(8), r.GetString(9)))
            ?? throw AppError.NotFound();

        c.Emails.AddRange(db.Rows("SELECT label, value FROM emails WHERE contact_id = ? ORDER BY position", [id],
            r => new LabeledValue(r.GetString(0), r.GetString(1))));
        c.Phones.AddRange(db.Rows("SELECT label, value FROM phones WHERE contact_id = ? ORDER BY position", [id],
            r => new LabeledValue(r.GetString(0), r.GetString(1))));
        c.Addresses.AddRange(db.Rows("""
            SELECT label, street, city, region, postal_code, country
            FROM addresses WHERE contact_id = ? ORDER BY position
            """, [id], r => new Address(r.GetString(0), r.GetString(1), r.GetString(2), r.GetString(3), r.GetString(4), r.GetString(5))));
        c.Tags.AddRange(db.Rows("""
            SELECT t.id, t.name, t.color FROM tags t
            JOIN contact_tags ct ON ct.tag_id = t.id
            WHERE ct.contact_id = ? ORDER BY t.name COLLATE NOCASE
            """, [id], r => new Tag(r.GetInt64(0), r.GetString(1), r.GetString(2))));
        return c;
    }

    public static long InsertContact(Conn tx, ValidContact c)
    {
        tx.Run("""
            INSERT INTO contacts (first_name, last_name, company, job_title, birthday, notes, favorite)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, c.FirstName, c.LastName, c.Company, c.JobTitle, c.Birthday, c.Notes, c.Favorite);
        var id = tx.LastInsertId;
        WriteChildren(tx, id, c);
        RefreshFts(tx, id);
        return id;
    }

    public static void UpdateContact(Conn tx, long id, ValidContact c)
    {
        var changed = tx.Run($"""
            UPDATE contacts SET first_name = ?, last_name = ?, company = ?, job_title = ?,
                birthday = ?, notes = ?, favorite = ?, updated_at = {Now}
            WHERE id = ?
            """, c.FirstName, c.LastName, c.Company, c.JobTitle, c.Birthday, c.Notes, c.Favorite, id);
        if (changed == 0) throw AppError.NotFound();
        foreach (var table in new[] { "emails", "phones", "addresses", "contact_tags" })
            tx.Run($"DELETE FROM {table} WHERE contact_id = ?", id);
        WriteChildren(tx, id, c);
        RefreshFts(tx, id);
    }

    public static void SetFavorite(Conn tx, long id, bool favorite)
    {
        if (tx.Run($"UPDATE contacts SET favorite = ?, updated_at = {Now} WHERE id = ?", favorite, id) == 0)
            throw AppError.NotFound();
    }

    public static void DeleteContact(Conn tx, long id)
    {
        // Children go via ON DELETE CASCADE; the FTS table has no foreign key.
        tx.Run("DELETE FROM contacts_fts WHERE rowid = ?", id);
        if (tx.Run("DELETE FROM contacts WHERE id = ?", id) == 0) throw AppError.NotFound();
    }

    static void WriteChildren(Conn tx, long id, ValidContact c)
    {
        for (var i = 0; i < c.Emails.Count; i++)
            tx.Run("INSERT INTO emails (contact_id, label, value, position) VALUES (?, ?, ?, ?)", id, c.Emails[i].Label, c.Emails[i].Value, i);
        for (var i = 0; i < c.Phones.Count; i++)
            tx.Run("INSERT INTO phones (contact_id, label, value, position) VALUES (?, ?, ?, ?)", id, c.Phones[i].Label, c.Phones[i].Value, i);
        for (var i = 0; i < c.Addresses.Count; i++)
        {
            var a = c.Addresses[i];
            tx.Run("""
                INSERT INTO addresses (contact_id, label, street, city, region, postal_code, country, position)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, id, a.Label, a.Street, a.City, a.Region, a.PostalCode, a.Country, i);
        }
        foreach (var tagId in c.TagIds)
        {
            try
            {
                tx.Run("INSERT INTO contact_tags (contact_id, tag_id) VALUES (?, ?)", id, tagId);
            }
            catch (SqliteException e) when (e.SqliteErrorCode == 19)
            {
                throw AppError.Validation($"tag {tagId} does not exist");
            }
        }
    }

    /// <summary>Rebuild one contact's search document from its current rows.</summary>
    static void RefreshFts(Conn tx, long id)
    {
        tx.Run("DELETE FROM contacts_fts WHERE rowid = ?", id);
        tx.Run("""
            INSERT INTO contacts_fts (rowid, name, company, emails, phones, places, notes)
            SELECT c.id,
                   c.first_name || ' ' || c.last_name,
                   c.company || ' ' || c.job_title,
                   coalesce((SELECT group_concat(value, ' ') FROM emails WHERE contact_id = c.id), ''),
                   coalesce((SELECT group_concat(value, ' ') FROM phones WHERE contact_id = c.id), ''),
                   coalesce((SELECT group_concat(street || ' ' || city || ' ' || region || ' ' || country, ' ')
                             FROM addresses WHERE contact_id = c.id), ''),
                   c.notes
            FROM contacts c WHERE c.id = ?
            """, id);
    }

    // ---------------------------------------------------------------- tags

    public static List<TagWithCount> ListTags(Conn db) => db.Rows("""
        SELECT t.id, t.name, t.color, count(ct.contact_id)
        FROM tags t LEFT JOIN contact_tags ct ON ct.tag_id = t.id
        GROUP BY t.id ORDER BY t.name COLLATE NOCASE
        """, [], r => new TagWithCount(r.GetInt64(0), r.GetString(1), r.GetString(2), r.GetInt64(3)));

    static Tag GetTag(Conn db, long id) =>
        db.Row("SELECT id, name, color FROM tags WHERE id = ?", [id], r => new Tag(r.GetInt64(0), r.GetString(1), r.GetString(2)))
        ?? throw AppError.NotFound();

    public static Tag InsertTag(Conn tx, string name, string? color)
    {
        try
        {
            tx.Run("INSERT INTO tags (name, color) VALUES (?, ?)", name, color ?? "slate");
        }
        catch (SqliteException e) when (e.SqliteErrorCode == 19)
        {
            throw AppError.Conflict($"a tag named '{name}' already exists");
        }
        return GetTag(tx, tx.LastInsertId);
    }

    public static Tag UpdateTag(Conn tx, long id, string name, string? color)
    {
        int changed;
        try
        {
            changed = tx.Run("UPDATE tags SET name = ?, color = coalesce(?, color) WHERE id = ?", name, color, id);
        }
        catch (SqliteException e) when (e.SqliteErrorCode == 19)
        {
            throw AppError.Conflict($"a tag named '{name}' already exists");
        }
        if (changed == 0) throw AppError.NotFound();
        return GetTag(tx, id);
    }

    public static void DeleteTag(Conn tx, long id)
    {
        if (tx.Run("DELETE FROM tags WHERE id = ?", id) == 0) throw AppError.NotFound();
    }

    // ---------------------------------------------------------------- stats

    public static Stats GetStats(Conn db) =>
        db.Row("SELECT count(*), coalesce(sum(favorite), 0) FROM contacts", [], r => new Stats(r.GetInt64(0), r.GetInt64(1)))!;

    static string? Str(SqliteDataReader r, int i) => r.IsDBNull(i) ? null : r.GetString(i);
}
