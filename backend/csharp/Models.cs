using System.Text.Json.Serialization;
using System.Text.RegularExpressions;

namespace AddressBook;

/// <summary>An error with an HTTP status; rendered as {"error": message}.</summary>
public sealed class AppError(int status, string message) : Exception(message)
{
    public int Status { get; } = status;
    public static AppError NotFound() => new(404, "not found");
    public static AppError Validation(string message) => new(422, message);
    public static AppError Conflict(string message) => new(409, message);
}

public record LabeledValue(string Label, string Value);

public record Address(string Label, string Street, string City, string Region, string PostalCode, string Country);

public record Tag(long Id, string Name, string Color);

public record TagWithCount(long Id, string Name, string Color, long ContactCount);

public record Contact(
    long Id, string FirstName, string LastName, string Company, string JobTitle, string? Birthday,
    string Notes, bool Favorite, List<LabeledValue> Emails, List<LabeledValue> Phones,
    List<Address> Addresses, List<Tag> Tags, string CreatedAt, string UpdatedAt);

public record ContactSummary(
    long Id, string FirstName, string LastName, string Company, string JobTitle, bool Favorite,
    string? Email, string? Phone, List<long> TagIds);

public record ContactPage(List<ContactSummary> Items, long Total, long Limit, long Offset);

public record LetterIndex(string Letter, long Offset, long Count);

public record Stats(long Contacts, long Favorites);

public record ErrorBody(string Error);

public record FavoriteBody(bool? Favorite);

public record ListQuery(string? Q, long? Tag, bool Favorite, long? Limit, long? Offset);

public class LabeledValueInput
{
    public string? Label { get; set; }
    public string? Value { get; set; }
}

public class AddressInput
{
    public string? Label { get; set; }
    public string? Street { get; set; }
    public string? City { get; set; }
    public string? Region { get; set; }
    public string? PostalCode { get; set; }
    public string? Country { get; set; }
}

/// <summary>Body for creating or replacing a contact.</summary>
public class ContactInput
{
    public string? FirstName { get; set; }
    public string? LastName { get; set; }
    public string? Company { get; set; }
    public string? JobTitle { get; set; }
    public string? Birthday { get; set; }
    public string? Notes { get; set; }
    public bool Favorite { get; set; }
    public List<LabeledValueInput>? Emails { get; set; }
    public List<LabeledValueInput>? Phones { get; set; }
    public List<AddressInput>? Addresses { get; set; }
    public List<long>? TagIds { get; set; }
}

/// <summary>A contact input after validation: trimmed, empty rows dropped.</summary>
public record ValidContact(
    string FirstName, string LastName, string Company, string JobTitle, string? Birthday, string Notes,
    bool Favorite, List<LabeledValue> Emails, List<LabeledValue> Phones, List<Address> Addresses, List<long> TagIds);

public class TagInput
{
    public string? Name { get; set; }
    public string? Color { get; set; }
}

public static partial class Validate
{
    public static readonly string[] TagColors = ["slate", "red", "orange", "amber", "green", "teal", "sky", "indigo", "violet", "pink"];

    [GeneratedRegex(@"^(\d{4})-(\d{2})-(\d{2})$")]
    private static partial Regex IsoDate();

    /// <summary>Same rules as the Rust backend.</summary>
    public static ValidContact Contact(ContactInput? c)
    {
        if (c is null) throw AppError.Validation("expected a JSON object");
        string first = Trim(c.FirstName), last = Trim(c.LastName), company = Trim(c.Company);
        if (first == "" && last == "" && company == "") throw AppError.Validation("a name or company is required");

        var birthday = Trim(c.Birthday);
        if (birthday != "")
        {
            var m = IsoDate().Match(birthday);
            if (!m.Success || int.Parse(m.Groups[2].Value) is < 1 or > 12 || int.Parse(m.Groups[3].Value) is < 1 or > 31)
                throw AppError.Validation("birthday must be YYYY-MM-DD");
        }

        var emails = Labeled(c.Emails);
        var phones = Labeled(c.Phones);
        foreach (var e in emails)
        {
            var at = e.Value.IndexOf('@');
            if (at <= 0 || !e.Value[(at + 1)..].Contains('.') || e.Value.Any(char.IsWhiteSpace))
                throw AppError.Validation($"'{e.Value}' is not a valid email");
        }

        var addresses = (c.Addresses ?? [])
            .Select(a => new Address(Label(a.Label), Trim(a.Street), Trim(a.City), Trim(a.Region), Trim(a.PostalCode), Trim(a.Country)))
            .Where(a => a.Street != "" || a.City != "" || a.Region != "" || a.PostalCode != "" || a.Country != "")
            .ToList();

        return new ValidContact(first, last, company, Trim(c.JobTitle), birthday == "" ? null : birthday, Trim(c.Notes),
            c.Favorite, emails, phones, addresses, (c.TagIds ?? []).Distinct().Order().ToList());
    }

    public static (string Name, string? Color) Tag(TagInput? t)
    {
        var name = Trim(t?.Name);
        if (name == "") throw AppError.Validation("tag name is required");
        if (name.EnumerateRunes().Count() > 40) throw AppError.Validation("tag name must be 40 characters or fewer");
        if (t!.Color is { } color && !TagColors.Contains(color)) throw AppError.Validation($"unknown tag color '{color}'");
        return (name, t.Color);
    }

    static List<LabeledValue> Labeled(List<LabeledValueInput>? rows) =>
        (rows ?? []).Select(r => new LabeledValue(Label(r.Label), Trim(r.Value))).Where(r => r.Value != "").ToList();

    static string Label(string? label) => Trim(label).ToLowerInvariant() is { Length: > 0 } l ? l : "other";

    static string Trim(string? s) => s?.Trim() ?? "";
}

/// <summary>Compile-time JSON serialization (snake_case, like the other backends).</summary>
[JsonSourceGenerationOptions(PropertyNamingPolicy = JsonKnownNamingPolicy.SnakeCaseLower)]
[JsonSerializable(typeof(Contact))]
[JsonSerializable(typeof(ContactPage))]
[JsonSerializable(typeof(List<LetterIndex>))]
[JsonSerializable(typeof(List<TagWithCount>))]
[JsonSerializable(typeof(Tag))]
[JsonSerializable(typeof(Stats))]
[JsonSerializable(typeof(ErrorBody))]
[JsonSerializable(typeof(ContactInput))]
[JsonSerializable(typeof(TagInput))]
[JsonSerializable(typeof(FavoriteBody))]
public partial class AppJson : JsonSerializerContext;
