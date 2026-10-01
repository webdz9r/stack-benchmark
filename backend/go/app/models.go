package app

import (
	"regexp"
	"slices"
	"strconv"
	"strings"
	"unicode"
	"unicode/utf8"
)

type LabeledValue struct {
	Label string `json:"label"`
	Value string `json:"value"`
}

type Address struct {
	Label      string `json:"label"`
	Street     string `json:"street"`
	City       string `json:"city"`
	Region     string `json:"region"`
	PostalCode string `json:"postal_code"`
	Country    string `json:"country"`
}

func (a *Address) blank() bool {
	for _, s := range []string{a.Street, a.City, a.Region, a.PostalCode, a.Country} {
		if strings.TrimSpace(s) != "" {
			return false
		}
	}
	return true
}

type Tag struct {
	ID    int64  `json:"id"`
	Name  string `json:"name"`
	Color string `json:"color"`
}

type TagWithCount struct {
	Tag
	ContactCount int64 `json:"contact_count"`
}

type Contact struct {
	ID        int64          `json:"id"`
	FirstName string         `json:"first_name"`
	LastName  string         `json:"last_name"`
	Company   string         `json:"company"`
	JobTitle  string         `json:"job_title"`
	Birthday  *string        `json:"birthday"`
	Notes     string         `json:"notes"`
	Favorite  bool           `json:"favorite"`
	Emails    []LabeledValue `json:"emails"`
	Phones    []LabeledValue `json:"phones"`
	Addresses []Address      `json:"addresses"`
	Tags      []Tag          `json:"tags"`
	CreatedAt string         `json:"created_at"`
	UpdatedAt string         `json:"updated_at"`
}

type ContactSummary struct {
	ID        int64   `json:"id"`
	FirstName string  `json:"first_name"`
	LastName  string  `json:"last_name"`
	Company   string  `json:"company"`
	JobTitle  string  `json:"job_title"`
	Favorite  bool    `json:"favorite"`
	Email     *string `json:"email"`
	Phone     *string `json:"phone"`
	TagIDs    []int64 `json:"tag_ids"`
}

type ContactPage struct {
	Items  []ContactSummary `json:"items"`
	Total  int64            `json:"total"`
	Limit  int64            `json:"limit"`
	Offset int64            `json:"offset"`
}

type LetterIndex struct {
	Letter string `json:"letter"`
	Offset int64  `json:"offset"`
	Count  int64  `json:"count"`
}

type ListQuery struct {
	Q        string
	Tag      *int64
	Favorite bool
	Limit    *int64
	Offset   *int64
}

// ContactInput is the body for creating or replacing a contact.
type ContactInput struct {
	FirstName string         `json:"first_name"`
	LastName  string         `json:"last_name"`
	Company   string         `json:"company"`
	JobTitle  string         `json:"job_title"`
	Birthday  *string        `json:"birthday"`
	Notes     string         `json:"notes"`
	Favorite  bool           `json:"favorite"`
	Emails    []LabeledValue `json:"emails"`
	Phones    []LabeledValue `json:"phones"`
	Addresses []Address      `json:"addresses"`
	TagIDs    []int64        `json:"tag_ids"`
}

var isoDate = regexp.MustCompile(`^(\d{4})-(\d{2})-(\d{2})$`)

// Validate trims fields, drops empty rows, and rejects obviously bad input;
// same rules as the Rust backend.
func (c *ContactInput) Validate() error {
	for _, s := range []*string{&c.FirstName, &c.LastName, &c.Company, &c.JobTitle, &c.Notes} {
		*s = strings.TrimSpace(*s)
	}
	if c.FirstName == "" && c.LastName == "" && c.Company == "" {
		return Validation("a name or company is required")
	}
	if c.Birthday != nil {
		b := strings.TrimSpace(*c.Birthday)
		c.Birthday = &b
		if b == "" {
			c.Birthday = nil
		} else if m := isoDate.FindStringSubmatch(b); m == nil || !inRange(m[2], 1, 12) || !inRange(m[3], 1, 31) {
			return Validation("birthday must be YYYY-MM-DD")
		}
	}
	for _, list := range []*[]LabeledValue{&c.Emails, &c.Phones} {
		kept := (*list)[:0]
		for _, v := range *list {
			v.Value = strings.TrimSpace(v.Value)
			if v.Value == "" {
				continue
			}
			v.Label = normalizeLabel(v.Label)
			kept = append(kept, v)
		}
		*list = kept
	}
	for _, e := range c.Emails {
		user, domain, found := strings.Cut(e.Value, "@")
		if !found || user == "" || !strings.Contains(domain, ".") || strings.IndexFunc(e.Value, unicode.IsSpace) >= 0 {
			return Validation("'" + e.Value + "' is not a valid email")
		}
	}
	kept := c.Addresses[:0]
	for _, a := range c.Addresses {
		if a.blank() {
			continue
		}
		a.Label = normalizeLabel(a.Label)
		for _, s := range []*string{&a.Street, &a.City, &a.Region, &a.PostalCode, &a.Country} {
			*s = strings.TrimSpace(*s)
		}
		kept = append(kept, a)
	}
	c.Addresses = kept
	slices.Sort(c.TagIDs)
	c.TagIDs = slices.Compact(c.TagIDs)
	return nil
}

var TagColors = []string{"slate", "red", "orange", "amber", "green", "teal", "sky", "indigo", "violet", "pink"}

type TagInput struct {
	Name  string  `json:"name"`
	Color *string `json:"color"`
}

func (t *TagInput) Validate() error {
	t.Name = strings.TrimSpace(t.Name)
	if t.Name == "" {
		return Validation("tag name is required")
	}
	if utf8.RuneCountInString(t.Name) > 40 {
		return Validation("tag name must be 40 characters or fewer")
	}
	if t.Color != nil && !slices.Contains(TagColors, *t.Color) {
		return Validation("unknown tag color '" + *t.Color + "'")
	}
	return nil
}

func normalizeLabel(label string) string {
	label = strings.ToLower(strings.TrimSpace(label))
	if label == "" {
		return "other"
	}
	return label
}

func inRange(s string, lo, hi int) bool {
	n, err := strconv.Atoi(s)
	return err == nil && n >= lo && n <= hi
}
