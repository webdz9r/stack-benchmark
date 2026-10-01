#include "db.h"

#include <dirent.h>
#include <errno.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static const char *PRAGMAS =
    "PRAGMA journal_mode = WAL;"
    "PRAGMA synchronous = NORMAL;"
    "PRAGMA busy_timeout = 5000;"
    "PRAGMA foreign_keys = ON;"
    "PRAGMA cache_size = -64000;"
    "PRAGMA temp_store = MEMORY;"
    "PRAGMA mmap_size = 268435456;"
    "PRAGMA journal_size_limit = 67108864;";

#define STMT_SLOTS 64

struct conn {
    sqlite3 *db;
    struct { char *sql; sqlite3_stmt *stmt; } stmts[STMT_SLOTS];
};

static char *db_path;
static conn_t *writer;
static pthread_mutex_t write_lock = PTHREAD_MUTEX_INITIALIZER;
static _Atomic uint64_t generation;
static pthread_key_t reader_key;

void set_err(app_err *e, int status, const char *fmt, ...) {
    e->status = status;
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(e->msg, sizeof e->msg, fmt, ap);
    va_end(ap);
}

int db_fail(app_err *e, sqlite3 *db, const char *what) {
    fprintf(stderr, "internal error: %s: %s\n", what, db ? sqlite3_errmsg(db) : "?");
    set_err(e, 500, "internal server error");
    return 0;
}

sqlite3 *conn_db(conn_t *c) { return c->db; }

sqlite3_stmt *conn_stmt(conn_t *c, const char *sql, app_err *e) {
    /* Open addressing on a hash of the SQL text. */
    unsigned long h = 5381;
    for (const char *p = sql; *p; p++) h = h * 33 + (unsigned char)*p;
    for (int i = 0; i < STMT_SLOTS; i++) {
        int slot = (int)((h + (unsigned long)i) % STMT_SLOTS);
        if (c->stmts[slot].sql && strcmp(c->stmts[slot].sql, sql) == 0) {
            sqlite3_stmt *s = c->stmts[slot].stmt;
            sqlite3_reset(s);
            sqlite3_clear_bindings(s);
            return s;
        }
        if (!c->stmts[slot].sql) {
            sqlite3_stmt *s;
            if (sqlite3_prepare_v3(c->db, sql, -1, SQLITE_PREPARE_PERSISTENT, &s, NULL) != SQLITE_OK) {
                db_fail(e, c->db, "prepare");
                return NULL;
            }
            c->stmts[slot].sql = strdup(sql);
            c->stmts[slot].stmt = s;
            return s;
        }
    }
    /* Table full: prepare an uncached statement (never happens with this app's SQL). */
    fprintf(stderr, "warning: statement cache full\n");
    sqlite3_stmt *s;
    if (sqlite3_prepare_v2(c->db, sql, -1, &s, NULL) != SQLITE_OK) {
        db_fail(e, c->db, "prepare");
        return NULL;
    }
    return s;
}

static conn_t *open_conn(int readonly) {
    conn_t *c = calloc(1, sizeof *c);
    int flags = (readonly ? SQLITE_OPEN_READONLY : SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE) | SQLITE_OPEN_NOMUTEX;
    if (sqlite3_open_v2(db_path, &c->db, flags, NULL) != SQLITE_OK) {
        fprintf(stderr, "open %s: %s\n", db_path, sqlite3_errmsg(c->db));
        exit(1);
    }
    char *msg = NULL;
    if (sqlite3_exec(c->db, PRAGMAS, NULL, NULL, &msg) != SQLITE_OK) {
        fprintf(stderr, "pragmas: %s\n", msg);
        exit(1);
    }
    return c;
}

static int cmp_names(const void *a, const void *b) {
    return strcmp(*(char *const *)a, *(char *const *)b);
}

static char *read_file(const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *s = malloc((size_t)n + 1);
    size_t got = fread(s, 1, (size_t)n, f);
    s[got] = '\0';
    fclose(f);
    return s;
}

/* Apply pending migrations, all in one BEGIN IMMEDIATE transaction (DB-4). */
static void migrate(const char *dir) {
    DIR *d = opendir(dir);
    if (!d) {
        fprintf(stderr, "migrations directory %s: %s\n", dir, strerror(errno));
        exit(1);
    }
    char *names[256];
    int count = 0;
    struct dirent *ent;
    while ((ent = readdir(d)) && count < 256) {
        size_t n = strlen(ent->d_name);
        if (n > 4 && strcmp(ent->d_name + n - 4, ".sql") == 0) names[count++] = strdup(ent->d_name);
    }
    closedir(d);
    qsort(names, (size_t)count, sizeof names[0], cmp_names);
    if (count == 0) {
        fprintf(stderr, "no migrations found in %s\n", dir);
        exit(1);
    }

    sqlite3 *db = writer->db;
    char *msg = NULL;
    if (sqlite3_exec(db, "BEGIN IMMEDIATE", NULL, NULL, &msg) != SQLITE_OK) goto fail;
    sqlite3_stmt *s;
    sqlite3_prepare_v2(db, "PRAGMA user_version", -1, &s, NULL);
    sqlite3_step(s);
    int current = sqlite3_column_int(s, 0);
    sqlite3_finalize(s);
    for (int i = current; i < count; i++) {
        char path[4096];
        snprintf(path, sizeof path, "%s/%s", dir, names[i]);
        char *script = read_file(path);
        if (!script || sqlite3_exec(db, script, NULL, NULL, &msg) != SQLITE_OK) {
            fprintf(stderr, "migration %s failed\n", names[i]);
            goto fail;
        }
        free(script);
        char pragma[64];
        snprintf(pragma, sizeof pragma, "PRAGMA user_version = %d", i + 1);
        if (sqlite3_exec(db, pragma, NULL, NULL, &msg) != SQLITE_OK) goto fail;
        fprintf(stderr, "applied migration %d (%s)\n", i + 1, names[i]);
    }
    if (sqlite3_exec(db, "COMMIT", NULL, NULL, &msg) != SQLITE_OK) goto fail;
    for (int i = 0; i < count; i++) free(names[i]);
    return;
fail:
    fprintf(stderr, "migrate: %s\n", msg ? msg : sqlite3_errmsg(db));
    exit(1);
}

static void mkdirs(const char *path) {
    char tmp[4096];
    snprintf(tmp, sizeof tmp, "%s", path);
    char *slash = strrchr(tmp, '/');
    if (!slash) return;
    *slash = '\0';
    for (char *p = tmp + 1; *p; p++) {
        if (*p == '/') {
            *p = '\0';
            mkdir(tmp, 0755);
            *p = '/';
        }
    }
    mkdir(tmp, 0755);
}

int db_open(const char *path, const char *migrations_dir) {
    db_path = strdup(path);
    mkdirs(path);
    /* The writer first, so the file exists, WAL is on and migrations have run
     * before any reader connects (ARCH-14). */
    writer = open_conn(0);
    migrate(migrations_dir);
    pthread_key_create(&reader_key, NULL);
    return 0;
}

conn_t *db_reader(app_err *e) {
    conn_t *c = pthread_getspecific(reader_key);
    if (!c) {
        c = open_conn(1);
        pthread_setspecific(reader_key, c);
    }
    (void)e;
    return c;
}

conn_t *db_begin(app_err *e) {
    pthread_mutex_lock(&write_lock);
    if (sqlite3_exec(writer->db, "BEGIN IMMEDIATE", NULL, NULL, NULL) != SQLITE_OK) {
        db_fail(e, writer->db, "begin");
        atomic_fetch_add(&generation, 1);
        pthread_mutex_unlock(&write_lock);
        return NULL;
    }
    return writer;
}

void db_end(conn_t *w, app_err *e) {
    if (e->status == 0) {
        if (sqlite3_exec(w->db, "COMMIT", NULL, NULL, NULL) != SQLITE_OK) {
            db_fail(e, w->db, "commit");
            sqlite3_exec(w->db, "ROLLBACK", NULL, NULL, NULL);
        }
    } else {
        sqlite3_exec(w->db, "ROLLBACK", NULL, NULL, NULL);
    }
    /* Bump even on error: a failed write may still have changed data. */
    atomic_fetch_add(&generation, 1);
    pthread_mutex_unlock(&write_lock);
}

uint64_t db_generation(void) { return atomic_load(&generation); }

/* Same policy as the Rust reference: PASSIVE, then TRUNCATE once the WAL passes
 * 64 MB and has been fully copied, waiting at most 50 ms. */
static int checkpoint(void) {
    int wal_pages = 0, copied = 0, rc;
    pthread_mutex_lock(&write_lock);
    rc = sqlite3_wal_checkpoint_v2(writer->db, NULL, SQLITE_CHECKPOINT_PASSIVE, &wal_pages, &copied);
    if (rc == SQLITE_OK && wal_pages >= 16384 && copied >= wal_pages) {
        sqlite3_busy_timeout(writer->db, 50);
        rc = sqlite3_wal_checkpoint_v2(writer->db, NULL, SQLITE_CHECKPOINT_TRUNCATE, NULL, NULL);
        if (rc == SQLITE_BUSY) rc = SQLITE_OK; /* readers active; try again next tick */
        sqlite3_busy_timeout(writer->db, 5000);
    }
    pthread_mutex_unlock(&write_lock);
    return rc;
}

static void *checkpointer(void *arg) {
    (void)arg;
    for (;;) {
        sleep(5);
        int rc = checkpoint();
        if (rc != SQLITE_OK) fprintf(stderr, "warning: WAL checkpoint failed: %s\n", sqlite3_errstr(rc));
    }
    return NULL;
}

void db_start_checkpointer(void) {
    pthread_t t;
    pthread_create(&t, NULL, checkpointer, NULL);
    pthread_detach(t);
}

void db_truncate_wal(void) {
    pthread_mutex_lock(&write_lock);
    sqlite3_wal_checkpoint_v2(writer->db, NULL, SQLITE_CHECKPOINT_TRUNCATE, NULL, NULL);
    pthread_mutex_unlock(&write_lock);
}
