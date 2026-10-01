/* Fill the database with fake contacts, all inside one transaction.
 *
 *   ./seed 10000
 *
 * A port of the Rust seeder (same generator, same data for the same starting
 * state; docs/requirements/05-seeder.md). */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "db.h"
#include "repo.h"

#define N(a) (sizeof(a) / sizeof((a)[0]))

static const char *FIRST[] = {
    "Ava", "Liam", "Olivia", "Noah", "Emma", "Oliver", "Sophia", "Elijah", "Isabella", "James",
    "Mia", "Lucas", "Amelia", "Mateo", "Harper", "Benjamin", "Evelyn", "Henry", "Aria", "Theo",
    "Chloe", "Samuel", "Priya", "Arjun", "Mei", "Hiroshi", "Fatima", "Omar", "Zoe", "Diego",
    "Sofia", "Jonas", "Ingrid", "Kwame", "Amara", "Chen", "Yuki", "Leila", "Rafael", "Nadia",
    "Grace", "Ethan", "Hannah", "Isaac", "Julia", "Kofi", "Lena", "Marcus", "Nina", "Oscar",
    "Paula", "Quinn", "Rosa", "Sean", "Tara", "Umar", "Vera", "Wes", "Ximena", "Yusuf",
};
static const char *LAST[] = {
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez",
    "Martinez", "Hernandez", "Lopez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson",
    "Martin", "Lee", "Patel", "Nguyen", "Kim", "Tanaka", "Okafor", "Müller", "Rossi", "Dubois",
    "Kowalski", "Haddad", "O'Brien", "Andersen", "Silva", "Cohen", "Novak", "Park", "Singh",
    "Bakker", "Castillo", "Dimitrov", "Eriksson", "Fischer", "Gonzaga", "Horvat", "Ivanova",
    "Jensen", "Kaur", "Larsen", "Mendes", "Nakamura", "Osei", "Petrov", "Quintero", "Reyes",
    "Sato", "Tremblay", "Ueda", "Varga", "Walsh", "Xu", "Yilmaz", "Zhou", "Abara", "Byrne",
};
static const char *COMPANIES[] = {
    "Acme Corp", "Globex", "Initech", "Umbrella", "Hooli", "Stark Industries", "Wayne Enterprises",
    "Pied Piper", "Soylent", "Wonka Industries", "Cyberdyne", "Tyrell Corp", "Vandelay Industries",
    "Dunder Mifflin", "Massive Dynamic", "Aperture Science", "Oscorp", "Gringotts",
};
static const char *TITLES[] = {
    "Engineer", "Designer", "Product Manager", "Sales Lead", "CTO", "Founder", "Accountant",
    "Consultant", "Recruiter", "Data Scientist", "Marketing Director", "Support Specialist",
};
static const char *STREETS[] = {
    "Main St", "Oak Ave", "Maple Dr", "Cedar Ln", "Pine St", "Elm St", "Park Ave", "Lake Rd",
};
static const char *NOTES[] = {
    "", "", "", "Met at the conference last spring.", "Prefers email over phone.",
    "Old college friend.", "Introduced by a mutual friend.", "Follow up about the proposal.",
};
static const char *CITIES[][3] = {
    {"Austin", "TX", "USA"},
    {"Portland", "OR", "USA"},
    {"Denver", "CO", "USA"},
    {"Toronto", "ON", "Canada"},
    {"London", "", "UK"},
    {"Berlin", "", "Germany"},
    {"Chicago", "IL", "USA"},
    {"Seattle", "WA", "USA"},
    {"Sydney", "NSW", "Australia"},
};
static const char *TAGS[][2] = {
    {"Family", "red"},
    {"Friends", "amber"},
    {"Work", "sky"},
    {"Clients", "green"},
    {"Vendors", "violet"},
    {"Neighbors", "teal"},
};

/* The Rust seeder's xorshift PRNG, bit for bit. */
static uint64_t state;
static uint64_t next_u64(void) {
    state ^= state << 13;
    state ^= state >> 7;
    state ^= state << 17;
    return state;
}
static size_t below(size_t n) { return (size_t)(next_u64() % n); }
static int chance(uint64_t percent) { return next_u64() % 100 < percent; }
#define PICK(arr) ((arr)[below(N(arr))])

static const char *env(const char *name, const char *fallback) {
    const char *v = getenv(name);
    return v && *v ? v : fallback;
}

/* lowercase(first + "." + last without ' and ü + i) */
static void make_handle(char *out, size_t cap, const char *first, const char *last, long long i) {
    char stripped[64];
    size_t w = 0;
    for (const char *p = last; *p && w + 1 < sizeof stripped; p++) {
        if (*p == '\'') continue;
        if ((unsigned char)p[0] == 0xC3 && (unsigned char)p[1] == 0xBC) { p++; continue; } /* ü */
        stripped[w++] = *p;
    }
    stripped[w] = '\0';
    snprintf(out, cap, "%s.%s%lld", first, stripped, i);
    for (char *p = out; *p; p++)
        if (*p >= 'A' && *p <= 'Z') *p = (char)(*p + 32);
}

int main(int argc, char **argv) {
    long long count = argc > 1 ? atoll(argv[1]) : 10000;
    const char *path = env("DATABASE_PATH", "data/address-book.db");
    db_open(path, env("MIGRATIONS_DIR", "../migrations"));
    app_err e = {0};

    conn_t *w = db_begin(&e);
    if (!w) { fprintf(stderr, "%s\n", e.msg); return 1; }
    sqlite3_stmt *s = conn_stmt(w, "SELECT count(*) FROM contacts", &e);
    sqlite3_step(s);
    long long existing = sqlite3_column_int64(s, 0);
    sqlite3_reset(s);
    db_end(w, &e);
    state = 0x9E3779B97F4A7C15ULL ^ ((uint64_t)existing * 0x2545F4914F6CDD1DULL);

    struct timespec t0, t1;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    w = db_begin(&e);
    if (!w) { fprintf(stderr, "%s\n", e.msg); return 1; }

    int64_t tag_ids[N(TAGS)];
    for (size_t t = 0; t < N(TAGS); t++) {
        s = conn_stmt(w, "INSERT OR IGNORE INTO tags (name, color) VALUES (?, ?)", &e);
        sqlite3_bind_text(s, 1, TAGS[t][0], -1, SQLITE_STATIC);
        sqlite3_bind_text(s, 2, TAGS[t][1], -1, SQLITE_STATIC);
        sqlite3_step(s);
        sqlite3_reset(s);
        s = conn_stmt(w, "SELECT id FROM tags WHERE name = ?", &e);
        sqlite3_bind_text(s, 1, TAGS[t][0], -1, SQLITE_STATIC);
        sqlite3_step(s);
        tag_ids[t] = sqlite3_column_int64(s, 0);
        sqlite3_reset(s);
    }

    for (long long i = existing; i < existing + count && !e.status; i++) {
        const char *first = PICK(FIRST), *last = PICK(LAST);
        char handle[128], birthday[16], phone[32], work_email[192], home_email[160], street[64], postal[8], domain[64];
        make_handle(handle, sizeof handle, first, last, i);
        int has_company = chance(70);
        const char *const *city = CITIES[below(N(CITIES))];
        const char *company = has_company ? PICK(COMPANIES) : "";
        const char *job_title = has_company ? PICK(TITLES) : "";
        int has_birthday = chance(40);
        if (has_birthday) {
            int y = 1950 + (int)below(55), m = 1 + (int)below(12), d = 1 + (int)below(28);
            snprintf(birthday, sizeof birthday, "%04d-%02d-%02d", y, m, d);
        }
        const char *notes = PICK(NOTES);
        int favorite = chance(5);
        int p3 = (int)below(1000), p4 = (int)below(10000);
        snprintf(phone, sizeof phone, "+1 555-%03d-%04d", p3, p4);
        snprintf(home_email, sizeof home_email, "%s@example.com", handle);

        labeled_t emails[2] = {{"home", home_email}};
        labeled_t phones[1] = {{"mobile", phone}};
        address_t addr;
        int64_t tags[N(TAGS)];
        contact_t c = {
            .first_name = (char *)first, .last_name = (char *)last, .company = (char *)company,
            .job_title = (char *)job_title, .notes = (char *)notes, .birthday = has_birthday ? birthday : NULL,
            .favorite = favorite, .emails = emails, .n_emails = 1, .phones = phones, .n_phones = 1,
            .addresses = &addr, .n_addresses = 0, .tag_ids = tags, .n_tag_ids = 0,
        };
        if (has_company && chance(50)) {
            size_t k = 0;
            for (const char *p = company; *p && k + 1 < sizeof domain; p++)
                if (*p != ' ') domain[k++] = (char)((*p >= 'A' && *p <= 'Z') ? *p + 32 : *p);
            domain[k] = '\0';
            snprintf(work_email, sizeof work_email, "%s@%s.com", handle, domain);
            emails[1] = (labeled_t){"work", work_email};
            c.n_emails = 2;
        }
        if (chance(60)) {
            int number = 1 + (int)below(9999);
            const char *street_name = PICK(STREETS);
            snprintf(street, sizeof street, "%d %s", number, street_name);
            snprintf(postal, sizeof postal, "%05d", (int)below(100000));
            addr = (address_t){"home", street, (char *)city[0], (char *)city[1], postal, (char *)city[2]};
            c.n_addresses = 1;
        }
        for (size_t t = 0; t < N(TAGS); t++)
            if (chance(12)) tags[c.n_tag_ids++] = tag_ids[t];

        int64_t id;
        repo_insert_contact(w, &c, &id, &e);
    }
    db_end(w, &e);
    if (e.status) { fprintf(stderr, "seed failed: %s\n", e.msg); return 1; }
    /* One big transaction leaves an equally big WAL; fold it in now. */
    db_truncate_wal();

    clock_gettime(CLOCK_MONOTONIC, &t1);
    double secs = (double)(t1.tv_sec - t0.tv_sec) + (double)(t1.tv_nsec - t0.tv_nsec) / 1e9;
    printf("Inserted %lld contacts into %s in %.1f ms (%.0f contacts/sec, each with its emails, phones, addresses, "
           "tags and search index row)\n", count, path, secs * 1000, (double)count / secs);
    return 0;
}
