package addressbook;

import tools.jackson.databind.JsonNode;
import tools.jackson.databind.MapperFeature;
import tools.jackson.databind.PropertyNamingStrategies;
import tools.jackson.databind.json.JsonMapper;

/** Compact snake_case JSON in declaration order (03-api.md §2). */
public final class Json {
    private Json() {
    }

    private static final JsonMapper MAPPER = JsonMapper.builder()
        .propertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE)
        .disable(MapperFeature.SORT_PROPERTIES_ALPHABETICALLY)
        .build();

    public static byte[] write(Object value) {
        return MAPPER.writeValueAsBytes(value);
    }

    /** Parses a request body; a syntax error or an empty body is a 400. */
    public static JsonNode read(byte[] body) {
        if (body == null || body.length == 0) {
            throw Models.ApiException.badRequest("request body is not valid JSON");
        }
        try {
            return MAPPER.readTree(body);
        } catch (tools.jackson.core.JacksonException e) {
            throw Models.ApiException.badRequest("request body is not valid JSON");
        }
    }
}
