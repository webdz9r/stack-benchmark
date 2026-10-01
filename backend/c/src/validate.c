#include "validate.h"

#include <stdlib.h>
#include <string.h>
#include <yyjson.h>

#include "text.h"

static const char *TAG_COLORS[] = {"slate", "red", "orange", "amber", "green", "teal", "sky", "indigo", "violet", "pink"};

/* A string field: missing or null -> "", a string -> trimmed copy, anything else -> error. */
static int str_field(yyjson_val *obj, const char *key, char **out, app_err *e) {
    yyjson_val *v = obj ? yyjson_obj_get(obj, key) : NULL;
    if (!v || yyjson_is_null(v)) {
        *out = strdup("");
        return 1;
    }
    if (!yyjson_is_str(v)) {
        set_err(e, 422, "%s must be a string", key);
        *out = NULL;
        return 0;
    }
    *out = trim_dup(yyjson_get_str(v));
    return 1;
}

static char *normalize_label(char *trimmed) {
    char *lower = lower_dup(trimmed);
    free(trimmed);
    if (!*lower) {
        free(lower);
        return strdup("other");
    }
    return lower;
}

static yyjson_doc *read_json(const char *body, size_t len, app_err *e) {
    yyjson_read_err err;
    yyjson_doc *doc = yyjson_read_opts((char *)body, len, 0, NULL, &err);
    if (!doc) {
        set_err(e, 400, "invalid JSON: %s", err.msg);
        return NULL;
    }
    if (!yyjson_is_obj(yyjson_doc_get_root(doc))) {
        set_err(e, 422, "expected a JSON object");
        yyjson_doc_free(doc);
        return NULL;
    }
    return doc;
}

/* Emails or phones: drop rows whose value is empty after trimming (V5, API-U1). */
static int labeled_list(yyjson_val *root, const char *key, labeled_t **out, size_t *n, app_err *e) {
    *out = NULL;
    *n = 0;
    yyjson_val *arr = yyjson_obj_get(root, key);
    if (!arr || yyjson_is_null(arr)) return 1;
    if (!yyjson_is_arr(arr)) {
        set_err(e, 422, "%s must be a list", key);
        return 0;
    }
    *out = calloc(yyjson_arr_size(arr) + 1, sizeof **out);
    size_t i, max;
    yyjson_val *row;
    yyjson_arr_foreach(arr, i, max, row) {
        if (!yyjson_is_obj(row)) {
            set_err(e, 422, "%s entries must be objects", key);
            return 0;
        }
        char *label, *value;
        if (!str_field(row, "label", &label, e)) return 0;
        if (!str_field(row, "value", &value, e)) {
            free(label);
            return 0;
        }
        if (!*value) {
            free(label);
            free(value);
            continue;
        }
        (*out)[*n].label = normalize_label(label);
        (*out)[*n].value = value;
        (*n)++;
    }
    return 1;
}

static int valid_email(const char *v) {
    const char *at = strchr(v, '@');
    if (!at || at == v || !strchr(at + 1, '.')) return 0;
    size_t n = strlen(v);
    uint32_t cp;
    for (size_t i = 0; i < n;) {
        i += utf8_decode(v + i, n - i, &cp);
        if (is_unicode_space(cp)) return 0;
    }
    return 1;
}

static int iso_date(const char *s) {
    if (strlen(s) != 10 || s[4] != '-' || s[7] != '-') return 0;
    for (int i = 0; i < 10; i++)
        if (i != 4 && i != 7 && (s[i] < '0' || s[i] > '9')) return 0;
    int month = (s[5] - '0') * 10 + (s[6] - '0'), day = (s[8] - '0') * 10 + (s[9] - '0');
    return month >= 1 && month <= 12 && day >= 1 && day <= 31;
}

static int cmp_i64(const void *a, const void *b) {
    int64_t x = *(const int64_t *)a, y = *(const int64_t *)b;
    return (x > y) - (x < y);
}

int parse_contact(const char *body, size_t len, contact_t *c, app_err *e) {
    memset(c, 0, sizeof *c);
    yyjson_doc *doc = read_json(body, len, e);
    if (!doc) return 0;
    yyjson_val *root = yyjson_doc_get_root(doc);
    int ok = 0;

    /* V1: trim */
    if (!str_field(root, "first_name", &c->first_name, e) || !str_field(root, "last_name", &c->last_name, e) ||
        !str_field(root, "company", &c->company, e) || !str_field(root, "job_title", &c->job_title, e) ||
        !str_field(root, "notes", &c->notes, e))
        goto done;
    yyjson_val *fav = yyjson_obj_get(root, "favorite");
    if (fav && !yyjson_is_null(fav) && !yyjson_is_bool(fav)) {
        set_err(e, 422, "favorite must be true or false");
        goto done;
    }
    c->favorite = fav && yyjson_is_true(fav);

    /* V2 */
    if (!*c->first_name && !*c->last_name && !*c->company) {
        set_err(e, 422, "a name or company is required");
        goto done;
    }
    /* V3, V4 */
    char *birthday;
    if (!str_field(root, "birthday", &birthday, e)) goto done;
    if (*birthday) {
        c->birthday = birthday;
        if (!iso_date(birthday)) {
            set_err(e, 422, "birthday must be YYYY-MM-DD");
            goto done;
        }
    } else {
        free(birthday);
    }
    /* V5, V6 */
    if (!labeled_list(root, "emails", &c->emails, &c->n_emails, e) ||
        !labeled_list(root, "phones", &c->phones, &c->n_phones, e))
        goto done;
    for (size_t i = 0; i < c->n_emails; i++) {
        if (!valid_email(c->emails[i].value)) {
            set_err(e, 422, "'%s' is not a valid email", c->emails[i].value);
            goto done;
        }
    }
    /* V7 */
    yyjson_val *addrs = yyjson_obj_get(root, "addresses");
    if (addrs && !yyjson_is_null(addrs)) {
        if (!yyjson_is_arr(addrs)) {
            set_err(e, 422, "addresses must be a list");
            goto done;
        }
        c->addresses = calloc(yyjson_arr_size(addrs) + 1, sizeof *c->addresses);
        size_t i, max;
        yyjson_val *row;
        yyjson_arr_foreach(addrs, i, max, row) {
            if (!yyjson_is_obj(row)) {
                set_err(e, 422, "addresses entries must be objects");
                goto done;
            }
            address_t a = {0};
            char *label;
            if (!str_field(row, "label", &label, e) || !str_field(row, "street", &a.street, e) ||
                !str_field(row, "city", &a.city, e) || !str_field(row, "region", &a.region, e) ||
                !str_field(row, "postal_code", &a.postal_code, e) || !str_field(row, "country", &a.country, e)) {
                free(a.street); free(a.city); free(a.region); free(a.postal_code); free(a.country);
                goto done;
            }
            if (!*a.street && !*a.city && !*a.region && !*a.postal_code && !*a.country) {
                free(label); free(a.street); free(a.city); free(a.region); free(a.postal_code); free(a.country);
                continue;
            }
            a.label = normalize_label(label);
            c->addresses[c->n_addresses++] = a;
        }
    }
    /* V8 */
    yyjson_val *tags = yyjson_obj_get(root, "tag_ids");
    if (tags && !yyjson_is_null(tags)) {
        if (!yyjson_is_arr(tags)) {
            set_err(e, 422, "tag_ids must be a list");
            goto done;
        }
        c->tag_ids = calloc(yyjson_arr_size(tags) + 1, sizeof *c->tag_ids);
        size_t i, max;
        yyjson_val *v;
        yyjson_arr_foreach(tags, i, max, v) {
            if (!yyjson_is_int(v)) {
                set_err(e, 422, "tag_ids must be integers");
                goto done;
            }
            c->tag_ids[c->n_tag_ids++] = yyjson_get_sint(v);
        }
        qsort(c->tag_ids, c->n_tag_ids, sizeof *c->tag_ids, cmp_i64);
        size_t w = 0;
        for (size_t r = 0; r < c->n_tag_ids; r++)
            if (w == 0 || c->tag_ids[w - 1] != c->tag_ids[r]) c->tag_ids[w++] = c->tag_ids[r];
        c->n_tag_ids = w;
    }
    ok = 1;
done:
    yyjson_doc_free(doc);
    if (!ok) contact_free(c);
    return ok;
}

int parse_tag(const char *body, size_t len, tag_t *t, app_err *e) {
    memset(t, 0, sizeof *t);
    yyjson_doc *doc = read_json(body, len, e);
    if (!doc) return 0;
    yyjson_val *root = yyjson_doc_get_root(doc);
    int ok = 0;
    if (!str_field(root, "name", &t->name, e)) goto done;
    if (!*t->name) { set_err(e, 422, "tag name is required"); goto done; }
    if (utf8_count(t->name) > 40) { set_err(e, 422, "tag name must be 40 characters or fewer"); goto done; }
    yyjson_val *color = yyjson_obj_get(root, "color");
    if (color && !yyjson_is_null(color)) {
        if (!yyjson_is_str(color)) { set_err(e, 422, "color must be a string"); goto done; }
        const char *s = yyjson_get_str(color);
        int known = 0;
        for (size_t i = 0; i < sizeof TAG_COLORS / sizeof *TAG_COLORS; i++) known |= strcmp(s, TAG_COLORS[i]) == 0;
        if (!known) { set_err(e, 422, "unknown tag color '%s'", s); goto done; }
        t->color = strdup(s);
    }
    ok = 1;
done:
    yyjson_doc_free(doc);
    if (!ok) tag_free(t);
    return ok;
}

int parse_favorite(const char *body, size_t len, int *out, app_err *e) {
    yyjson_doc *doc = read_json(body, len, e);
    if (!doc) return 0;
    yyjson_val *v = yyjson_obj_get(yyjson_doc_get_root(doc), "favorite");
    int ok = v && yyjson_is_bool(v);
    if (ok) *out = yyjson_is_true(v);
    else set_err(e, 422, "favorite must be true or false");
    yyjson_doc_free(doc);
    return ok;
}

void contact_free(contact_t *c) {
    free(c->first_name); free(c->last_name); free(c->company); free(c->job_title); free(c->notes); free(c->birthday);
    for (size_t i = 0; i < c->n_emails; i++) { free(c->emails[i].label); free(c->emails[i].value); }
    for (size_t i = 0; i < c->n_phones; i++) { free(c->phones[i].label); free(c->phones[i].value); }
    for (size_t i = 0; i < c->n_addresses; i++) {
        address_t *a = &c->addresses[i];
        free(a->label); free(a->street); free(a->city); free(a->region); free(a->postal_code); free(a->country);
    }
    free(c->emails); free(c->phones); free(c->addresses); free(c->tag_ids);
    memset(c, 0, sizeof *c);
}

void tag_free(tag_t *t) {
    free(t->name);
    free(t->color);
    memset(t, 0, sizeof *t);
}
