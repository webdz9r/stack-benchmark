/* In-process response cache (docs/requirements/04-caching-and-http.md). */
#ifndef CACHE_H
#define CACHE_H

#include <stddef.h>

#include "db.h"
#include "json.h"

typedef int (*compute_fn)(void *arg, buf_t *out, app_err *e);

void cache_init(size_t max_bytes, double max_staleness_s);

/* The JSON body for `key`, from cache when the data hasn't changed, otherwise
 * computed by fn (concurrent misses for a key share one computation).
 * fresh = the request had X-Fresh (key on the live write count).
 * On success *body is a malloc'd copy and etag holds "\"<16 hex>\"". */
int cache_json(const char *key, int fresh, compute_fn fn, void *arg, char **body, size_t *len, char etag[20],
               app_err *e);

/* Cache hit only: never computes. Returns 1 with a copy of the body if `key` is
 * cached and fresh, else 0 (the caller hands the request to a worker). */
int cache_peek(const char *key, int fresh, char **body, size_t *len, char etag[20]);

#endif
