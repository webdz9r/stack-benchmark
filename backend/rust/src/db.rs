//! SQLite access: a pool of read connections plus a single write connection.
//!
//! Under WAL, readers never block the writer (or each other), so reads fan out
//! across the pool. SQLite only allows one writer at a time, so all writes go
//! through one connection behind a mutex. That serializes writes inside the
//! process instead of having connections fight over the database lock.

use std::path::Path;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use r2d2::Pool;
use r2d2_sqlite::SqliteConnectionManager;
use r2d2_sqlite::rusqlite::{self, Connection, OpenFlags};

use crate::error::AppError;

const PRAGMAS: &str = "
    PRAGMA journal_mode = WAL;
    PRAGMA synchronous = NORMAL;
    PRAGMA busy_timeout = 5000;
    PRAGMA foreign_keys = ON;
    PRAGMA cache_size = -64000;
    PRAGMA temp_store = MEMORY;
    PRAGMA mmap_size = 268435456;
    PRAGMA journal_size_limit = 67108864;
";

/// Migrations in order; `PRAGMA user_version` records how many have run.
const MIGRATIONS: &[&str] = &[
    include_str!("../../migrations/001_init.sql"),
    include_str!("../../migrations/002_sort_letter.sql"),
];

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Checkpoint {
    pub wal_pages: i64,
    pub copied: i64,
    pub truncated: bool,
}

#[derive(Clone)]
pub struct Db {
    read: Pool<SqliteConnectionManager>,
    write: Arc<Mutex<Connection>>,
    /// Bumped after every write; response caches key on it.
    generation: Arc<AtomicU64>,
}

impl Db {
    pub fn open(path: impl AsRef<Path>, read_pool_size: u32) -> Result<Self, AppError> {
        let path = path.as_ref();
        if let Some(dir) = path.parent() {
            std::fs::create_dir_all(dir).map_err(|e| AppError::internal(e.to_string()))?;
        }

        // Open the writer first so the file exists, WAL is enabled and migrations
        // have run before any reader connects.
        let mut write = Connection::open(path)?;
        write.execute_batch(PRAGMAS)?;
        migrate(&mut write)?;

        let manager = SqliteConnectionManager::file(path)
            .with_flags(OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX)
            .with_init(|c| c.execute_batch(PRAGMAS));
        // No validity check on every checkout: these are local, long-lived connections.
        let read = Pool::builder().max_size(read_pool_size).test_on_check_out(false).build(manager)?;

        Ok(Self { read, write: Arc::new(Mutex::new(write)), generation: Arc::default() })
    }

    /// Run a read-only closure on a pooled connection, off the async runtime.
    pub async fn read<T, F>(&self, f: F) -> Result<T, AppError>
    where
        T: Send + 'static,
        F: FnOnce(&Connection) -> Result<T, AppError> + Send + 'static,
    {
        let pool = self.read.clone();
        tokio::task::spawn_blocking(move || {
            let conn = pool.get()?;
            f(&conn)
        })
        .await?
    }

    /// Run a closure on the single write connection, off the async runtime.
    /// The closure gets `&mut Connection` so it can open a transaction.
    pub async fn write<T, F>(&self, f: F) -> Result<T, AppError>
    where
        T: Send + 'static,
        F: FnOnce(&mut Connection) -> Result<T, AppError> + Send + 'static,
    {
        let write = self.write.clone();
        let generation = self.generation.clone();
        tokio::task::spawn_blocking(move || {
            let mut conn = write.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
            let result = f(&mut conn);
            // Bump even on error: a failed write may still have changed data.
            generation.fetch_add(1, Ordering::Release);
            result
        })
        .await?
    }

    /// How many writes this process has made; changes whenever data may have.
    pub fn generation(&self) -> u64 {
        self.generation.load(Ordering::Acquire)
    }

    /// Copy committed WAL pages back into the main database file, and reset
    /// the WAL once it has grown large.
    ///
    /// SQLite's automatic checkpoint only runs right after a commit, and it
    /// can't finish while readers are using older pages. If writes then stop,
    /// the WAL stays large and every read has to search it, which made reads
    /// several times slower in load tests. PASSIVE never waits on readers.
    ///
    /// Under constant read load the WAL also never restarts from the top, so
    /// the file keeps growing. Once everything is copied, TRUNCATE resets it;
    /// that needs a moment with no readers mid-WAL, so it waits at most 50 ms
    /// and simply tries again on the next call.
    pub async fn checkpoint(&self) -> Result<Checkpoint, AppError> {
        const RESET_AT_PAGES: i64 = 16_384; // 64 MB of 4 KB pages

        self.write(|c| {
            let run = |c: &Connection, mode: &str| {
                c.query_row(&format!("PRAGMA wal_checkpoint({mode})"), [], |r| {
                    Ok(Checkpoint { wal_pages: r.get(1)?, copied: r.get(2)?, truncated: false })
                })
            };
            let passive = run(c, "PASSIVE")?;
            if passive.wal_pages < RESET_AT_PAGES || passive.copied < passive.wal_pages {
                return Ok(passive);
            }
            c.busy_timeout(Duration::from_millis(50))?;
            let truncate = run(c, "TRUNCATE");
            c.busy_timeout(Duration::from_millis(5000))?;
            let truncate = truncate?;
            Ok(Checkpoint { truncated: truncate.wal_pages == 0, ..passive })
        })
        .await
    }

    /// Synchronous access to the write connection, for CLI tools like the seeder.
    pub fn write_blocking<T>(
        &self,
        f: impl FnOnce(&mut Connection) -> Result<T, AppError>,
    ) -> Result<T, AppError> {
        let mut conn = self.write.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
        f(&mut conn)
    }
}

fn migrate(conn: &mut Connection) -> rusqlite::Result<()> {
    let current: i64 = conn.pragma_query_value(None, "user_version", |r| r.get(0))?;
    for (i, sql) in MIGRATIONS.iter().enumerate().skip(current as usize) {
        let tx = conn.transaction()?;
        tx.execute_batch(sql)?;
        tx.pragma_update(None, "user_version", i as i64 + 1)?;
        tx.commit()?;
        tracing::info!(version = i + 1, "applied migration");
    }
    Ok(())
}
