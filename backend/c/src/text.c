#include "text.h"

#include <stdlib.h>
#include <string.h>
#include <wctype.h>

#include "unicode_table.h"

size_t utf8_decode(const char *str, size_t n, uint32_t *cp) {
    const unsigned char *s = (const unsigned char *)str;
    if (n == 0) { *cp = 0; return 0; }
    unsigned char c = s[0];
    size_t len;
    uint32_t v;
    if (c < 0x80) { *cp = c; return 1; }
    else if ((c & 0xE0) == 0xC0) { len = 2; v = c & 0x1F; }
    else if ((c & 0xF0) == 0xE0) { len = 3; v = c & 0x0F; }
    else if ((c & 0xF8) == 0xF0) { len = 4; v = c & 0x07; }
    else { *cp = 0xFFFD; return 1; }
    if (len > n) { *cp = 0xFFFD; return 1; }
    for (size_t i = 1; i < len; i++) {
        if ((s[i] & 0xC0) != 0x80) { *cp = 0xFFFD; return 1; }
        v = (v << 6) | (s[i] & 0x3F);
    }
    *cp = v;
    return len;
}

void utf8_encode(buf_t *b, uint32_t cp) {
    char out[4];
    size_t n;
    if (cp < 0x80) { out[0] = (char)cp; n = 1; }
    else if (cp < 0x800) { out[0] = (char)(0xC0 | (cp >> 6)); out[1] = (char)(0x80 | (cp & 0x3F)); n = 2; }
    else if (cp < 0x10000) {
        out[0] = (char)(0xE0 | (cp >> 12)); out[1] = (char)(0x80 | ((cp >> 6) & 0x3F));
        out[2] = (char)(0x80 | (cp & 0x3F)); n = 3;
    } else {
        out[0] = (char)(0xF0 | (cp >> 18)); out[1] = (char)(0x80 | ((cp >> 12) & 0x3F));
        out[2] = (char)(0x80 | ((cp >> 6) & 0x3F)); out[3] = (char)(0x80 | (cp & 0x3F)); n = 4;
    }
    buf_put(b, out, n);
}

size_t utf8_count(const char *s) {
    size_t count = 0, n = strlen(s);
    uint32_t cp;
    while (n) {
        size_t k = utf8_decode(s, n, &cp);
        s += k;
        n -= k;
        count++;
    }
    return count;
}

int is_unicode_space(uint32_t cp) {
    return (cp >= 0x09 && cp <= 0x0D) || cp == 0x20 || cp == 0x85 || cp == 0xA0 || cp == 0x1680 ||
           (cp >= 0x2000 && cp <= 0x200A) || cp == 0x2028 || cp == 0x2029 || cp == 0x202F || cp == 0x205F ||
           cp == 0x3000;
}

char *trim_dup(const char *s) {
    size_t n = strlen(s), start = 0, end = 0, i = 0;
    int seen = 0;
    uint32_t cp;
    while (i < n) {
        size_t k = utf8_decode(s + i, n - i, &cp);
        if (!is_unicode_space(cp)) {
            if (!seen) { start = i; seen = 1; }
            end = i + k;
        }
        i += k;
    }
    size_t len = seen ? end - start : 0;
    char *out = malloc(len + 1);
    memcpy(out, s + start, len);
    out[len] = '\0';
    return out;
}

char *lower_dup(const char *s) {
    buf_t b = {0};
    size_t n = strlen(s);
    uint32_t cp;
    while (n) {
        size_t k = utf8_decode(s, n, &cp);
        utf8_encode(&b, cp < 0x80 ? (uint32_t)((cp >= 'A' && cp <= 'Z') ? cp + 32 : cp) : (uint32_t)towlower((wint_t)cp));
        s += k;
        n -= k;
    }
    size_t len;
    return buf_take(&b, &len);
}

int is_word_char(uint32_t cp) {
    if (cp == '@' || cp == '.' || cp == '\'') return 1;
    size_t lo = 0, hi = sizeof WORD_RANGES / sizeof WORD_RANGES[0];
    while (lo < hi) {
        size_t mid = (lo + hi) / 2;
        if (cp < WORD_RANGES[mid][0]) hi = mid;
        else if (cp > WORD_RANGES[mid][1]) lo = mid + 1;
        else return 1;
    }
    return 0;
}

char *fts_query(const char *text) {
    if (!text || !*text) return NULL;
    buf_t out = {0};
    size_t n = strlen(text), i = 0;
    int in_word = 0, terms = 0;
    uint32_t cp;
    while (i < n) {
        size_t k = utf8_decode(text + i, n - i, &cp);
        if (is_word_char(cp)) {
            if (!in_word) {
                if (terms++) buf_putc(&out, ' ');
                buf_putc(&out, '"');
                in_word = 1;
            }
            buf_put(&out, text + i, k); /* word chars never include '"', so no escaping needed */
        } else if (in_word) {
            buf_puts(&out, "\"*");
            in_word = 0;
        }
        i += k;
    }
    if (in_word) buf_puts(&out, "\"*");
    if (!terms) {
        buf_free(&out);
        return NULL;
    }
    size_t len;
    return buf_take(&out, &len);
}
