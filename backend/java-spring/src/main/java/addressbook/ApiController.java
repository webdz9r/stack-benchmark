package addressbook;

import java.sql.SQLException;
import java.util.function.Supplier;

import jakarta.servlet.http.HttpServletRequest;

import addressbook.Db.SqlFn;
import addressbook.Models.ApiException;
import addressbook.Models.Contact;
import addressbook.Models.ContactInput;
import addressbook.Models.Filter;
import addressbook.Models.Tag;
import addressbook.Models.TagInput;

import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** The 13 routes of 03-api.md. Every JSON body is built as bytes, so a cache hit serializes nothing. */
@RestController
@RequestMapping("/api")
public class ApiController {
    private static final long MAX_STALENESS_NANOS = 1_000_000_000L;

    private final Db db;
    private final ResponseCache cache;
    private volatile long publishedGeneration;
    private volatile long publishedAt = System.nanoTime() - MAX_STALENESS_NANOS;

    public ApiController(Db db, ResponseCache cache) {
        this.db = db;
        this.cache = cache;
    }

    // ------------------------------------------------------------------ reads

    @GetMapping(value = "/health", produces = "text/plain;charset=utf-8")
    public String health() {
        return "ok";
    }

    @GetMapping("/stats")
    public ResponseEntity<byte[]> stats(HttpServletRequest req) {
        return cached(req, "stats", () -> Json.write(read(Store::stats)));
    }

    @GetMapping("/contacts")
    public ResponseEntity<byte[]> list(HttpServletRequest req,
                                       @RequestParam(required = false) String q,
                                       @RequestParam(required = false) String tag,
                                       @RequestParam(required = false) String favorite,
                                       @RequestParam(required = false) String limit,
                                       @RequestParam(required = false) String offset) {
        Filter f = filter(q, tag, favorite);
        long lim = Math.clamp(parseLong(limit, 50, "limit"), 1, 200);
        long off = Math.max(0, parseLong(offset, 0, "offset"));
        Supplier<byte[]> page = () -> Json.write(read(c -> Store.listPage(c, f, lim, off)));
        if (!f.isFiltered()) {
            return json(HttpStatus.OK, page.get()); // unfiltered pages aren't cached (CACHE-4)
        }
        String key = "list|" + f.key() + "|" + (limit == null ? "" : limit) + "|" + (offset == null ? "" : offset);
        return cached(req, key, page);
    }

    @GetMapping("/contacts/letters")
    public ResponseEntity<byte[]> letters(HttpServletRequest req,
                                          @RequestParam(required = false) String q,
                                          @RequestParam(required = false) String tag,
                                          @RequestParam(required = false) String favorite) {
        Filter f = filter(q, tag, favorite);
        return cached(req, "letters|" + f.key(), () -> Json.write(read(c -> Store.letters(c, f))));
    }

    @GetMapping("/contacts/{id}")
    public ResponseEntity<byte[]> contact(@PathVariable long id) {
        Contact contact = read(c -> Store.getContact(c, id));
        if (contact == null) {
            throw ApiException.notFound();
        }
        return json(HttpStatus.OK, Json.write(contact));
    }

    @GetMapping("/tags")
    public ResponseEntity<byte[]> tags(HttpServletRequest req) {
        return cached(req, "tags", () -> Json.write(read(Store::listTags)));
    }

    // ------------------------------------------------------------------ contact writes

    @PostMapping("/contacts")
    public ResponseEntity<byte[]> create(@RequestBody(required = false) byte[] body) {
        ContactInput in = Inputs.contact(Json.read(body));
        Contact created = write(c -> c.transaction(tx -> Store.getContact(tx, Store.insertContact(tx, in))));
        return json(HttpStatus.CREATED, Json.write(created));
    }

    @PutMapping("/contacts/{id}")
    public ResponseEntity<byte[]> replace(@PathVariable long id, @RequestBody(required = false) byte[] body) {
        ContactInput in = Inputs.contact(Json.read(body)); // validate first, then 404 (API-C1)
        Contact updated = write(c -> c.transaction(tx -> Store.replaceContact(tx, id, in)
            ? Store.getContact(tx, id) : null));
        if (updated == null) {
            throw ApiException.notFound();
        }
        return json(HttpStatus.OK, Json.write(updated));
    }

    @DeleteMapping("/contacts/{id}")
    public ResponseEntity<byte[]> delete(@PathVariable long id) {
        if (!write(c -> c.transaction(tx -> Store.deleteContact(tx, id)))) {
            throw ApiException.notFound();
        }
        return ResponseEntity.noContent().build();
    }

    @PutMapping("/contacts/{id}/favorite")
    public ResponseEntity<byte[]> favorite(@PathVariable long id, @RequestBody(required = false) byte[] body) {
        boolean fav = Inputs.favorite(Json.read(body));
        if (!write(c -> Store.setFavorite(c, id, fav))) {
            throw ApiException.notFound();
        }
        return ResponseEntity.noContent().build();
    }

    // ------------------------------------------------------------------ tag writes

    @PostMapping("/tags")
    public ResponseEntity<byte[]> createTag(@RequestBody(required = false) byte[] body) {
        TagInput in = Inputs.tag(Json.read(body));
        Tag tag = write(c -> Store.createTag(c, in));
        return json(HttpStatus.CREATED, Json.write(tag));
    }

    @PutMapping("/tags/{id}")
    public ResponseEntity<byte[]> updateTag(@PathVariable long id, @RequestBody(required = false) byte[] body) {
        TagInput in = Inputs.tag(Json.read(body));
        Tag tag = write(c -> Store.updateTag(c, id, in));
        if (tag == null) {
            throw ApiException.notFound();
        }
        return json(HttpStatus.OK, Json.write(tag));
    }

    @DeleteMapping("/tags/{id}")
    public ResponseEntity<byte[]> deleteTag(@PathVariable long id) {
        if (!write(c -> Store.deleteTag(c, id))) {
            throw ApiException.notFound();
        }
        return ResponseEntity.noContent().build();
    }

    /** Any other /api path or method: JSON 404 (ARCH-18), never the SPA. */
    @RequestMapping("/**")
    public ResponseEntity<byte[]> unknown() {
        throw ApiException.notFound();
    }

    // ------------------------------------------------------------------ helpers

    private static Filter filter(String q, String tag, String favorite) {
        Long tagId = tag == null ? null : parseLong(tag, 0, "tag");
        boolean fav = false;
        if (favorite != null) {
            fav = switch (favorite) {
                case "true" -> true;
                case "false" -> false;
                default -> throw ApiException.badRequest("favorite must be true or false");
            };
        }
        return new Filter(Inputs.ftsQuery(q), tagId, fav);
    }

    private static long parseLong(String raw, long dflt, String name) {
        if (raw == null) {
            return dflt;
        }
        try {
            return Long.parseLong(raw);
        } catch (NumberFormatException e) {
            throw ApiException.badRequest(name + " must be an integer");
        }
    }

    /** CACHE-11: the key generation is read before the query runs. */
    private long keyGeneration(HttpServletRequest req) {
        if (req.getHeader("X-Fresh") != null) {
            return db.generation(); // read-your-writes (CACHE-12)
        }
        long now = System.nanoTime();
        if (now - publishedAt >= MAX_STALENESS_NANOS) {
            publishedGeneration = db.generation(); // racing refreshes are harmless
            publishedAt = now;
        }
        return publishedGeneration;
    }

    private ResponseEntity<byte[]> cached(HttpServletRequest req, String key, Supplier<byte[]> compute) {
        byte[] body = cache.get(keyGeneration(req), key, compute);
        String etag = etag(body);
        if (matches(req.getHeader(HttpHeaders.IF_NONE_MATCH), etag)) {
            return ResponseEntity.status(HttpStatus.NOT_MODIFIED)
                .header(HttpHeaders.ETAG, etag)
                .header(HttpHeaders.CACHE_CONTROL, "no-cache")
                .build();
        }
        return ResponseEntity.ok()
            .contentType(MediaType.APPLICATION_JSON)
            .header(HttpHeaders.ETAG, etag)
            .header(HttpHeaders.CACHE_CONTROL, "no-cache")
            .body(body);
    }

    static ResponseEntity<byte[]> json(HttpStatus status, byte[] body) {
        return ResponseEntity.status(status).contentType(MediaType.APPLICATION_JSON).body(body);
    }

    /** CACHE-13: a quoted 64-bit FNV-1a hash of the body. */
    static String etag(byte[] body) {
        long h = 0xcbf29ce484222325L;
        for (byte b : body) {
            h ^= b & 0xff;
            h *= 0x100000001b3L;
        }
        return "\"" + String.format("%016x", h) + "\"";
    }

    /** CACHE-14: comma-separated tokens, W/ stripped, "*" matches anything. */
    static boolean matches(String ifNoneMatch, String etag) {
        if (ifNoneMatch == null) {
            return false;
        }
        for (String token : ifNoneMatch.split(",")) {
            String t = token.trim();
            if (t.startsWith("W/")) {
                t = t.substring(2);
            }
            if (t.equals("*") || t.equals(etag)) {
                return true;
            }
        }
        return false;
    }

    private <T> T read(SqlFn<T> fn) {
        try {
            return db.read(fn);
        } catch (SQLException e) {
            throw new DatabaseException(e);
        }
    }

    private <T> T write(SqlFn<T> fn) {
        try {
            return db.write(fn);
        } catch (SQLException e) {
            throw new DatabaseException(e);
        }
    }

    /** An unexpected SQLite error; ErrorAdvice maps constraints to 409 and the rest to 500. */
    static final class DatabaseException extends RuntimeException {
        DatabaseException(SQLException cause) {
            super(cause.getMessage(), cause);
        }
    }
}
