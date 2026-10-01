package addressbook;

import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.List;

import addressbook.Db.Conn;
import addressbook.Models.Address;
import addressbook.Models.ApiException;
import addressbook.Models.Contact;
import addressbook.Models.ContactInput;
import addressbook.Models.ContactPage;
import addressbook.Models.ContactSummary;
import addressbook.Models.Filter;
import addressbook.Models.LabeledValue;
import addressbook.Models.LetterIndex;
import addressbook.Models.Stats;
import addressbook.Models.Tag;
import addressbook.Models.TagInput;
import addressbook.Models.TagWithCount;

import org.sqlite.SQLiteException;

/** The canonical SQL (02-database.md §6-7), run on a connection handed out by {@link Db}. */
public final class Store {
    private Store() {
    }

    private static final String CONTACT_ORDER =
        "c.sort_key COLLATE NOCASE, c.first_name COLLATE NOCASE, c.id";

    private static final String FTS_DELETE = "DELETE FROM contacts_fts WHERE rowid = ?";
    private static final String FTS_INSERT = """
        INSERT INTO contacts_fts (rowid, name, company, emails, phones, places, notes)
        SELECT c.id,
               c.first_name || ' ' || c.last_name,
               c.company || ' ' || c.job_title,
               coalesce((SELECT group_concat(value, ' ') FROM emails WHERE contact_id = c.id), ''),
               coalesce((SELECT group_concat(value, ' ') FROM phones WHERE contact_id = c.id), ''),
               coalesce((SELECT group_concat(street || ' ' || city || ' ' || region || ' ' || country, ' ')
                         FROM addresses WHERE contact_id = c.id), ''),
               c.notes
        FROM contacts c WHERE c.id = ?""";

    // ------------------------------------------------------------------ reads

    public static Stats stats(Conn c) throws SQLException {
        try (ResultSet rs = c.prepare("SELECT count(*), coalesce(sum(favorite), 0) FROM contacts").executeQuery()) {
            rs.next();
            return new Stats(rs.getLong(1), rs.getLong(2));
        }
    }

    /** §7.1: the WHERE clause for a filter, built from fixed fragments. */
    private static String where(Filter f) {
        List<String> parts = new ArrayList<>(3);
        if (f.fts() != null) {
            parts.add("c.id IN (SELECT rowid FROM contacts_fts WHERE contacts_fts MATCH ?)");
        }
        if (f.tag() != null) {
            parts.add("c.id IN (SELECT contact_id FROM contact_tags WHERE tag_id = ?)");
        }
        if (f.favorite()) {
            parts.add("c.favorite = 1");
        }
        return parts.isEmpty() ? "" : " WHERE " + String.join(" AND ", parts);
    }

    /** Binds the filter's parameters and returns the next parameter index. */
    private static int bindFilter(PreparedStatement ps, Filter f) throws SQLException {
        int i = 1;
        if (f.fts() != null) {
            ps.setString(i++, f.fts());
        }
        if (f.tag() != null) {
            ps.setLong(i++, f.tag());
        }
        return i;
    }

    public static ContactPage listPage(Conn c, Filter f, long limit, long offset) throws SQLException {
        String where = where(f);
        long total;
        PreparedStatement count = c.prepare("SELECT count(*) FROM contacts c" + where);
        bindFilter(count, f);
        try (ResultSet rs = count.executeQuery()) {
            rs.next();
            total = rs.getLong(1);
        }

        PreparedStatement page = c.prepare("""
            SELECT c.id, c.first_name, c.last_name, c.company, c.job_title, c.favorite,
                   (SELECT value FROM emails WHERE contact_id = c.id ORDER BY position LIMIT 1),
                   (SELECT value FROM phones WHERE contact_id = c.id ORDER BY position LIMIT 1),
                   (SELECT group_concat(tag_id) FROM contact_tags WHERE contact_id = c.id)
            FROM contacts c""" + where + " ORDER BY " + CONTACT_ORDER + " LIMIT ? OFFSET ?");
        int i = bindFilter(page, f);
        page.setLong(i, limit);
        page.setLong(i + 1, offset);
        List<ContactSummary> items = new ArrayList<>((int) limit);
        try (ResultSet rs = page.executeQuery()) {
            while (rs.next()) {
                items.add(new ContactSummary(rs.getLong(1), rs.getString(2), rs.getString(3), rs.getString(4),
                    rs.getString(5), rs.getLong(6) != 0, rs.getString(7), rs.getString(8),
                    parseIds(rs.getString(9))));
            }
        }
        return new ContactPage(items, total, limit, offset);
    }

    private static final long[] NO_IDS = new long[0];

    private static long[] parseIds(String csv) {
        if (csv == null || csv.isEmpty()) {
            return NO_IDS;
        }
        int n = 1;
        for (int i = 0; i < csv.length(); i++) {
            if (csv.charAt(i) == ',') {
                n++;
            }
        }
        long[] ids = new long[n];
        int k = 0;
        long v = 0;
        for (int i = 0; i < csv.length(); i++) {
            char ch = csv.charAt(i);
            if (ch == ',') {
                ids[k++] = v;
                v = 0;
            } else {
                v = v * 10 + (ch - '0');
            }
        }
        ids[k] = v;
        return ids;
    }

    /** §7.3 plus API-L3: fold '~' (after Z) into '#'. */
    public static List<LetterIndex> letters(Conn c, Filter f) throws SQLException {
        PreparedStatement ps = c.prepare("SELECT c.sort_letter, count(*) FROM contacts c" + where(f)
            + " GROUP BY c.sort_letter ORDER BY c.sort_letter");
        bindFilter(ps, f);
        List<LetterIndex> letters = new ArrayList<>(28);
        long offset = 0;
        try (ResultSet rs = ps.executeQuery()) {
            while (rs.next()) {
                String letter = rs.getString(1);
                long count = rs.getLong(2);
                if (letter.equals("~")) {
                    int hash = -1;
                    for (int i = 0; i < letters.size(); i++) {
                        if (letters.get(i).letter().equals("#")) {
                            hash = i;
                        }
                    }
                    if (hash >= 0) {
                        LetterIndex e = letters.get(hash);
                        letters.set(hash, new LetterIndex("#", e.offset(), e.count() + count));
                    } else {
                        letters.add(new LetterIndex("#", offset, count));
                    }
                } else {
                    letters.add(new LetterIndex(letter, offset, count));
                }
                offset += count;
            }
        }
        return letters;
    }

    /** §7.4; null when the contact doesn't exist. */
    public static Contact getContact(Conn c, long id) throws SQLException {
        PreparedStatement ps = c.prepare("""
            SELECT id, first_name, last_name, company, job_title, birthday, notes, favorite,
                   created_at, updated_at
            FROM contacts WHERE id = ?""");
        ps.setLong(1, id);
        String first, last, company, jobTitle, birthday, notes, createdAt, updatedAt;
        boolean favorite;
        try (ResultSet rs = ps.executeQuery()) {
            if (!rs.next()) {
                return null;
            }
            first = rs.getString(2);
            last = rs.getString(3);
            company = rs.getString(4);
            jobTitle = rs.getString(5);
            birthday = rs.getString(6);
            notes = rs.getString(7);
            favorite = rs.getLong(8) != 0;
            createdAt = rs.getString(9);
            updatedAt = rs.getString(10);
        }
        List<LabeledValue> emails = labeled(c,
            "SELECT label, value FROM emails WHERE contact_id = ? ORDER BY position", id);
        List<LabeledValue> phones = labeled(c,
            "SELECT label, value FROM phones WHERE contact_id = ? ORDER BY position", id);

        List<Address> addresses = new ArrayList<>();
        PreparedStatement ap = c.prepare("""
            SELECT label, street, city, region, postal_code, country
              FROM addresses WHERE contact_id = ? ORDER BY position""");
        ap.setLong(1, id);
        try (ResultSet rs = ap.executeQuery()) {
            while (rs.next()) {
                addresses.add(new Address(rs.getString(1), rs.getString(2), rs.getString(3), rs.getString(4),
                    rs.getString(5), rs.getString(6)));
            }
        }

        List<Tag> tags = new ArrayList<>();
        PreparedStatement tp = c.prepare("""
            SELECT t.id, t.name, t.color FROM tags t
              JOIN contact_tags ct ON ct.tag_id = t.id
              WHERE ct.contact_id = ? ORDER BY t.name COLLATE NOCASE""");
        tp.setLong(1, id);
        try (ResultSet rs = tp.executeQuery()) {
            while (rs.next()) {
                tags.add(new Tag(rs.getLong(1), rs.getString(2), rs.getString(3)));
            }
        }
        return new Contact(id, first, last, company, jobTitle, birthday, notes, favorite, emails, phones,
            addresses, tags, createdAt, updatedAt);
    }

    private static List<LabeledValue> labeled(Conn c, String sql, long id) throws SQLException {
        PreparedStatement ps = c.prepare(sql);
        ps.setLong(1, id);
        List<LabeledValue> out = new ArrayList<>();
        try (ResultSet rs = ps.executeQuery()) {
            while (rs.next()) {
                out.add(new LabeledValue(rs.getString(1), rs.getString(2)));
            }
        }
        return out;
    }

    // ------------------------------------------------------------------ contact writes

    /** §7.5 insert, children and FTS row; call inside a transaction. Returns the new id. */
    public static long insertContact(Conn c, ContactInput in) throws SQLException {
        c.update("""
            INSERT INTO contacts (first_name, last_name, company, job_title, birthday, notes, favorite)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            in.firstName(), in.lastName(), in.company(), in.jobTitle(), in.birthday(), in.notes(),
            in.favorite() ? 1 : 0);
        long id = c.lastInsertRowid();
        insertChildren(c, id, in);
        rebuildFts(c, id);
        return id;
    }

    /** §7.5 replace; false when the contact doesn't exist. Call inside a transaction. */
    public static boolean replaceContact(Conn c, long id, ContactInput in) throws SQLException {
        int changed = c.update("""
            UPDATE contacts SET first_name = ?, last_name = ?, company = ?, job_title = ?,
                birthday = ?, notes = ?, favorite = ?,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ?""",
            in.firstName(), in.lastName(), in.company(), in.jobTitle(), in.birthday(), in.notes(),
            in.favorite() ? 1 : 0, id);
        if (changed == 0) {
            return false;
        }
        c.update("DELETE FROM emails       WHERE contact_id = ?", id);
        c.update("DELETE FROM phones       WHERE contact_id = ?", id);
        c.update("DELETE FROM addresses    WHERE contact_id = ?", id);
        c.update("DELETE FROM contact_tags WHERE contact_id = ?", id);
        insertChildren(c, id, in);
        rebuildFts(c, id);
        return true;
    }

    private static void insertChildren(Conn c, long id, ContactInput in) throws SQLException {
        List<LabeledValue> emails = in.emails();
        for (int i = 0; i < emails.size(); i++) {
            c.update("INSERT INTO emails (contact_id, label, value, position) VALUES (?, ?, ?, ?)",
                id, emails.get(i).label(), emails.get(i).value(), i);
        }
        List<LabeledValue> phones = in.phones();
        for (int i = 0; i < phones.size(); i++) {
            c.update("INSERT INTO phones (contact_id, label, value, position) VALUES (?, ?, ?, ?)",
                id, phones.get(i).label(), phones.get(i).value(), i);
        }
        List<Address> addresses = in.addresses();
        for (int i = 0; i < addresses.size(); i++) {
            Address a = addresses.get(i);
            c.update("""
                INSERT INTO addresses (contact_id, label, street, city, region, postal_code, country, position)
                  VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                id, a.label(), a.street(), a.city(), a.region(), a.postalCode(), a.country(), i);
        }
        for (long tagId : in.tagIds()) {
            try {
                c.update("INSERT INTO contact_tags (contact_id, tag_id) VALUES (?, ?)", id, tagId);
            } catch (SQLiteException e) {
                if (isConstraint(e)) {
                    throw ApiException.invalid("tag " + tagId + " does not exist");
                }
                throw e;
            }
        }
    }

    private static void rebuildFts(Conn c, long id) throws SQLException {
        c.update(FTS_DELETE, id);
        c.update(FTS_INSERT, id);
    }

    /** §7.6: FTS row, then the contact (children cascade). */
    public static boolean deleteContact(Conn c, long id) throws SQLException {
        c.update(FTS_DELETE, id);
        return c.update("DELETE FROM contacts WHERE id = ?", id) > 0;
    }

    public static boolean setFavorite(Conn c, long id, boolean favorite) throws SQLException {
        return c.update("UPDATE contacts SET favorite = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"
            + " WHERE id = ?", favorite ? 1 : 0, id) > 0;
    }

    // ------------------------------------------------------------------ tags (§7.7)

    public static List<TagWithCount> listTags(Conn c) throws SQLException {
        List<TagWithCount> tags = new ArrayList<>();
        try (ResultSet rs = c.prepare("""
            SELECT t.id, t.name, t.color, count(ct.contact_id)
            FROM tags t LEFT JOIN contact_tags ct ON ct.tag_id = t.id
            GROUP BY t.id ORDER BY t.name COLLATE NOCASE""").executeQuery()) {
            while (rs.next()) {
                tags.add(new TagWithCount(rs.getLong(1), rs.getString(2), rs.getString(3), rs.getLong(4)));
            }
        }
        return tags;
    }

    public static Tag getTag(Conn c, long id) throws SQLException {
        PreparedStatement ps = c.prepare("SELECT id, name, color FROM tags WHERE id = ?");
        ps.setLong(1, id);
        try (ResultSet rs = ps.executeQuery()) {
            return rs.next() ? new Tag(rs.getLong(1), rs.getString(2), rs.getString(3)) : null;
        }
    }

    public static Tag createTag(Conn c, TagInput in) throws SQLException {
        try {
            c.update("INSERT INTO tags (name, color) VALUES (?, ?)", in.name(),
                in.color() == null ? "slate" : in.color());
        } catch (SQLiteException e) {
            throw tagConflict(e, in.name());
        }
        return getTag(c, c.lastInsertRowid());
    }

    /** Null when the tag doesn't exist. */
    public static Tag updateTag(Conn c, long id, TagInput in) throws SQLException {
        int changed;
        try {
            changed = c.update("UPDATE tags SET name = ?, color = coalesce(?, color) WHERE id = ?",
                in.name(), in.color(), id);
        } catch (SQLiteException e) {
            throw tagConflict(e, in.name());
        }
        return changed == 0 ? null : getTag(c, id);
    }

    public static boolean deleteTag(Conn c, long id) throws SQLException {
        return c.update("DELETE FROM tags WHERE id = ?", id) > 0;
    }

    private static SQLException tagConflict(SQLiteException e, String name) {
        if (isConstraint(e) && e.getMessage() != null && e.getMessage().contains("UNIQUE")) {
            throw new ApiException(409, "a tag named '" + name + "' already exists");
        }
        return e;
    }

    /** SQLITE_CONSTRAINT (19), including its extended codes. */
    public static boolean isConstraint(SQLiteException e) {
        return (e.getResultCode().code & 0xff) == 19;
    }
}
