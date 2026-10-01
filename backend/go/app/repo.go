package app

// Plain SQL; the same statements as the Rust backend's repo.rs.

import (
	"context"
	"database/sql"
	"errors"
	"strconv"
	"strings"
	"unicode"
)

const (
	maxPage      = 200
	contactOrder = "c.sort_key COLLATE NOCASE, c.first_name COLLATE NOCASE, c.id"
	now          = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"
)

// FtsQuery turns free text into a safe FTS5 query: each word a quoted prefix
// term. `jo smi` -> `"jo"* "smi"*`. Empty when there's nothing to search for.
// A word is made of Unicode letters, marks and numbers, plus `@ . '`.
func FtsQuery(text string) string {
	terms := strings.FieldsFunc(text, func(r rune) bool {
		return !(unicode.IsLetter(r) || unicode.IsMark(r) || unicode.IsNumber(r) || r == '@' || r == '.' || r == '\'')
	})
	for i, t := range terms {
		terms[i] = `"` + strings.ReplaceAll(t, `"`, `""`) + `"*`
	}
	return strings.Join(terms, " ")
}

func filters(q ListQuery) (string, []any) {
	var clauses []string
	var args []any
	if fts := FtsQuery(q.Q); fts != "" {
		clauses = append(clauses, "c.id IN (SELECT rowid FROM contacts_fts WHERE contacts_fts MATCH ?)")
		args = append(args, fts)
	}
	if q.Tag != nil {
		clauses = append(clauses, "c.id IN (SELECT contact_id FROM contact_tags WHERE tag_id = ?)")
		args = append(args, *q.Tag)
	}
	if q.Favorite {
		clauses = append(clauses, "c.favorite = 1")
	}
	if len(clauses) == 0 {
		return "", args
	}
	return "WHERE " + strings.Join(clauses, " AND "), args
}

func ListContacts(ctx context.Context, db Querier, q ListQuery) (*ContactPage, error) {
	limit, offset := int64(50), int64(0)
	if q.Limit != nil {
		limit = min(max(*q.Limit, 1), maxPage)
	}
	if q.Offset != nil {
		offset = max(*q.Offset, 0)
	}
	where, args := filters(q)

	page := &ContactPage{Items: []ContactSummary{}, Limit: limit, Offset: offset}
	if err := db.QueryRowContext(ctx, "SELECT count(*) FROM contacts c "+where, args...).Scan(&page.Total); err != nil {
		return nil, err
	}
	rows, err := db.QueryContext(ctx, `SELECT c.id, c.first_name, c.last_name, c.company, c.job_title, c.favorite,
			(SELECT value FROM emails WHERE contact_id = c.id ORDER BY position LIMIT 1),
			(SELECT value FROM phones WHERE contact_id = c.id ORDER BY position LIMIT 1),
			(SELECT group_concat(tag_id) FROM contact_tags WHERE contact_id = c.id)
		FROM contacts c
		`+where+`
		ORDER BY `+contactOrder+`
		LIMIT ? OFFSET ?`, append(args, limit, offset)...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var s ContactSummary
		var email, phone, tags sql.NullString
		if err := rows.Scan(&s.ID, &s.FirstName, &s.LastName, &s.Company, &s.JobTitle, &s.Favorite, &email, &phone, &tags); err != nil {
			return nil, err
		}
		s.Email, s.Phone = nullable(email), nullable(phone)
		s.TagIDs = []int64{}
		if tags.Valid {
			for _, t := range strings.Split(tags.String, ",") {
				id, _ := strconv.ParseInt(t, 10, 64)
				s.TagIDs = append(s.TagIDs, id)
			}
		}
		page.Items = append(page.Items, s)
	}
	return page, rows.Err()
}

// ListLetters reports where each file letter starts in the sorted, filtered
// list. Buckets are contiguous and sort like the list ('#' < 'A'..'Z' < '~'),
// so offsets are running totals; '~' (after Z) is reported as '#'.
func ListLetters(ctx context.Context, db Querier, q ListQuery) ([]LetterIndex, error) {
	where, args := filters(q)
	rows, err := db.QueryContext(ctx, "SELECT c.sort_letter, count(*) FROM contacts c "+where+
		" GROUP BY c.sort_letter ORDER BY c.sort_letter", args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	letters := []LetterIndex{}
	var offset int64
	for rows.Next() {
		var letter string
		var count int64
		if err := rows.Scan(&letter, &count); err != nil {
			return nil, err
		}
		if letter == "~" {
			merged := false
			for i := range letters {
				if letters[i].Letter == "#" {
					letters[i].Count += count
					merged = true
				}
			}
			if !merged {
				letters = append(letters, LetterIndex{"#", offset, count})
			}
		} else {
			letters = append(letters, LetterIndex{letter, offset, count})
		}
		offset += count
	}
	return letters, rows.Err()
}

func GetContact(ctx context.Context, db Querier, id int64) (*Contact, error) {
	c := &Contact{Emails: []LabeledValue{}, Phones: []LabeledValue{}, Addresses: []Address{}, Tags: []Tag{}}
	var birthday sql.NullString
	err := db.QueryRowContext(ctx, `SELECT id, first_name, last_name, company, job_title, birthday, notes, favorite,
			created_at, updated_at FROM contacts WHERE id = ?`, id).
		Scan(&c.ID, &c.FirstName, &c.LastName, &c.Company, &c.JobTitle, &birthday, &c.Notes, &c.Favorite, &c.CreatedAt, &c.UpdatedAt)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, NotFound()
	} else if err != nil {
		return nil, err
	}
	c.Birthday = nullable(birthday)

	for _, list := range []struct {
		table string
		dst   *[]LabeledValue
	}{{"emails", &c.Emails}, {"phones", &c.Phones}} {
		err := each(ctx, db, "SELECT label, value FROM "+list.table+" WHERE contact_id = ? ORDER BY position", []any{id},
			func(r *sql.Rows) error {
				var v LabeledValue
				*list.dst = append(*list.dst, v)
				last := &(*list.dst)[len(*list.dst)-1]
				return r.Scan(&last.Label, &last.Value)
			})
		if err != nil {
			return nil, err
		}
	}
	err = each(ctx, db, `SELECT label, street, city, region, postal_code, country
		FROM addresses WHERE contact_id = ? ORDER BY position`, []any{id}, func(r *sql.Rows) error {
		var a Address
		if err := r.Scan(&a.Label, &a.Street, &a.City, &a.Region, &a.PostalCode, &a.Country); err != nil {
			return err
		}
		c.Addresses = append(c.Addresses, a)
		return nil
	})
	if err != nil {
		return nil, err
	}
	err = each(ctx, db, `SELECT t.id, t.name, t.color FROM tags t
		JOIN contact_tags ct ON ct.tag_id = t.id
		WHERE ct.contact_id = ? ORDER BY t.name COLLATE NOCASE`, []any{id}, func(r *sql.Rows) error {
		var t Tag
		if err := r.Scan(&t.ID, &t.Name, &t.Color); err != nil {
			return err
		}
		c.Tags = append(c.Tags, t)
		return nil
	})
	if err != nil {
		return nil, err
	}
	return c, nil
}

func InsertContact(ctx context.Context, tx *sql.Tx, c *ContactInput) (int64, error) {
	res, err := tx.ExecContext(ctx, `INSERT INTO contacts (first_name, last_name, company, job_title, birthday, notes, favorite)
		VALUES (?, ?, ?, ?, ?, ?, ?)`, c.FirstName, c.LastName, c.Company, c.JobTitle, c.Birthday, c.Notes, c.Favorite)
	if err != nil {
		return 0, err
	}
	id, _ := res.LastInsertId()
	if err := writeChildren(ctx, tx, id, c); err != nil {
		return 0, err
	}
	return id, refreshFts(ctx, tx, id)
}

func UpdateContact(ctx context.Context, tx *sql.Tx, id int64, c *ContactInput) error {
	res, err := tx.ExecContext(ctx, `UPDATE contacts SET first_name = ?, last_name = ?, company = ?, job_title = ?,
			birthday = ?, notes = ?, favorite = ?, updated_at = `+now+` WHERE id = ?`,
		c.FirstName, c.LastName, c.Company, c.JobTitle, c.Birthday, c.Notes, c.Favorite, id)
	if err != nil {
		return err
	}
	if n, _ := res.RowsAffected(); n == 0 {
		return NotFound()
	}
	for _, table := range []string{"emails", "phones", "addresses", "contact_tags"} {
		if _, err := tx.ExecContext(ctx, "DELETE FROM "+table+" WHERE contact_id = ?", id); err != nil {
			return err
		}
	}
	if err := writeChildren(ctx, tx, id, c); err != nil {
		return err
	}
	return refreshFts(ctx, tx, id)
}

func SetFavorite(ctx context.Context, tx *sql.Tx, id int64, favorite bool) error {
	return mustChange(tx.ExecContext(ctx, "UPDATE contacts SET favorite = ?, updated_at = "+now+" WHERE id = ?", favorite, id))
}

func DeleteContact(ctx context.Context, tx *sql.Tx, id int64) error {
	// Children go via ON DELETE CASCADE; the FTS table has no foreign key.
	if _, err := tx.ExecContext(ctx, "DELETE FROM contacts_fts WHERE rowid = ?", id); err != nil {
		return err
	}
	return mustChange(tx.ExecContext(ctx, "DELETE FROM contacts WHERE id = ?", id))
}

func writeChildren(ctx context.Context, tx *sql.Tx, id int64, c *ContactInput) error {
	for i, e := range c.Emails {
		if _, err := tx.ExecContext(ctx, "INSERT INTO emails (contact_id, label, value, position) VALUES (?, ?, ?, ?)", id, e.Label, e.Value, i); err != nil {
			return err
		}
	}
	for i, p := range c.Phones {
		if _, err := tx.ExecContext(ctx, "INSERT INTO phones (contact_id, label, value, position) VALUES (?, ?, ?, ?)", id, p.Label, p.Value, i); err != nil {
			return err
		}
	}
	for i, a := range c.Addresses {
		if _, err := tx.ExecContext(ctx, `INSERT INTO addresses (contact_id, label, street, city, region, postal_code, country, position)
			VALUES (?, ?, ?, ?, ?, ?, ?, ?)`, id, a.Label, a.Street, a.City, a.Region, a.PostalCode, a.Country, i); err != nil {
			return err
		}
	}
	for _, tagID := range c.TagIDs {
		if _, err := tx.ExecContext(ctx, "INSERT INTO contact_tags (contact_id, tag_id) VALUES (?, ?)", id, tagID); err != nil {
			if isConstraint(err) {
				return Validation("tag " + strconv.FormatInt(tagID, 10) + " does not exist")
			}
			return err
		}
	}
	return nil
}

// refreshFts rebuilds one contact's search document from its current rows.
func refreshFts(ctx context.Context, tx *sql.Tx, id int64) error {
	if _, err := tx.ExecContext(ctx, "DELETE FROM contacts_fts WHERE rowid = ?", id); err != nil {
		return err
	}
	_, err := tx.ExecContext(ctx, `INSERT INTO contacts_fts (rowid, name, company, emails, phones, places, notes)
		SELECT c.id,
			c.first_name || ' ' || c.last_name,
			c.company || ' ' || c.job_title,
			coalesce((SELECT group_concat(value, ' ') FROM emails WHERE contact_id = c.id), ''),
			coalesce((SELECT group_concat(value, ' ') FROM phones WHERE contact_id = c.id), ''),
			coalesce((SELECT group_concat(street || ' ' || city || ' ' || region || ' ' || country, ' ')
				FROM addresses WHERE contact_id = c.id), ''),
			c.notes
		FROM contacts c WHERE c.id = ?`, id)
	return err
}

// ---------------------------------------------------------------- tags

func ListTags(ctx context.Context, db Querier) ([]TagWithCount, error) {
	tags := []TagWithCount{}
	err := each(ctx, db, `SELECT t.id, t.name, t.color, count(ct.contact_id)
		FROM tags t LEFT JOIN contact_tags ct ON ct.tag_id = t.id
		GROUP BY t.id ORDER BY t.name COLLATE NOCASE`, nil, func(r *sql.Rows) error {
		var t TagWithCount
		if err := r.Scan(&t.ID, &t.Name, &t.Color, &t.ContactCount); err != nil {
			return err
		}
		tags = append(tags, t)
		return nil
	})
	return tags, err
}

func getTag(ctx context.Context, db Querier, id int64) (*Tag, error) {
	var t Tag
	err := db.QueryRowContext(ctx, "SELECT id, name, color FROM tags WHERE id = ?", id).Scan(&t.ID, &t.Name, &t.Color)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, NotFound()
	}
	return &t, err
}

func InsertTag(ctx context.Context, tx *sql.Tx, t *TagInput) (*Tag, error) {
	color := "slate"
	if t.Color != nil {
		color = *t.Color
	}
	res, err := tx.ExecContext(ctx, "INSERT INTO tags (name, color) VALUES (?, ?)", t.Name, color)
	if err != nil {
		return nil, tagConflict(err, t.Name)
	}
	id, _ := res.LastInsertId()
	return getTag(ctx, tx, id)
}

func UpdateTag(ctx context.Context, tx *sql.Tx, id int64, t *TagInput) (*Tag, error) {
	res, err := tx.ExecContext(ctx, "UPDATE tags SET name = ?, color = coalesce(?, color) WHERE id = ?", t.Name, t.Color, id)
	if err != nil {
		return nil, tagConflict(err, t.Name)
	}
	if n, _ := res.RowsAffected(); n == 0 {
		return nil, NotFound()
	}
	return getTag(ctx, tx, id)
}

func DeleteTag(ctx context.Context, tx *sql.Tx, id int64) error {
	return mustChange(tx.ExecContext(ctx, "DELETE FROM tags WHERE id = ?", id))
}

func tagConflict(err error, name string) error {
	if isConstraint(err) {
		return Conflict("a tag named '" + name + "' already exists")
	}
	return err
}

// ---------------------------------------------------------------- stats

type Stats struct {
	Contacts  int64 `json:"contacts"`
	Favorites int64 `json:"favorites"`
}

func GetStats(ctx context.Context, db Querier) (*Stats, error) {
	var s Stats
	err := db.QueryRowContext(ctx, "SELECT count(*), coalesce(sum(favorite), 0) FROM contacts").Scan(&s.Contacts, &s.Favorites)
	return &s, err
}

// ---------------------------------------------------------------- helpers

func each(ctx context.Context, db Querier, query string, args []any, fn func(*sql.Rows) error) error {
	rows, err := db.QueryContext(ctx, query, args...)
	if err != nil {
		return err
	}
	defer rows.Close()
	for rows.Next() {
		if err := fn(rows); err != nil {
			return err
		}
	}
	return rows.Err()
}

func mustChange(res sql.Result, err error) error {
	if err != nil {
		return err
	}
	if n, _ := res.RowsAffected(); n == 0 {
		return NotFound()
	}
	return nil
}

func nullable(s sql.NullString) *string {
	if !s.Valid {
		return nil
	}
	return &s.String
}
