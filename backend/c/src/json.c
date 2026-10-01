#include "json.h"

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

void buf_reserve(buf_t *b, size_t extra) {
    if (b->len + extra + 1 <= b->cap) return;
    size_t cap = b->cap ? b->cap : 256;
    while (cap < b->len + extra + 1) cap *= 2;
    char *p = realloc(b->data, cap);
    if (!p) abort();
    b->data = p;
    b->cap = cap;
}

void buf_put(buf_t *b, const char *s, size_t n) {
    buf_reserve(b, n);
    memcpy(b->data + b->len, s, n);
    b->len += n;
    b->data[b->len] = '\0';
}

void buf_puts(buf_t *b, const char *s) { buf_put(b, s, strlen(s)); }

void buf_putc(buf_t *b, char c) { buf_put(b, &c, 1); }

void buf_printf(buf_t *b, const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    char small[256];
    int n = vsnprintf(small, sizeof small, fmt, ap);
    va_end(ap);
    if (n < (int)sizeof small) {
        buf_put(b, small, (size_t)n);
        return;
    }
    buf_reserve(b, (size_t)n);
    va_start(ap, fmt);
    vsnprintf(b->data + b->len, (size_t)n + 1, fmt, ap);
    va_end(ap);
    b->len += (size_t)n;
}

void buf_free(buf_t *b) {
    free(b->data);
    b->data = NULL;
    b->len = b->cap = 0;
}

char *buf_take(buf_t *b, size_t *len) {
    if (!b->data) buf_reserve(b, 0);
    char *p = b->data;
    *len = b->len;
    b->data = NULL;
    b->len = b->cap = 0;
    return p;
}

void json_str(buf_t *b, const char *s) {
    buf_putc(b, '"');
    const char *run = s;
    for (const unsigned char *p = (const unsigned char *)s; *p; p++) {
        const char *esc = NULL;
        char tmp[8];
        switch (*p) {
            case '"': esc = "\\\""; break;
            case '\\': esc = "\\\\"; break;
            case '\n': esc = "\\n"; break;
            case '\r': esc = "\\r"; break;
            case '\t': esc = "\\t"; break;
            case '\b': esc = "\\b"; break;
            case '\f': esc = "\\f"; break;
            default:
                if (*p < 0x20) {
                    snprintf(tmp, sizeof tmp, "\\u%04x", *p);
                    esc = tmp;
                }
        }
        if (esc) {
            buf_put(b, run, (size_t)((const char *)p - run));
            buf_puts(b, esc);
            run = (const char *)p + 1;
        }
    }
    buf_puts(b, run);
    buf_putc(b, '"');
}

void json_str_or_null(buf_t *b, const char *s) {
    if (s) json_str(b, s);
    else buf_puts(b, "null");
}

void json_int(buf_t *b, int64_t v) { buf_printf(b, "%lld", (long long)v); }

void json_bool(buf_t *b, int v) { buf_puts(b, v ? "true" : "false"); }

void json_key(buf_t *b, const char *key) {
    buf_putc(b, '"');
    buf_puts(b, key);
    buf_puts(b, "\":");
}
