package addressbook;

import java.util.List;

/**
 * API types (03-api.md §2). Components are declared in the reference field order and
 * serialized in snake_case by {@link Json}.
 */
public final class Models {
    private Models() {
    }

    public record Tag(long id, String name, String color) {
    }

    public record TagWithCount(long id, String name, String color, long contactCount) {
    }

    public record LabeledValue(String label, String value) {
    }

    public record Address(String label, String street, String city, String region, String postalCode,
                          String country) {
    }

    public record Contact(long id, String firstName, String lastName, String company, String jobTitle,
                          String birthday, String notes, boolean favorite, List<LabeledValue> emails,
                          List<LabeledValue> phones, List<Address> addresses, List<Tag> tags,
                          String createdAt, String updatedAt) {
    }

    public record ContactSummary(long id, String firstName, String lastName, String company, String jobTitle,
                                 boolean favorite, String email, String phone, long[] tagIds) {
    }

    public record ContactPage(List<ContactSummary> items, long total, long limit, long offset) {
    }

    public record LetterIndex(String letter, long offset, long count) {
    }

    public record Stats(long contacts, long favorites) {
    }

    public record ErrorBody(String error) {
    }

    /** A validated contact body (03-api.md §4), ready to insert. */
    public record ContactInput(String firstName, String lastName, String company, String jobTitle,
                               String birthday, String notes, boolean favorite, List<LabeledValue> emails,
                               List<LabeledValue> phones, List<Address> addresses, long[] tagIds) {
    }

    /** A validated tag body (03-api.md §5); color is null when it was left out. */
    public record TagInput(String name, String color) {
    }

    /** The list and letter filters (02-database.md §7.1). fts is null when there is no search. */
    public record Filter(String fts, Long tag, boolean favorite) {
        public String key() {
            return (fts == null ? "" : fts) + "|" + (tag == null ? "none" : tag) + "|" + favorite;
        }

        public boolean isFiltered() {
            return fts != null || tag != null || favorite;
        }
    }

    /** An error with its HTTP status and the exact client message (03-api.md §6). */
    public static final class ApiException extends RuntimeException {
        private final int status;

        public ApiException(int status, String message) {
            super(message, null, false, false);
            this.status = status;
        }

        public int status() {
            return status;
        }

        public static ApiException notFound() {
            return new ApiException(404, "not found");
        }

        public static ApiException invalid(String message) {
            return new ApiException(422, message);
        }

        public static ApiException badRequest(String message) {
            return new ApiException(400, message);
        }
    }
}
