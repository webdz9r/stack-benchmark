/* SQLite access: one serialized writer plus one read-only connection per server
 * thread (docs/requirements/01-architecture.md §3). */
#ifndef DB_H
#define DB_H

#include <sqlite3.h>
#include <stdint.h>

/* An application error: status 0 means OK. Rendered as {"error": msg}. */
typedef struct {
    int status;
    char msg[512];
} app_err;

void set_err(app_err *e, int status, const char *fmt, ...) __attribute__((format(printf, 3, 4)));
/* Turn a failed SQLite call into a 500 (logged); returns 0 so callers can `return db_fail(...)`. */
int db_fail(app_err *e, sqlite3 *db, const char *what);

/* A connection with its prepared statements cached by SQL text. */
typedef struct conn conn_t;

sqlite3 *conn_db(conn_t *c);
/* A reset, cleared statement for this SQL, prepared once per connection. */
sqlite3_stmt *conn_stmt(conn_t *c, const char *sql, app_err *e);

/* Open the database: writer first (pragmas, migrations), readers lazily per thread. */
int db_open(const char *path, const char *migrations_dir);
/* This thread's read-only connection. */
conn_t *db_reader(app_err *e);
/* Lock the writer and BEGIN IMMEDIATE. Returns the writer, or NULL (err set). */
conn_t *db_begin(app_err *e);
/* COMMIT when ok (e->status == 0), ROLLBACK otherwise; unlocks; bumps the generation. */
void db_end(conn_t *w, app_err *e);
/* Writes by this process so far; response caches key on it (CACHE-9). */
uint64_t db_generation(void);
/* Start the 5 s WAL checkpoint thread (DB-7). */
void db_start_checkpointer(void);
/* PRAGMA wal_checkpoint(TRUNCATE) on the writer (the seeder, after its big transaction). */
void db_truncate_wal(void);

#endif
