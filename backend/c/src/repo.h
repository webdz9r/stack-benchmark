/* The canonical SQL (docs/requirements/02-database.md §7), writing JSON directly.
 * Every function returns 1 on success, 0 with *e set on failure. */
#ifndef REPO_H
#define REPO_H

#include <stdint.h>

#include "db.h"
#include "json.h"
#include "validate.h"

typedef struct {
    const char *q;          /* search text, may be NULL */
    int has_tag;
    int64_t tag;
    int favorite;           /* 1 = favorites only */
    int has_limit, has_offset;
    int64_t limit, offset;
} list_query_t;

int repo_list_contacts(conn_t *c, const list_query_t *q, buf_t *out, app_err *e);
int repo_list_letters(conn_t *c, const list_query_t *q, buf_t *out, app_err *e);
int repo_get_contact(conn_t *c, int64_t id, buf_t *out, app_err *e);
int repo_insert_contact(conn_t *w, const contact_t *in, int64_t *id, app_err *e);
int repo_update_contact(conn_t *w, int64_t id, const contact_t *in, app_err *e);
int repo_set_favorite(conn_t *w, int64_t id, int favorite, app_err *e);
int repo_delete_contact(conn_t *w, int64_t id, app_err *e);
int repo_list_tags(conn_t *c, buf_t *out, app_err *e);
int repo_insert_tag(conn_t *w, const tag_t *t, buf_t *out, app_err *e);
int repo_update_tag(conn_t *w, int64_t id, const tag_t *t, buf_t *out, app_err *e);
int repo_delete_tag(conn_t *w, int64_t id, app_err *e);
int repo_stats(conn_t *c, buf_t *out, app_err *e);

#endif
