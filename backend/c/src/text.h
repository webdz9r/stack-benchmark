/* UTF-8 text helpers: Unicode-aware trimming, lowercasing, and the search tokenizer. */
#ifndef TEXT_H
#define TEXT_H

#include <stddef.h>
#include <stdint.h>

#include "json.h"

/* Decode one UTF-8 code point at s (n bytes left); returns bytes consumed (>= 1).
 * Invalid bytes decode as U+FFFD, one byte at a time. */
size_t utf8_decode(const char *s, size_t n, uint32_t *cp);
void utf8_encode(buf_t *b, uint32_t cp);
size_t utf8_count(const char *s);

/* Unicode White_Space property (what Rust's str::trim and char::is_whitespace use). */
int is_unicode_space(uint32_t cp);

/* A copy of s without leading/trailing Unicode whitespace (malloc'd). */
char *trim_dup(const char *s);
/* A lowercased copy (full Unicode, via towlower in a UTF-8 locale). */
char *lower_dup(const char *s);

/* Search word character: general category L*, M* or N*, or one of @ . ' (DB-12). */
int is_word_char(uint32_t cp);
/* Free text -> FTS5 expression (`jo smi` -> `"jo"* "smi"*`), or NULL if there
 * are no words. Caller frees. */
char *fts_query(const char *text);

#endif
