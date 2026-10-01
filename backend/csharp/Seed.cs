using System.Diagnostics;

namespace AddressBook;

/// <summary>
/// Fill the database with fake contacts, all inside one transaction.
///
///   dotnet run -c Release -- seed 10000
///
/// A port of the Rust seeder (same generator, same data for the same starting
/// state), so the two can be compared on insert speed.
/// </summary>
public static class Seed
{
    static readonly string[] FirstNames =
    [
        "Ava", "Liam", "Olivia", "Noah", "Emma", "Oliver", "Sophia", "Elijah", "Isabella", "James",
        "Mia", "Lucas", "Amelia", "Mateo", "Harper", "Benjamin", "Evelyn", "Henry", "Aria", "Theo",
        "Chloe", "Samuel", "Priya", "Arjun", "Mei", "Hiroshi", "Fatima", "Omar", "Zoe", "Diego",
        "Sofia", "Jonas", "Ingrid", "Kwame", "Amara", "Chen", "Yuki", "Leila", "Rafael", "Nadia",
        "Grace", "Ethan", "Hannah", "Isaac", "Julia", "Kofi", "Lena", "Marcus", "Nina", "Oscar",
        "Paula", "Quinn", "Rosa", "Sean", "Tara", "Umar", "Vera", "Wes", "Ximena", "Yusuf",
    ];

    static readonly string[] LastNames =
    [
        "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez",
        "Martinez", "Hernandez", "Lopez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson",
        "Martin", "Lee", "Patel", "Nguyen", "Kim", "Tanaka", "Okafor", "Müller", "Rossi", "Dubois",
        "Kowalski", "Haddad", "O'Brien", "Andersen", "Silva", "Cohen", "Novak", "Park", "Singh",
        "Bakker", "Castillo", "Dimitrov", "Eriksson", "Fischer", "Gonzaga", "Horvat", "Ivanova",
        "Jensen", "Kaur", "Larsen", "Mendes", "Nakamura", "Osei", "Petrov", "Quintero", "Reyes",
        "Sato", "Tremblay", "Ueda", "Varga", "Walsh", "Xu", "Yilmaz", "Zhou", "Abara", "Byrne",
    ];

    static readonly string[] Companies =
    [
        "Acme Corp", "Globex", "Initech", "Umbrella", "Hooli", "Stark Industries", "Wayne Enterprises",
        "Pied Piper", "Soylent", "Wonka Industries", "Cyberdyne", "Tyrell Corp", "Vandelay Industries",
        "Dunder Mifflin", "Massive Dynamic", "Aperture Science", "Oscorp", "Gringotts",
    ];

    static readonly string[] Titles =
    [
        "Engineer", "Designer", "Product Manager", "Sales Lead", "CTO", "Founder", "Accountant",
        "Consultant", "Recruiter", "Data Scientist", "Marketing Director", "Support Specialist",
    ];

    static readonly string[] Streets =
    [
        "Main St", "Oak Ave", "Maple Dr", "Cedar Ln", "Pine St", "Elm St", "Park Ave", "Lake Rd",
    ];

    static readonly string[] Notes =
    [
        "", "", "", "Met at the conference last spring.", "Prefers email over phone.",
        "Old college friend.", "Introduced by a mutual friend.", "Follow up about the proposal.",
    ];

    static readonly (string City, string Region, string Country)[] Cities =
    [
        ("Austin", "TX", "USA"),
        ("Portland", "OR", "USA"),
        ("Denver", "CO", "USA"),
        ("Toronto", "ON", "Canada"),
        ("London", "", "UK"),
        ("Berlin", "", "Germany"),
        ("Chicago", "IL", "USA"),
        ("Seattle", "WA", "USA"),
        ("Sydney", "NSW", "Australia"),
    ];

    static readonly (string Name, string Color)[] Tags =
    [
        ("Family", "red"),
        ("Friends", "amber"),
        ("Work", "sky"),
        ("Clients", "green"),
        ("Vendors", "violet"),
        ("Neighbors", "teal"),
    ];

    /// <summary>The Rust seeder's xorshift PRNG, bit for bit.</summary>
    sealed class Rng(ulong state)
    {
        public ulong Next()
        {
            state ^= state << 13;
            state ^= state >> 7;
            state ^= state << 17;
            return state;
        }
        public int Below(int n) => (int)(Next() % (ulong)n);
        public T Pick<T>(T[] items) => items[Below(items.Length)];
        public bool Chance(ulong percent) => Next() % 100 < percent;
    }

    public static void Run(Db db, string path, int count)
    {
        var existing = db.WriteBlocking(c => c.Scalar<long>("SELECT count(*) FROM contacts"));
        var rng = new Rng(0x9E3779B97F4A7C15UL ^ unchecked((ulong)existing * 0x2545F4914F6CDD1DUL));

        var started = Stopwatch.StartNew();
        db.WriteBlocking(tx =>
        {
            var tagIds = Tags.Select(t =>
            {
                tx.Run("INSERT OR IGNORE INTO tags (name, color) VALUES (?, ?)", t.Name, t.Color);
                return tx.Scalar<long>("SELECT id FROM tags WHERE name = ?", t.Name);
            }).ToArray();

            for (var i = existing; i < existing + count; i++)
            {
                var first = rng.Pick(FirstNames);
                var last = rng.Pick(LastNames);
                var handle = $"{first}.{last.Replace("'", "").Replace("ü", "")}{i}".ToLowerInvariant();
                var hasCompany = rng.Chance(70);
                var (city, region, country) = rng.Pick(Cities);

                var company = hasCompany ? rng.Pick(Companies) : "";
                var jobTitle = hasCompany ? rng.Pick(Titles) : "";
                string? birthday = rng.Chance(40) ? $"{1950 + rng.Below(55)}-{1 + rng.Below(12):D2}-{1 + rng.Below(28):D2}" : null;
                var notes = rng.Pick(Notes);
                var favorite = rng.Chance(5);
                var phone = $"+1 555-{rng.Below(1000):D3}-{rng.Below(10_000):D4}";

                List<LabeledValue> emails = [new("home", $"{handle}@example.com")];
                if (hasCompany && rng.Chance(50))
                    emails.Add(new("work", $"{handle}@{company.ToLowerInvariant().Replace(" ", "")}.com"));
                List<Address> addresses = [];
                if (rng.Chance(60))
                    addresses.Add(new("home", $"{1 + rng.Below(9999)} {rng.Pick(Streets)}", city, region, $"{rng.Below(100_000):D5}", country));
                var contactTags = tagIds.Where(_ => rng.Chance(12)).ToList();

                Repo.InsertContact(tx, new ValidContact(first, last, company, jobTitle, birthday, notes, favorite,
                    emails, [new("mobile", phone)], addresses, contactTags));
            }
            return 0;
        });
        // One big transaction leaves an equally big WAL; fold it in now.
        db.TruncateWal();

        var secs = started.Elapsed.TotalSeconds;
        Console.WriteLine($"Inserted {count} contacts into {path} in {secs * 1000:F1} ms ({count / secs:F0} contacts/sec, each with its emails, phones, addresses, tags and search index row)");
    }
}
