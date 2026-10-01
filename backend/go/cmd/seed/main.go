// Fill the database with fake contacts, all inside one transaction.
//
//	go run -tags sqlite_fts5 ./cmd/seed 10000
//
// A port of the Rust seeder (same generator, same data for the same starting
// state), so the two can be compared on insert speed.
package main

import (
	"context"
	"database/sql"
	"fmt"
	"log"
	"os"
	"strconv"
	"strings"
	"time"

	"addressbook/app"
)

var firstNames = []string{
	"Ava", "Liam", "Olivia", "Noah", "Emma", "Oliver", "Sophia", "Elijah", "Isabella", "James",
	"Mia", "Lucas", "Amelia", "Mateo", "Harper", "Benjamin", "Evelyn", "Henry", "Aria", "Theo",
	"Chloe", "Samuel", "Priya", "Arjun", "Mei", "Hiroshi", "Fatima", "Omar", "Zoe", "Diego",
	"Sofia", "Jonas", "Ingrid", "Kwame", "Amara", "Chen", "Yuki", "Leila", "Rafael", "Nadia",
	"Grace", "Ethan", "Hannah", "Isaac", "Julia", "Kofi", "Lena", "Marcus", "Nina", "Oscar",
	"Paula", "Quinn", "Rosa", "Sean", "Tara", "Umar", "Vera", "Wes", "Ximena", "Yusuf",
}

var lastNames = []string{
	"Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez",
	"Martinez", "Hernandez", "Lopez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson",
	"Martin", "Lee", "Patel", "Nguyen", "Kim", "Tanaka", "Okafor", "Müller", "Rossi", "Dubois",
	"Kowalski", "Haddad", "O'Brien", "Andersen", "Silva", "Cohen", "Novak", "Park", "Singh",
	"Bakker", "Castillo", "Dimitrov", "Eriksson", "Fischer", "Gonzaga", "Horvat", "Ivanova",
	"Jensen", "Kaur", "Larsen", "Mendes", "Nakamura", "Osei", "Petrov", "Quintero", "Reyes",
	"Sato", "Tremblay", "Ueda", "Varga", "Walsh", "Xu", "Yilmaz", "Zhou", "Abara", "Byrne",
}

var companies = []string{
	"Acme Corp", "Globex", "Initech", "Umbrella", "Hooli", "Stark Industries", "Wayne Enterprises",
	"Pied Piper", "Soylent", "Wonka Industries", "Cyberdyne", "Tyrell Corp", "Vandelay Industries",
	"Dunder Mifflin", "Massive Dynamic", "Aperture Science", "Oscorp", "Gringotts",
}

var titles = []string{
	"Engineer", "Designer", "Product Manager", "Sales Lead", "CTO", "Founder", "Accountant",
	"Consultant", "Recruiter", "Data Scientist", "Marketing Director", "Support Specialist",
}

var streets = []string{
	"Main St", "Oak Ave", "Maple Dr", "Cedar Ln", "Pine St", "Elm St", "Park Ave", "Lake Rd",
}

var notes = []string{
	"", "", "", "Met at the conference last spring.", "Prefers email over phone.",
	"Old college friend.", "Introduced by a mutual friend.", "Follow up about the proposal.",
}

var cities = [][3]string{
	{"Austin", "TX", "USA"},
	{"Portland", "OR", "USA"},
	{"Denver", "CO", "USA"},
	{"Toronto", "ON", "Canada"},
	{"London", "", "UK"},
	{"Berlin", "", "Germany"},
	{"Chicago", "IL", "USA"},
	{"Seattle", "WA", "USA"},
	{"Sydney", "NSW", "Australia"},
}

var tags = [][2]string{
	{"Family", "red"},
	{"Friends", "amber"},
	{"Work", "sky"},
	{"Clients", "green"},
	{"Vendors", "violet"},
	{"Neighbors", "teal"},
}

// rng is the Rust seeder's xorshift PRNG, bit for bit.
type rng struct{ state uint64 }

func (r *rng) next() uint64 {
	r.state ^= r.state << 13
	r.state ^= r.state >> 7
	r.state ^= r.state << 17
	return r.state
}
func (r *rng) below(n int) int            { return int(r.next() % uint64(n)) }
func (r *rng) pick(items []string) string { return items[r.below(len(items))] }
func (r *rng) chance(percent uint64) bool { return r.next()%100 < percent }

func env(name, fallback string) string {
	if v := os.Getenv(name); v != "" {
		return v
	}
	return fallback
}

func main() {
	count := 10_000
	if len(os.Args) > 1 {
		n, err := strconv.Atoi(os.Args[1])
		if err != nil {
			log.Fatal("usage: seed [count]")
		}
		count = n
	}
	path := env("DATABASE_PATH", "data/address-book.db")
	db, err := app.Open(path, 1, env("MIGRATIONS_DIR", "../migrations"))
	if err != nil {
		log.Fatal(err)
	}
	ctx := context.Background()
	var existing int
	if err := db.Reader().QueryRowContext(ctx, "SELECT count(*) FROM contacts").Scan(&existing); err != nil {
		log.Fatal(err)
	}
	r := &rng{0x9E3779B97F4A7C15 ^ uint64(existing)*0x2545F4914F6CDD1D}
	stripHandle := strings.NewReplacer("'", "", "ü", "")

	started := time.Now()
	err = db.Transaction(ctx, func(tx *sql.Tx) error {
		var tagIDs []int64
		for _, t := range tags {
			if _, err := tx.Exec("INSERT OR IGNORE INTO tags (name, color) VALUES (?, ?)", t[0], t[1]); err != nil {
				return err
			}
			var id int64
			if err := tx.QueryRow("SELECT id FROM tags WHERE name = ?", t[0]).Scan(&id); err != nil {
				return err
			}
			tagIDs = append(tagIDs, id)
		}

		for i := existing; i < existing+count; i++ {
			first := r.pick(firstNames)
			last := r.pick(lastNames)
			handle := strings.ToLower(fmt.Sprintf("%s.%s%d", first, stripHandle.Replace(last), i))
			hasCompany := r.chance(70)
			city := cities[r.below(len(cities))]

			c := app.ContactInput{FirstName: first, LastName: last}
			if hasCompany {
				c.Company = r.pick(companies)
				c.JobTitle = r.pick(titles)
			}
			if r.chance(40) {
				b := fmt.Sprintf("%d-%02d-%02d", 1950+r.below(55), 1+r.below(12), 1+r.below(28))
				c.Birthday = &b
			}
			c.Notes = r.pick(notes)
			c.Favorite = r.chance(5)
			c.Emails = []app.LabeledValue{{Label: "home", Value: handle + "@example.com"}}
			c.Phones = []app.LabeledValue{{Label: "mobile", Value: fmt.Sprintf("+1 555-%03d-%04d", r.below(1000), r.below(10_000))}}
			if hasCompany && r.chance(50) {
				domain := strings.ReplaceAll(strings.ToLower(c.Company), " ", "")
				c.Emails = append(c.Emails, app.LabeledValue{Label: "work", Value: handle + "@" + domain + ".com"})
			}
			if r.chance(60) {
				c.Addresses = []app.Address{{
					Label:      "home",
					Street:     fmt.Sprintf("%d %s", 1+r.below(9999), r.pick(streets)),
					City:       city[0],
					Region:     city[1],
					PostalCode: fmt.Sprintf("%05d", r.below(100_000)),
					Country:    city[2],
				}}
			}
			for _, id := range tagIDs {
				if r.chance(12) {
					c.TagIDs = append(c.TagIDs, id)
				}
			}
			if _, err := app.InsertContact(ctx, tx, &c); err != nil {
				return err
			}
		}
		return nil
	})
	if err != nil {
		log.Fatal(err)
	}
	// One big transaction leaves an equally big WAL; fold it in now.
	if err := db.TruncateWal(); err != nil {
		log.Fatal(err)
	}
	secs := time.Since(started).Seconds()
	fmt.Printf("Inserted %d contacts into %s in %.1f ms (%.0f contacts/sec, each with its emails, phones, addresses, tags and search index row)\n",
		count, path, secs*1000, float64(count)/secs)
}
