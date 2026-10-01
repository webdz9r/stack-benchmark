#include "cache.h"

#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define BUCKETS 8192
#define TTL_S 30.0

typedef struct entry {
    char *key;               /* "<generation>|<key>" */
    char *body;
    size_t len;
    char etag[20];
    double at;
    int computing;           /* another thread is filling it in */
    struct entry *next;      /* hash chain */
    struct entry *prev_lru, *next_lru;
} entry_t;

static entry_t *table[BUCKETS];
static entry_t lru = {.prev_lru = &lru, .next_lru = &lru}; /* sentinel; front = most recent */
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t filled = PTHREAD_COND_INITIALIZER;
static size_t bytes, max_bytes;
static double max_staleness;
static _Atomic uint64_t published;
static _Atomic int64_t published_at_ms = INT64_MIN / 2;

static double now_s(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
}

void cache_init(size_t max, double staleness) {
    max_bytes = max;
    max_staleness = staleness;
}

static uint64_t hash64(const char *s, size_t n) { /* FNV-1a */
    uint64_t h = 1469598103934665603ULL;
    for (size_t i = 0; i < n; i++) h = (h ^ (unsigned char)s[i]) * 1099511628211ULL;
    return h;
}

static void lru_unlink(entry_t *e) {
    e->prev_lru->next_lru = e->next_lru;
    e->next_lru->prev_lru = e->prev_lru;
}

static void lru_push_front(entry_t *e) {
    e->next_lru = lru.next_lru;
    e->prev_lru = &lru;
    lru.next_lru->prev_lru = e;
    lru.next_lru = e;
}

static entry_t **slot_for(const char *key) {
    entry_t **p = &table[hash64(key, strlen(key)) % BUCKETS];
    while (*p && strcmp((*p)->key, key) != 0) p = &(*p)->next;
    return p;
}

/* Unlink from the table and the LRU list and free (caller holds the lock). */
static void drop(entry_t *e) {
    entry_t **p = slot_for(e->key);
    if (*p == e) *p = e->next;
    if (!e->computing) {
        lru_unlink(e);
        bytes -= e->len + strlen(e->key);
    }
    free(e->key);
    free(e->body);
    free(e);
}

/* The write count to key on: live for X-Fresh, else refreshed at most once per max_staleness. */
static uint64_t key_generation(int fresh) {
    if (fresh) return db_generation();
    int64_t t = (int64_t)(now_s() * 1000);
    if (t - atomic_load(&published_at_ms) >= (int64_t)(max_staleness * 1000)) {
        atomic_store(&published, db_generation()); /* racing refreshes are harmless */
        atomic_store(&published_at_ms, t);
    }
    return atomic_load(&published);
}

int cache_peek(const char *key, int fresh, char **body, size_t *len, char etag[20]) {
    buf_t kb = {0};
    buf_printf(&kb, "%llu|", (unsigned long long)key_generation(fresh));
    buf_puts(&kb, key);
    int hit = 0;
    pthread_mutex_lock(&lock);
    entry_t *e = *slot_for(kb.data);
    if (e && !e->computing && now_s() - e->at <= TTL_S) {
        lru_unlink(e);
        lru_push_front(e);
        *body = malloc(e->len + 1);
        memcpy(*body, e->body, e->len + 1);
        *len = e->len;
        memcpy(etag, e->etag, 20);
        hit = 1;
    }
    pthread_mutex_unlock(&lock);
    buf_free(&kb);
    return hit;
}

int cache_json(const char *key, int fresh, compute_fn fn, void *arg, char **body, size_t *len, char etag[20],
               app_err *err) {
    /* Read the generation before computing: if a write lands mid-query, the entry
     * is filed under the older generation and replaced at the next refresh. */
    buf_t kb = {0};
    buf_printf(&kb, "%llu|", (unsigned long long)key_generation(fresh));
    buf_puts(&kb, key);
    char *full = kb.data;

    pthread_mutex_lock(&lock);
    for (;;) {
        entry_t *e = *slot_for(full);
        if (e && e->computing) {
            pthread_cond_wait(&filled, &lock);
            continue;
        }
        if (e && now_s() - e->at > TTL_S) {
            drop(e);
            e = NULL;
        }
        if (e) {
            lru_unlink(e);
            lru_push_front(e);
            *body = malloc(e->len + 1);
            memcpy(*body, e->body, e->len + 1);
            *len = e->len;
            memcpy(etag, e->etag, 20);
            pthread_mutex_unlock(&lock);
            free(full);
            return 1;
        }
        break;
    }
    /* Miss: claim the key, compute without holding the lock. */
    entry_t *e = calloc(1, sizeof *e);
    e->key = strdup(full);
    e->computing = 1;
    entry_t **p = slot_for(full);
    e->next = *p;
    *p = e;
    pthread_mutex_unlock(&lock);

    buf_t out = {0};
    int ok = fn(arg, &out, err);

    pthread_mutex_lock(&lock);
    if (!ok) {
        drop(e);
        pthread_cond_broadcast(&filled);
        pthread_mutex_unlock(&lock);
        buf_free(&out);
        free(full);
        return 0;
    }
    e->body = buf_take(&out, &e->len);
    snprintf(e->etag, sizeof e->etag, "\"%016llx\"", (unsigned long long)hash64(e->body, e->len));
    e->at = now_s();
    e->computing = 0;
    lru_push_front(e);
    bytes += e->len + strlen(e->key);
    while (bytes > max_bytes && lru.prev_lru != &lru && lru.prev_lru != e) drop(lru.prev_lru);
    *body = malloc(e->len + 1);
    memcpy(*body, e->body, e->len + 1);
    *len = e->len;
    memcpy(etag, e->etag, 20);
    pthread_cond_broadcast(&filled);
    pthread_mutex_unlock(&lock);
    free(full);
    return 1;
}
