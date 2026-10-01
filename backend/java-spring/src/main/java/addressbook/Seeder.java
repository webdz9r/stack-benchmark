package addressbook;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Locale;

import addressbook.Models.Address;
import addressbook.Models.ContactInput;
import addressbook.Models.LabeledValue;

/** The deterministic seeder (05-seeder.md): `./run.sh seed [COUNT]`. */
public final class Seeder {
    private Seeder() {
    }

    private static final String[] FIRST = {
        "Ava", "Liam", "Olivia", "Noah", "Emma", "Oliver", "Sophia", "Elijah", "Isabella", "James",
        "Mia", "Lucas", "Amelia", "Mateo", "Harper", "Benjamin", "Evelyn", "Henry", "Aria", "Theo",
        "Chloe", "Samuel", "Priya", "Arjun", "Mei", "Hiroshi", "Fatima", "Omar", "Zoe", "Diego",
        "Sofia", "Jonas", "Ingrid", "Kwame", "Amara", "Chen", "Yuki", "Leila", "Rafael", "Nadia",
        "Grace", "Ethan", "Hannah", "Isaac", "Julia", "Kofi", "Lena", "Marcus", "Nina", "Oscar",
        "Paula", "Quinn", "Rosa", "Sean", "Tara", "Umar", "Vera", "Wes", "Ximena", "Yusuf",
    };
    private static final String[] LAST = {
        "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez",
        "Martinez", "Hernandez", "Lopez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson",
        "Martin", "Lee", "Patel", "Nguyen", "Kim", "Tanaka", "Okafor", "Müller", "Rossi", "Dubois",
        "Kowalski", "Haddad", "O'Brien", "Andersen", "Silva", "Cohen", "Novak", "Park", "Singh",
        "Bakker", "Castillo", "Dimitrov", "Eriksson", "Fischer", "Gonzaga", "Horvat", "Ivanova",
        "Jensen", "Kaur", "Larsen", "Mendes", "Nakamura", "Osei", "Petrov", "Quintero", "Reyes",
        "Sato", "Tremblay", "Ueda", "Varga", "Walsh", "Xu", "Yilmaz", "Zhou", "Abara", "Byrne",
    };
    private static final String[] COMPANIES = {
        "Acme Corp", "Globex", "Initech", "Umbrella", "Hooli", "Stark Industries",
        "Wayne Enterprises", "Pied Piper", "Soylent", "Wonka Industries", "Cyberdyne", "Tyrell Corp",
        "Vandelay Industries", "Dunder Mifflin", "Massive Dynamic", "Aperture Science", "Oscorp",
        "Gringotts",
    };
    private static final String[] TITLES = {
        "Engineer", "Designer", "Product Manager", "Sales Lead", "CTO", "Founder", "Accountant",
        "Consultant", "Recruiter", "Data Scientist", "Marketing Director", "Support Specialist",
    };
    private static final String[] STREETS = {
        "Main St", "Oak Ave", "Maple Dr", "Cedar Ln", "Pine St", "Elm St", "Park Ave", "Lake Rd",
    };
    private static final String[][] CITIES = {
        {"Austin", "TX", "USA"}, {"Portland", "OR", "USA"}, {"Denver", "CO", "USA"},
        {"Toronto", "ON", "Canada"}, {"London", "", "UK"}, {"Berlin", "", "Germany"},
        {"Chicago", "IL", "USA"}, {"Seattle", "WA", "USA"}, {"Sydney", "NSW", "Australia"},
    };
    private static final String[] NOTES = {
        "", "", "", "Met at the conference last spring.", "Prefers email over phone.",
        "Old college friend.", "Introduced by a mutual friend.", "Follow up about the proposal.",
    };
    private static final String[][] TAGS = {
        {"Family", "red"}, {"Friends", "amber"}, {"Work", "sky"}, {"Clients", "green"},
        {"Vendors", "violet"}, {"Neighbors", "teal"},
    };

    /** 64-bit xorshift on unsigned values: Java's long with >>> and remainderUnsigned. */
    static final class Rng {
        private long state;

        Rng(long existing) {
            state = 0x9E3779B97F4A7C15L ^ (existing * 0x2545F4914F6CDD1DL);
        }

        long next() {
            state ^= state << 13;
            state ^= state >>> 7;
            state ^= state << 17;
            return state;
        }

        int below(int n) {
            return (int) Long.remainderUnsigned(next(), n);
        }

        String pick(String[] arr) {
            return arr[below(arr.length)];
        }

        boolean chance(int percent) {
            return Long.remainderUnsigned(next(), 100) < percent;
        }
    }

    public static void run(Config config, String[] args) throws Exception {
        int count = args.length > 1 ? Integer.parseInt(args[1]) : 10000;
        long started = System.nanoTime();
        try (Db db = Db.open(config.databasePath(), config.migrationsDir(), 0, false)) {
            db.write(c -> c.transaction(tx -> {                                  // SEED-4
                long existing = tx.queryLong("SELECT count(*) FROM contacts");
                long[] tagIds = new long[TAGS.length];
                for (int t = 0; t < TAGS.length; t++) {
                    tx.update("INSERT OR IGNORE INTO tags (name, color) VALUES (?, ?)", TAGS[t][0], TAGS[t][1]);
                    tagIds[t] = tx.queryLong("SELECT id FROM tags WHERE name = ?", TAGS[t][0]);
                }
                Rng rng = new Rng(existing);
                for (long i = existing; i < existing + count; i++) {
                    Store.insertContact(tx, contact(rng, i, tagIds));             // SEED-5
                }
                return null;
            }));
            db.truncateWal();                                                    // SEED-6
        }
        double ms = (System.nanoTime() - started) / 1e6;
        System.out.println(String.format(Locale.ROOT,
            "Inserted %d contacts into %s in %.1f ms (%.0f contacts/sec, each with its emails, phones, "
                + "addresses, tags and search index row)",
            count, config.databasePath(), ms, count / (ms / 1000)));
    }

    static ContactInput contact(Rng rng, long i, long[] tagIds) {
        String first = rng.pick(FIRST);
        String last = rng.pick(LAST);
        String handle = (first + "." + last.replace("'", "").replace("ü", "") + i).toLowerCase(Locale.ROOT);
        boolean hasCompany = rng.chance(70);
        String[] city = CITIES[rng.below(CITIES.length)];
        String company = hasCompany ? rng.pick(COMPANIES) : "";
        String jobTitle = hasCompany ? rng.pick(TITLES) : "";

        String birthday = null;
        if (rng.chance(40)) {
            int y = 1950 + rng.below(55);
            int m = 1 + rng.below(12);
            int d = 1 + rng.below(28);
            birthday = String.format(Locale.ROOT, "%04d-%02d-%02d", y, m, d);
        }
        String notes = rng.pick(NOTES);
        boolean favorite = rng.chance(5);

        List<LabeledValue> emails = new ArrayList<>(2);
        emails.add(new LabeledValue("home", handle + "@example.com"));
        int area = rng.below(1000);
        int line = rng.below(10000);
        List<LabeledValue> phones = List.of(
            new LabeledValue("mobile", String.format(Locale.ROOT, "+1 555-%03d-%04d", area, line)));
        List<Address> addresses = new ArrayList<>(1);

        if (hasCompany && rng.chance(50)) {
            String domain = company.toLowerCase(Locale.ROOT).replace(" ", "");
            emails.add(new LabeledValue("work", handle + "@" + domain + ".com"));
        }
        if (rng.chance(60)) {
            int number = 1 + rng.below(9999);
            String street = rng.pick(STREETS);
            String postal = String.format(Locale.ROOT, "%05d", rng.below(100000));
            addresses.add(new Address("home", number + " " + street, city[0], city[1], postal, city[2]));
        }
        long[] tags = new long[tagIds.length];
        int n = 0;
        for (long tag : tagIds) {
            if (rng.chance(12)) {
                tags[n++] = tag;
            }
        }
        return new ContactInput(first, last, company, jobTitle, birthday, notes, favorite, emails, phones,
            addresses, Arrays.copyOf(tags, n));
    }
}
