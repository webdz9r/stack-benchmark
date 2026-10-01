/* Request bodies and their validation (docs/requirements/03-api.md §4, §5). */
#ifndef VALIDATE_H
#define VALIDATE_H

#include <stddef.h>
#include <stdint.h>

#include "db.h"

typedef struct {
    char *label, *value;
} labeled_t;

typedef struct {
    char *label, *street, *city, *region, *postal_code, *country;
} address_t;

/* A validated contact: trimmed, empty rows dropped, labels normalized,
 * tag ids sorted and unique. Every string is malloc'd; free with contact_free. */
typedef struct {
    char *first_name, *last_name, *company, *job_title, *notes;
    char *birthday; /* NULL when absent */
    int favorite;
    labeled_t *emails;
    size_t n_emails;
    labeled_t *phones;
    size_t n_phones;
    address_t *addresses;
    size_t n_addresses;
    int64_t *tag_ids;
    size_t n_tag_ids;
} contact_t;

typedef struct {
    char *name;
    char *color; /* NULL when absent */
} tag_t;

/* Parse and validate a JSON body. Malformed JSON -> 400; wrong types -> 422;
 * rule failures -> 422 with the spec's exact message. */
int parse_contact(const char *body, size_t len, contact_t *out, app_err *e);
int parse_tag(const char *body, size_t len, tag_t *out, app_err *e);
/* {"favorite": true|false}; anything else -> 422. */
int parse_favorite(const char *body, size_t len, int *out, app_err *e);

void contact_free(contact_t *c);
void tag_free(tag_t *t);

#endif
