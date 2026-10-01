package addressbook;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Locale;
import java.util.Set;

import addressbook.Models.Address;
import addressbook.Models.ApiException;
import addressbook.Models.ContactInput;
import addressbook.Models.LabeledValue;
import addressbook.Models.TagInput;

import tools.jackson.databind.JsonNode;

/**
 * Request body parsing and validation (03-api.md §4-5, §7), and the search
 * expression builder (02-database.md §6.2). Types are checked strictly: no
 * coercion of "yes", 1 or "3".
 */
public final class Inputs {
    private Inputs() {
    }

    private static final Set<String> COLORS =
        Set.of("slate", "red", "orange", "amber", "green", "teal", "sky", "indigo", "violet", "pink");

    // ------------------------------------------------------------------ contact

    public static ContactInput contact(JsonNode root) {
        JsonNode obj = object(root, "body");
        String first = trim(string(obj, "first_name"));                       // V1
        String last = trim(string(obj, "last_name"));
        String company = trim(string(obj, "company"));
        String jobTitle = trim(string(obj, "job_title"));
        String notes = trim(string(obj, "notes"));
        String birthday = optString(obj, "birthday");
        boolean favorite = bool(obj, "favorite", false);
        List<JsonNode> emailRows = array(obj, "emails");
        List<JsonNode> phoneRows = array(obj, "phones");
        List<JsonNode> addressRows = array(obj, "addresses");
        List<JsonNode> tagNodes = array(obj, "tag_ids");
        long[] tagIds = new long[tagNodes.size()];
        for (int i = 0; i < tagIds.length; i++) {
            JsonNode n = tagNodes.get(i);
            if (!n.isIntegralNumber() || !n.canConvertToLong()) {
                throw ApiException.invalid("tag_ids must be integers");
            }
            tagIds[i] = n.longValue();
        }

        if (first.isEmpty() && last.isEmpty() && company.isEmpty()) {           // V2
            throw ApiException.invalid("a name or company is required");
        }
        if (birthday != null) {                                                  // V3
            birthday = trim(birthday);
            if (birthday.isEmpty()) {
                birthday = null;
            }
        }
        if (birthday != null && !validBirthday(birthday)) {                     // V4
            throw ApiException.invalid("birthday must be YYYY-MM-DD");
        }
        List<LabeledValue> emails = labeledRows(emailRows, "emails");           // V5
        List<LabeledValue> phones = labeledRows(phoneRows, "phones");
        for (LabeledValue e : emails) {                                         // V6
            if (!validEmail(e.value())) {
                throw ApiException.invalid("'" + e.value() + "' is not a valid email");
            }
        }
        List<Address> addresses = new ArrayList<>(addressRows.size());          // V7
        for (JsonNode row : addressRows) {
            JsonNode a = object(row, "addresses");
            String street = trim(rowString(a, "street"));
            String city = trim(rowString(a, "city"));
            String region = trim(rowString(a, "region"));
            String postal = trim(rowString(a, "postal_code"));
            String country = trim(rowString(a, "country"));
            if (street.isEmpty() && city.isEmpty() && region.isEmpty() && postal.isEmpty() && country.isEmpty()) {
                continue;
            }
            addresses.add(new Address(label(rowString(a, "label")), street, city, region, postal, country));
        }
        long[] sorted = Arrays.stream(tagIds).sorted().distinct().toArray();      // V8

        return new ContactInput(first, last, company, jobTitle, birthday, notes, favorite, emails, phones,
            addresses, sorted);
    }

    private static List<LabeledValue> labeledRows(List<JsonNode> rows, String field) {
        List<LabeledValue> out = new ArrayList<>(rows.size());
        for (JsonNode row : rows) {
            JsonNode r = object(row, field);
            String value = trim(rowString(r, "value")); // API-U1: a missing value is empty
            if (value.isEmpty()) {
                continue;
            }
            out.add(new LabeledValue(label(rowString(r, "label")), value));
        }
        return out;
    }

    private static String label(String raw) {
        String l = trim(raw).toLowerCase(Locale.ROOT);
        return l.isEmpty() ? "other" : l;
    }

    static boolean validBirthday(String s) {
        String[] parts = s.split("-", -1);
        if (parts.length != 3 || parts[0].length() != 4 || parts[1].length() != 2 || parts[2].length() != 2) {
            return false;
        }
        for (String p : parts) {
            for (int i = 0; i < p.length(); i++) {
                char ch = p.charAt(i);
                if (ch < '0' || ch > '9') {
                    return false;
                }
            }
        }
        int month = Integer.parseInt(parts[1]);
        int day = Integer.parseInt(parts[2]);
        return month >= 1 && month <= 12 && day >= 1 && day <= 31;
    }

    static boolean validEmail(String s) {
        int at = s.indexOf('@');
        if (at <= 0 || s.indexOf('.', at + 1) < 0) {
            return false;
        }
        for (int i = 0; i < s.length(); ) {
            int cp = s.codePointAt(i);
            if (isWhiteSpace(cp)) {
                return false;
            }
            i += Character.charCount(cp);
        }
        return true;
    }

    // ------------------------------------------------------------------ tag and favorite

    public static TagInput tag(JsonNode root) {
        JsonNode obj = object(root, "body");
        String name = trim(string(obj, "name"));
        String color = optString(obj, "color");
        if (name.isEmpty()) {                                                    // T1
            throw ApiException.invalid("tag name is required");
        }
        if (name.codePointCount(0, name.length()) > 40) {                       // T2
            throw ApiException.invalid("tag name must be 40 characters or fewer");
        }
        if (color != null && !COLORS.contains(color)) {                         // T3
            throw ApiException.invalid("unknown tag color '" + color + "'");
        }
        return new TagInput(name, color);
    }

    public static boolean favorite(JsonNode root) {
        JsonNode v = object(root, "body").get("favorite");
        if (v == null || v.isNull()) {
            throw ApiException.invalid("missing field `favorite`");
        }
        if (!v.isBoolean()) {
            throw ApiException.invalid("favorite must be a boolean");
        }
        return v.booleanValue();
    }

    // ------------------------------------------------------------------ strict JSON access

    private static JsonNode object(JsonNode n, String what) {
        if (n == null || !n.isObject()) {
            throw ApiException.invalid(what + " must be a JSON object");
        }
        return n;
    }

    /** A top-level string field: missing means "", anything but a string is an error. */
    private static String string(JsonNode obj, String field) {
        JsonNode v = obj.get(field);
        if (v == null) {
            return "";
        }
        if (!v.isString()) {
            throw ApiException.invalid(field + " must be a string");
        }
        return v.stringValue();
    }

    /** A string inside a child row: missing or null means "". */
    private static String rowString(JsonNode obj, String field) {
        JsonNode v = obj.get(field);
        if (v == null || v.isNull()) {
            return "";
        }
        if (!v.isString()) {
            throw ApiException.invalid(field + " must be a string");
        }
        return v.stringValue();
    }

    /** A string that may be missing or null. */
    private static String optString(JsonNode obj, String field) {
        JsonNode v = obj.get(field);
        if (v == null || v.isNull()) {
            return null;
        }
        if (!v.isString()) {
            throw ApiException.invalid(field + " must be a string");
        }
        return v.stringValue();
    }

    private static boolean bool(JsonNode obj, String field, boolean dflt) {
        JsonNode v = obj.get(field);
        if (v == null) {
            return dflt;
        }
        if (!v.isBoolean()) {
            throw ApiException.invalid(field + " must be a boolean");
        }
        return v.booleanValue();
    }

    private static List<JsonNode> array(JsonNode obj, String field) {
        JsonNode v = obj.get(field);
        if (v == null) {
            return List.of();
        }
        if (!v.isArray()) {
            throw ApiException.invalid(field + " must be an array");
        }
        List<JsonNode> out = new ArrayList<>(v.size());
        for (JsonNode e : v) {
            out.add(e);
        }
        return out;
    }

    // ------------------------------------------------------------------ text helpers

    /**
     * Unicode White_Space, the set Rust's str::trim uses. Java's strip() differs: it
     * keeps U+00A0, U+2007 and U+202F, and removes U+001C..U+001F.
     */
    static boolean isWhiteSpace(int cp) {
        return (cp >= 0x09 && cp <= 0x0D) || cp == 0x20 || cp == 0x85 || cp == 0xA0 || cp == 0x1680
            || (cp >= 0x2000 && cp <= 0x200A) || cp == 0x2028 || cp == 0x2029 || cp == 0x202F
            || cp == 0x205F || cp == 0x3000;
    }

    static String trim(String s) {
        int start = 0;
        int end = s.length();
        while (start < end) {
            int cp = s.codePointAt(start);
            if (!isWhiteSpace(cp)) {
                break;
            }
            start += Character.charCount(cp);
        }
        while (end > start) {
            int cp = s.codePointBefore(end);
            if (!isWhiteSpace(cp)) {
                break;
            }
            end -= Character.charCount(cp);
        }
        return start == 0 && end == s.length() ? s : s.substring(start, end);
    }

    /** DB-12: Unicode Letters, Marks and Numbers, per code point, plus '@', '.' and '\''. */
    static boolean isWordChar(int cp) {
        if (cp == '@' || cp == '.' || cp == '\'') {
            return true;
        }
        return switch (Character.getType(cp)) {
            case Character.UPPERCASE_LETTER, Character.LOWERCASE_LETTER, Character.TITLECASE_LETTER,
                 Character.MODIFIER_LETTER, Character.OTHER_LETTER,
                 Character.NON_SPACING_MARK, Character.ENCLOSING_MARK, Character.COMBINING_SPACING_MARK,
                 Character.DECIMAL_DIGIT_NUMBER, Character.LETTER_NUMBER, Character.OTHER_NUMBER -> true;
            default -> false;
        };
    }

    /** fts_query (02-database.md §6.2); null means no search filter. */
    public static String ftsQuery(String input) {
        if (input == null) {
            return null;
        }
        StringBuilder out = new StringBuilder();
        int i = 0;
        int n = input.length();
        while (i < n) {
            int cp = input.codePointAt(i);
            if (!isWordChar(cp)) {
                i += Character.charCount(cp);
                continue;
            }
            int start = i;
            while (i < n) {
                cp = input.codePointAt(i);
                if (!isWordChar(cp)) {
                    break;
                }
                i += Character.charCount(cp);
            }
            if (!out.isEmpty()) {
                out.append(' ');
            }
            out.append('"').append(input, start, i).append("\"*");
        }
        return out.isEmpty() ? null : out.toString();
    }
}
