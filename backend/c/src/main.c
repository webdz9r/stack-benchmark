/* C version of the address book API: libmicrohttpd + the SQLite amalgamation +
 * yyjson + zlib. Same routes, JSON, SQL and SQLite settings as the Rust
 * reference (backend/rust); built from docs/requirements/.
 *
 *   THREADS=4 ./server          (listens on 127.0.0.1:7885)
 *
 * Threading (ARCH-11): libmicrohttpd's I/O threads only accept connections and
 * move bytes. An API request is captured, its connection suspended, and the
 * work queued for a pool of THREADS worker threads, each with its own read
 * connection; the worker builds and gzips the reply, then resumes the
 * connection. So a burst of SQLite work never stops connections being accepted.
 */
#include <errno.h>
#include <locale.h>
#include <microhttpd.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "cache.h"
#include "db.h"
#include "http.h"
#include "json.h"
#include "repo.h"
#include "text.h"
#include "validate.h"

#define MAX_BODY (1 << 20)

static const char *static_dir;
static int has_frontend;

/* Per-request state. Everything a worker needs is copied out of the
 * connection first, so workers never call libmicrohttpd. */
typedef struct {
    buf_t body;
    int too_large;
    enum { READING, QUEUED, REPLIED } state;
    struct MHD_Connection *conn;
    char *method, *path;                        /* path is what follows "/api" */
    char *q, *tag, *limit, *offset, *favorite;  /* query parameters (NULL if absent) */
    char *if_none_match;
    int fresh, accept_gzip;
    int peek;       /* I/O thread: answer only from cache; status 0 = needs a worker */
    reply_t reply;
} req_t;

static char *dup_or_null(const char *s) { return s ? strdup(s) : NULL; }

static const char *env(const char *name, const char *fallback) {
    const char *v = getenv(name);
    return v && *v ? v : fallback;
}

/* ---------------------------------------------------------------- parsing */

/* Strict integer: optional '-', digits only, in range. */
static int parse_i64(const char *s, int64_t *out) {
    if (!s || !*s) return 0;
    const char *p = s + (*s == '-');
    if (!*p) return 0;
    for (const char *q = p; *q; q++)
        if (*q < '0' || *q > '9') return 0;
    errno = 0;
    char *end;
    long long v = strtoll(s, &end, 10);
    if (errno || *end) return 0;
    *out = v;
    return 1;
}

/* Query filters; returns 0 with *e set on a bad parameter (400, spec §7). */
static int list_query(const req_t *r, list_query_t *q, app_err *e) {
    memset(q, 0, sizeof *q);
    q->q = r->q;
    const char *v;
    if ((v = r->tag) && *v) {
        if (!parse_i64(v, &q->tag)) { set_err(e, 400, "tag must be an integer"); return 0; }
        q->has_tag = 1;
    }
    if ((v = r->limit) && *v) {
        if (!parse_i64(v, &q->limit)) { set_err(e, 400, "limit must be an integer"); return 0; }
        q->has_limit = 1;
    }
    if ((v = r->offset) && *v) {
        if (!parse_i64(v, &q->offset)) { set_err(e, 400, "offset must be an integer"); return 0; }
        q->has_offset = 1;
    }
    if ((v = r->favorite) && *v) {
        if (strcmp(v, "true") && strcmp(v, "false")) { set_err(e, 400, "favorite must be true or false"); return 0; }
        q->favorite = strcmp(v, "true") == 0;
    }
    return 1;
}

/* Cache key part for filters: the normalized search, so "Smith" and "smith " share an entry. */
static void filter_key(buf_t *k, const list_query_t *q) {
    char *fts = fts_query(q->q);
    buf_printf(k, "%s|", fts ? fts : "");
    free(fts);
    if (q->has_tag) buf_printf(k, "%lld", (long long)q->tag);
    buf_printf(k, "|%d", q->favorite);
}

static int etag_matches(const char *header, const char *etag) {
    if (!header) return 0;
    const char *p = header;
    while (*p) {
        while (*p == ' ' || *p == ',' || *p == '\t') p++;
        if (strncmp(p, "W/", 2) == 0) p += 2;
        const char *end = p;
        while (*end && *end != ',') end++;
        const char *trim = end;
        while (trim > p && (trim[-1] == ' ' || trim[-1] == '\t')) trim--;
        size_t n = (size_t)(trim - p);
        if ((n == 1 && *p == '*') || (n == strlen(etag) && strncmp(p, etag, n) == 0)) return 1;
        p = end;
    }
    return 0;
}

/* ---------------------------------------------------------------- handlers */

typedef struct {
    int kind; /* 0 stats, 1 tags, 2 list, 3 letters */
    list_query_t q;
} compute_arg;

static int compute(void *a, buf_t *out, app_err *e) {
    compute_arg *ca = a;
    conn_t *r = db_reader(e);
    switch (ca->kind) {
        case 0: return repo_stats(r, out, e);
        case 1: return repo_list_tags(r, out, e);
        case 2: return repo_list_contacts(r, &ca->q, out, e);
        default: return repo_list_letters(r, &ca->q, out, e);
    }
}

static reply_t cached(const req_t *rq, const char *key, compute_arg *ca) {
    app_err e = {0};
    char *body;
    size_t len;
    char etag[20];
    if (rq->peek) {
        if (!cache_peek(key, rq->fresh, &body, &len, etag)) return (reply_t){.status = 0};
    } else if (!cache_json(key, rq->fresh, compute, ca, &body, &len, etag, &e)) {
        return error_reply(e.status, e.msg);
    }
    reply_t r = json_reply(200, body, len);
    memcpy(r.etag, etag, sizeof etag);
    if (etag_matches(rq->if_none_match, etag)) {
        free(r.body);
        r.body = NULL;
        r.len = 0;
        r.status = 304;
    }
    return r;
}

static reply_t direct(int (*fn)(void *, buf_t *, app_err *), void *arg, int status) {
    app_err e = {0};
    buf_t b = {0};
    if (!fn(arg, &b, &e)) {
        buf_free(&b);
        return error_reply(e.status, e.msg);
    }
    size_t len;
    char *body = buf_take(&b, &len);
    return json_reply(status, body, len);
}

static reply_t list_contacts(const req_t *c) {
    compute_arg ca = {.kind = 2};
    app_err e = {0};
    if (!list_query(c, &ca.q, &e)) return error_reply(e.status, e.msg);
    char *fts = fts_query(ca.q.q);
    int filtered = ca.q.has_tag || ca.q.favorite || fts;
    free(fts);
    if (!filtered) return c->peek ? (reply_t){.status = 0} : direct(compute, &ca, 200); /* not cached (CACHE-4) */
    buf_t k = {0};
    buf_puts(&k, "list|");
    filter_key(&k, &ca.q);
    const char *limit = c->limit, *offset = c->offset;
    buf_printf(&k, "|%s|%s", limit ? limit : "", offset ? offset : "");
    reply_t r = cached(c, k.data, &ca);
    buf_free(&k);
    return r;
}

static reply_t list_letters(const req_t *c) {
    compute_arg ca = {.kind = 3};
    app_err e = {0};
    if (!list_query(c, &ca.q, &e)) return error_reply(e.status, e.msg);
    buf_t k = {0};
    buf_puts(&k, "letters|");
    filter_key(&k, &ca.q);
    reply_t r = cached(c, k.data, &ca);
    buf_free(&k);
    return r;
}

typedef struct { int64_t id; } id_arg;

static int get_contact_fn(void *a, buf_t *out, app_err *e) {
    return repo_get_contact(db_reader(e), ((id_arg *)a)->id, out, e);
}

/* Validate, then write in one transaction and read the contact back. */
static reply_t save_contact(const buf_t *body, int64_t id, int create) {
    app_err e = {0};
    contact_t in;
    if (!parse_contact(body->data ? body->data : "", body->len, &in, &e)) return error_reply(e.status, e.msg);
    buf_t out = {0};
    conn_t *w = db_begin(&e);
    if (w) {
        int ok = create ? repo_insert_contact(w, &in, &id, &e) : repo_update_contact(w, id, &in, &e);
        if (ok) repo_get_contact(w, id, &out, &e);
        db_end(w, &e);
    }
    contact_free(&in);
    if (e.status) {
        buf_free(&out);
        return error_reply(e.status, e.msg);
    }
    size_t len;
    char *data = buf_take(&out, &len);
    return json_reply(create ? 201 : 200, data, len);
}

static reply_t save_tag(const buf_t *body, int64_t id, int create) {
    app_err e = {0};
    tag_t t;
    if (!parse_tag(body->data ? body->data : "", body->len, &t, &e)) return error_reply(e.status, e.msg);
    buf_t out = {0};
    conn_t *w = db_begin(&e);
    if (w) {
        if (create) repo_insert_tag(w, &t, &out, &e);
        else repo_update_tag(w, id, &t, &out, &e);
        db_end(w, &e);
    }
    tag_free(&t);
    if (e.status) {
        buf_free(&out);
        return error_reply(e.status, e.msg);
    }
    size_t len;
    char *data = buf_take(&out, &len);
    return json_reply(create ? 201 : 200, data, len);
}

static reply_t no_content(int (*fn)(conn_t *, int64_t, app_err *), int64_t id) {
    app_err e = {0};
    conn_t *w = db_begin(&e);
    if (w) {
        fn(w, id, &e);
        db_end(w, &e);
    }
    if (e.status) return error_reply(e.status, e.msg);
    return (reply_t){.status = 204};
}

static reply_t set_favorite(const buf_t *body, int64_t id) {
    app_err e = {0};
    int favorite;
    if (!parse_favorite(body->data ? body->data : "", body->len, &favorite, &e)) return error_reply(e.status, e.msg);
    conn_t *w = db_begin(&e);
    if (w) {
        repo_set_favorite(w, id, favorite, &e);
        db_end(w, &e);
    }
    if (e.status) return error_reply(e.status, e.msg);
    return (reply_t){.status = 204};
}

/* ---------------------------------------------------------------- routing */

#define IS(m) (strcmp(method, m) == 0)

static reply_t route_api(req_t *c) {
    const char *path = c->path, *method = c->method;
    const buf_t *body = &c->body;
    /* On the I/O thread only cacheable GETs are attempted (from cache); everything
     * else goes straight to a worker. */
    if (c->peek && (!IS("GET") || !(strcmp(path, "/stats") == 0 || strcmp(path, "/tags") == 0 ||
                                     strcmp(path, "/contacts") == 0 || strcmp(path, "/contacts/letters") == 0)))
        return (reply_t){.status = 0};
    if (strcmp(path, "/health") == 0) {
        if (!IS("GET")) return error_reply(405, "method not allowed");
        return (reply_t){.status = 200, .body = strdup("ok"), .len = 2, .type = "text/plain; charset=utf-8"};
    }
    if (strcmp(path, "/stats") == 0) {
        if (!IS("GET")) return error_reply(405, "method not allowed");
        compute_arg ca = {.kind = 0};
        return cached(c, "stats", &ca);
    }
    if (strcmp(path, "/tags") == 0) {
        if (IS("GET")) {
            compute_arg ca = {.kind = 1};
            return cached(c, "tags", &ca);
        }
        if (IS("POST")) return save_tag(body, 0, 1);
        return error_reply(405, "method not allowed");
    }
    if (strcmp(path, "/contacts") == 0) {
        if (IS("GET")) return list_contacts(c);
        if (IS("POST")) return save_contact(body, 0, 1);
        return error_reply(405, "method not allowed");
    }
    if (strcmp(path, "/contacts/letters") == 0) { /* matched before /contacts/{id} (API-1) */
        if (!IS("GET")) return error_reply(405, "method not allowed");
        return list_letters(c);
    }
    char seg[64];
    int64_t id;
    if (strncmp(path, "/tags/", 6) == 0 && !strchr(path + 6, '/')) {
        if (!parse_i64(path + 6, &id)) return error_reply(400, "invalid id");
        if (IS("PUT")) return save_tag(body, id, 0);
        if (IS("DELETE")) return no_content(repo_delete_tag, id);
        return error_reply(405, "method not allowed");
    }
    if (strncmp(path, "/contacts/", 10) == 0) {
        const char *rest = path + 10, *slash = strchr(rest, '/');
        size_t n = slash ? (size_t)(slash - rest) : strlen(rest);
        if (n >= sizeof seg) return error_reply(404, "not found");
        memcpy(seg, rest, n);
        seg[n] = '\0';
        if (!slash) {
            if (!parse_i64(seg, &id)) return error_reply(400, "invalid id");
            if (IS("GET")) {
                id_arg a = {id};
                return direct(get_contact_fn, &a, 200);
            }
            if (IS("PUT")) return save_contact(body, id, 0);
            if (IS("DELETE")) return no_content(repo_delete_contact, id);
            return error_reply(405, "method not allowed");
        }
        if (strcmp(slash, "/favorite") == 0) {
            if (!parse_i64(seg, &id)) return error_reply(400, "invalid id");
            if (IS("PUT")) return set_favorite(body, id);
            return error_reply(405, "method not allowed");
        }
    }
    return error_reply(404, "not found");
}

/* ---------------------------------------------------------------- workers */

static pthread_mutex_t queue_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t queue_ready = PTHREAD_COND_INITIALIZER;
static size_t queue_len;

/* A FIFO of requests waiting for a worker. */
typedef struct job { req_t *r; struct job *next; } job_t;
static job_t *jobs_head, *jobs_tail;

static void enqueue(req_t *r) {
    job_t *j = malloc(sizeof *j);
    j->r = r;
    j->next = NULL;
    pthread_mutex_lock(&queue_lock);
    if (jobs_tail) jobs_tail->next = j;
    else jobs_head = j;
    jobs_tail = j;
    queue_len++;
    pthread_cond_signal(&queue_ready);
    pthread_mutex_unlock(&queue_lock);
}

static void *worker(void *arg) {
    (void)arg;
    for (;;) {
        pthread_mutex_lock(&queue_lock);
        while (!jobs_head) pthread_cond_wait(&queue_ready, &queue_lock);
        job_t *j = jobs_head;
        jobs_head = j->next;
        if (!jobs_head) jobs_tail = NULL;
        queue_len--;
        pthread_mutex_unlock(&queue_lock);

        req_t *r = j->r;
        free(j);
        r->reply = r->too_large ? error_reply(413, "request body too large") : route_api(r);
        finish_reply(&r->reply, r->accept_gzip);
        r->state = REPLIED;
        MHD_resume_connection(r->conn); /* the I/O thread calls handler() again and sends it */
    }
    return NULL;
}

static void capture(req_t *r, struct MHD_Connection *c, const char *url, const char *method) {
    r->conn = c;
    r->method = strdup(method);
    r->path = strdup(url + 4);
    static const char *const names[] = {"q", "tag", "limit", "offset", "favorite"};
    char **slots[] = {&r->q, &r->tag, &r->limit, &r->offset, &r->favorite};
    for (int i = 0; i < 5; i++) *slots[i] = dup_or_null(MHD_lookup_connection_value(c, MHD_GET_ARGUMENT_KIND, names[i]));
    r->if_none_match = dup_or_null(MHD_lookup_connection_value(c, MHD_HEADER_KIND, MHD_HTTP_HEADER_IF_NONE_MATCH));
    r->fresh = MHD_lookup_connection_value(c, MHD_HEADER_KIND, "X-Fresh") != NULL;
    const char *ae = MHD_lookup_connection_value(c, MHD_HEADER_KIND, MHD_HTTP_HEADER_ACCEPT_ENCODING);
    r->accept_gzip = ae && strstr(ae, "gzip") != NULL;
}

static enum MHD_Result handler(void *cls, struct MHD_Connection *c, const char *url, const char *method,
                               const char *version, const char *upload, size_t *upload_size, void **req_cls) {
    req_t *r = *req_cls;
    if (!r) {
        *req_cls = calloc(1, sizeof(req_t));
        return MHD_YES;
    }
    if (r->state == REPLIED) return send_reply(c, &r->reply); /* resumed after a worker finished */
    if (*upload_size) {
        if (r->body.len + *upload_size > MAX_BODY) r->too_large = 1;
        else buf_put(&r->body, upload, *upload_size);
        *upload_size = 0;
        return MHD_YES;
    }
    if (r->state == QUEUED) return MHD_YES;

    int api = strncmp(url, "/api/", 5) == 0 || strcmp(url, "/api") == 0;
    if (api && strcmp(url, "/api/health") != 0) {
        capture(r, c, url, method);
        if (!r->too_large) {
            /* A cache hit is answered right here, like Rust's async handlers do. */
            r->peek = 1;
            reply_t hit = route_api(r);
            r->peek = 0;
            if (hit.status) {
                finish_reply(&hit, r->accept_gzip);
                return send_reply(c, &hit);
            }
        }
        r->state = QUEUED;
        MHD_suspend_connection(c);
        enqueue(r);
        return MHD_YES;
    }
    /* Cheap requests stay on the I/O thread: the health check and static files. */
    reply_t reply;
    const char *ae = MHD_lookup_connection_value(c, MHD_HEADER_KIND, MHD_HTTP_HEADER_ACCEPT_ENCODING);
    if (api) {
        req_t tmp = {.method = (char *)method, .path = (char *)url + 4};
        reply = route_api(&tmp);
    } else if (has_frontend && (IS("GET") || IS("HEAD")) && static_reply(static_dir, url, &reply)) {
    } else {
        reply = error_reply(404, "not found");
    }
    finish_reply(&reply, ae && strstr(ae, "gzip") != NULL);
    return send_reply(c, &reply);
}

static void completed(void *cls, struct MHD_Connection *c, void **req_cls, enum MHD_RequestTerminationCode code) {
    req_t *r = *req_cls;
    if (r) {
        buf_free(&r->body);
        free(r->method); free(r->path); free(r->q); free(r->tag); free(r->limit); free(r->offset);
        free(r->favorite); free(r->if_none_match);
        free(r->reply.body);
        free(r);
        *req_cls = NULL;
    }
}

int main(void) {
    /* towlower needs a UTF-8 locale for non-ASCII labels. */
    if (!setlocale(LC_CTYPE, "C.UTF-8")) setlocale(LC_CTYPE, "en_US.UTF-8");
    signal(SIGPIPE, SIG_IGN);

    const char *db_path = env("DATABASE_PATH", "data/address-book.db");
    const char *bind_addr = env("BIND_ADDR", "127.0.0.1:7885");
    static_dir = env("STATIC_DIR", "../../frontend/dist");
    long cpus = sysconf(_SC_NPROCESSORS_ONLN);
    int threads = atoi(env("THREADS", "0"));
    if (threads <= 0) threads = (int)(cpus > 0 ? cpus : 4);

    char index[4096];
    snprintf(index, sizeof index, "%s/index.html", static_dir);
    has_frontend = access(index, R_OK) == 0;

    /* Block the shutdown signals before any thread starts; main waits for them. */
    sigset_t sigs;
    sigemptyset(&sigs);
    sigaddset(&sigs, SIGINT);
    sigaddset(&sigs, SIGTERM);
    pthread_sigmask(SIG_BLOCK, &sigs, NULL);

    db_open(db_path, env("MIGRATIONS_DIR", "../migrations"));
    db_start_checkpointer();
    cache_init(64u << 20, 1.0);

    char host[256];
    snprintf(host, sizeof host, "%s", bind_addr);
    char *colon = strrchr(host, ':');
    if (!colon) { fprintf(stderr, "BIND_ADDR must be host:port\n"); return 1; }
    *colon = '\0';
    struct sockaddr_in addr = {.sin_family = AF_INET, .sin_port = htons((uint16_t)atoi(colon + 1))};
    if (inet_pton(AF_INET, host, &addr.sin_addr) != 1) { fprintf(stderr, "bad BIND_ADDR host\n"); return 1; }

    /* THREADS workers do the SQLite work (one read connection each); the same
     * number of I/O threads accept connections and move bytes. */
    for (int i = 0; i < threads; i++) {
        pthread_t t;
        pthread_create(&t, NULL, worker, NULL);
        pthread_detach(t);
    }

    struct MHD_Daemon *d = MHD_start_daemon(
        MHD_USE_AUTO_INTERNAL_THREAD | MHD_ALLOW_SUSPEND_RESUME | MHD_USE_ERROR_LOG, 0, NULL, NULL, &handler, NULL,
        MHD_OPTION_SOCK_ADDR, (struct sockaddr *)&addr,
        MHD_OPTION_THREAD_POOL_SIZE, (unsigned int)threads,
        MHD_OPTION_CONNECTION_LIMIT, (unsigned int)60000,
        MHD_OPTION_CONNECTION_TIMEOUT, (unsigned int)120,
        /* The default backlog (SOMAXCONN, often 128) overflowed at 6,000 users;
         * 1024 matches Tokio's default on the Rust side. */
        MHD_OPTION_LISTEN_BACKLOG_SIZE, (unsigned int)1024,
        MHD_OPTION_NOTIFY_COMPLETED, &completed, NULL,
        MHD_OPTION_END);
    if (!d) { fprintf(stderr, "failed to start the HTTP server on %s\n", bind_addr); return 1; }
    fprintf(stderr, "database ready: %s (%d workers with a reader each, %d I/O threads); %s; listening on http://%s\n", db_path,
            threads, threads, has_frontend ? "serving frontend" : "no frontend build", bind_addr);

    int sig;
    sigwait(&sigs, &sig);
    MHD_stop_daemon(d); /* finishes in-flight requests */
    return 0;
}
