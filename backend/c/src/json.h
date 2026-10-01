/* Growable byte buffer and a compact JSON writer. */
#ifndef JSON_H
#define JSON_H

#include <stddef.h>
#include <stdint.h>

typedef struct {
    char *data;
    size_t len, cap;
} buf_t;

void buf_reserve(buf_t *b, size_t extra);
void buf_put(buf_t *b, const char *s, size_t n);
void buf_puts(buf_t *b, const char *s);
void buf_putc(buf_t *b, char c);
void buf_printf(buf_t *b, const char *fmt, ...) __attribute__((format(printf, 2, 3)));
void buf_free(buf_t *b);
/* Take ownership of the bytes; the buffer is left empty. */
char *buf_take(buf_t *b, size_t *len);

/* JSON values. Strings are escaped like serde_json: \" \\ \n \r \t \b \f, other
 * control characters as \u00XX, everything else (including UTF-8) as is. */
void json_str(buf_t *b, const char *s);
void json_str_or_null(buf_t *b, const char *s);
void json_int(buf_t *b, int64_t v);
void json_bool(buf_t *b, int v);
/* "key": — the key is a trusted literal, written without escaping. */
void json_key(buf_t *b, const char *key);

#endif
