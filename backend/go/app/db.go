// Package app is the Go version of the address book API; same routes, JSON,
// SQL and SQLite settings as the Rust reference (backend/rust).
package app

import (
	"context"
	"database/sql"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"sort"
	"sync"
	"sync/atomic"
	"time"

	"github.com/mattn/go-sqlite3"
)

const pragmas = `
	PRAGMA journal_mode = WAL;
	PRAGMA synchronous = NORMAL;
	PRAGMA busy_timeout = 5000;
	PRAGMA foreign_keys = ON;
	PRAGMA cache_size = -64000;
	PRAGMA temp_store = MEMORY;
	PRAGMA mmap_size = 268435456;
	PRAGMA journal_size_limit = 67108864;
`

func init() {
	// Apply the tuning to every connection the pools open.
	sql.Register("sqlite3_tuned", &sqlite3.SQLiteDriver{
		ConnectHook: func(c *sqlite3.SQLiteConn) error {
			_, err := c.Exec(pragmas, nil)
			return err
		},
	})
}

// Db has a pool of read-only connections and a single write connection.
// Under WAL, reads run in parallel and never wait on the writer; writes are
// serialized in-process (one connection) instead of contending for SQLite's lock.
type Db struct {
	read       *sql.DB
	write      *sql.DB
	stmts      sync.Map // query -> *sql.Stmt on the read pool
	generation atomic.Uint64
}

func Open(path string, readers int, migrationsDir string) (*Db, error) {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return nil, err
	}
	// _txlock=immediate: transactions start with BEGIN IMMEDIATE.
	write, err := sql.Open("sqlite3_tuned", "file:"+path+"?_txlock=immediate")
	if err != nil {
		return nil, err
	}
	write.SetMaxOpenConns(1)
	write.SetConnMaxIdleTime(0)
	d := &Db{write: write}
	// Open the writer first so the file exists, WAL is on and migrations have
	// run before any reader connects.
	if err := d.migrate(migrationsDir); err != nil {
		return nil, err
	}
	read, err := sql.Open("sqlite3_tuned", "file:"+path+"?mode=ro")
	if err != nil {
		return nil, err
	}
	read.SetMaxOpenConns(readers)
	read.SetMaxIdleConns(readers)
	read.SetConnMaxIdleTime(0)
	d.read = read
	return d, nil
}

// Reader returns a querier on the read pool with cached prepared statements.
func (d *Db) Reader() Querier { return reader{d} }

// Transaction runs fn inside BEGIN IMMEDIATE ... COMMIT on the write connection.
func (d *Db) Transaction(ctx context.Context, fn func(tx *sql.Tx) error) error {
	tx, err := d.write.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer d.generation.Add(1) // bump even on error: a failed write may still have changed data
	if err := fn(tx); err != nil {
		tx.Rollback()
		return err
	}
	return tx.Commit()
}

// Generation counts writes by this process; response caches key on it.
func (d *Db) Generation() uint64 { return d.generation.Load() }

func (d *Db) migrate(dir string) error {
	files, err := filepath.Glob(filepath.Join(dir, "*.sql"))
	if err != nil || len(files) == 0 {
		return fmt.Errorf("no migrations found in %s", dir)
	}
	sort.Strings(files)
	return d.Transaction(context.Background(), func(tx *sql.Tx) error {
		var current int
		if err := tx.QueryRow("PRAGMA user_version").Scan(&current); err != nil {
			return err
		}
		for i := current; i < len(files); i++ {
			script, err := os.ReadFile(files[i])
			if err != nil {
				return err
			}
			if _, err := tx.Exec(string(script)); err != nil {
				return fmt.Errorf("%s: %w", files[i], err)
			}
			if _, err := tx.Exec(fmt.Sprintf("PRAGMA user_version = %d", i+1)); err != nil {
				return err
			}
		}
		return nil
	})
}

// Checkpoint uses the same policy as the Rust backend: PASSIVE, then TRUNCATE
// once the WAL passes 64 MB and has been fully copied, waiting at most 50 ms.
func (d *Db) Checkpoint(ctx context.Context) error {
	conn, err := d.write.Conn(ctx)
	if err != nil {
		return err
	}
	defer conn.Close()
	var busy, walPages, copied int
	if err := conn.QueryRowContext(ctx, "PRAGMA wal_checkpoint(PASSIVE)").Scan(&busy, &walPages, &copied); err != nil {
		return err
	}
	if walPages < 16_384 || copied < walPages {
		return nil
	}
	conn.ExecContext(ctx, "PRAGMA busy_timeout = 50")
	defer conn.ExecContext(ctx, "PRAGMA busy_timeout = 5000")
	_, err = conn.ExecContext(ctx, "PRAGMA wal_checkpoint(TRUNCATE)")
	return err
}

func (d *Db) StartCheckpointer() {
	go func() {
		for range time.Tick(5 * time.Second) {
			if err := d.Checkpoint(context.Background()); err != nil {
				log.Printf("warning: WAL checkpoint failed: %v", err)
			}
		}
	}()
}

func (d *Db) TruncateWal() error {
	_, err := d.write.Exec("PRAGMA wal_checkpoint(TRUNCATE)")
	return err
}

// Querier is satisfied by the read pool and by *sql.Tx.
type Querier interface {
	QueryContext(ctx context.Context, query string, args ...any) (*sql.Rows, error)
	QueryRowContext(ctx context.Context, query string, args ...any) *sql.Row
}

type reader struct{ d *Db }

func (r reader) stmt(ctx context.Context, query string) (*sql.Stmt, error) {
	if s, ok := r.d.stmts.Load(query); ok {
		return s.(*sql.Stmt), nil
	}
	s, err := r.d.read.PrepareContext(ctx, query)
	if err != nil {
		return nil, err
	}
	if prev, loaded := r.d.stmts.LoadOrStore(query, s); loaded {
		s.Close()
		return prev.(*sql.Stmt), nil
	}
	return s, nil
}

func (r reader) QueryContext(ctx context.Context, query string, args ...any) (*sql.Rows, error) {
	s, err := r.stmt(ctx, query)
	if err != nil {
		return nil, err
	}
	return s.QueryContext(ctx, args...)
}

func (r reader) QueryRowContext(ctx context.Context, query string, args ...any) *sql.Row {
	s, err := r.stmt(ctx, query)
	if err != nil {
		// Surface the prepare error through the returned row.
		return r.d.read.QueryRowContext(ctx, query, args...)
	}
	return s.QueryRowContext(ctx, args...)
}
