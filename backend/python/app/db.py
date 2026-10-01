"""SQLite access, mirroring the Rust backend's design.

One writer and several readers per process. Python runs as several worker
processes (the GIL limits one process to roughly one core of Python code), so
each process has its own writer; SQLite's lock serializes them across
processes, with BEGIN IMMEDIATE + busy_timeout making writers queue instead of
failing.
"""

import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from .errors import AppError

PRAGMAS = """
    PRAGMA journal_mode = WAL;
    PRAGMA synchronous = NORMAL;
    PRAGMA busy_timeout = 5000;
    PRAGMA foreign_keys = ON;
    PRAGMA cache_size = -64000;
    PRAGMA temp_store = MEMORY;
    PRAGMA mmap_size = 268435456;
    PRAGMA journal_size_limit = 67108864;
"""

# The shared migration files (backend/migrations), so the schema can't drift.
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


class Db:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)

        self._writer = self._connect(readonly=False)
        self._write_lock = threading.Lock()
        self._migrate()

        self._local = threading.local()

        # Change detection for the response cache. PRAGMA data_version on this
        # connection changes whenever any *other* connection commits, which
        # covers this process's writer, the other workers, and the seeder.
        self._watcher = self._connect(readonly=True)
        self._watch_lock = threading.Lock()
        self._last_data_version = None
        self._generation = 0

    def _connect(self, readonly: bool) -> sqlite3.Connection:
        uri = f"file:{self.path}?mode=ro" if readonly else f"file:{self.path}"
        conn = sqlite3.connect(uri, uri=True, autocommit=True, check_same_thread=False)
        conn.executescript(PRAGMAS)
        return conn

    def _migrate(self) -> None:
        files = sorted(MIGRATIONS_DIR.glob("*.sql"))
        c = self._writer
        # IMMEDIATE takes the write lock first, so concurrent workers starting
        # up don't both run the same migration.
        c.execute("BEGIN IMMEDIATE")
        try:
            current = c.execute("PRAGMA user_version").fetchone()[0]
            for i, f in enumerate(files[current:], start=current):
                # Statement by statement: executescript() would COMMIT early.
                for stmt in _split_sql(f.read_text()):
                    c.execute(stmt)
                c.execute(f"PRAGMA user_version = {i + 1}")
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise

    def reader(self) -> sqlite3.Connection:
        """This thread's read-only connection."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._local.conn = self._connect(readonly=True)
        return conn

    @contextmanager
    def transaction(self):
        """The process's write connection inside BEGIN IMMEDIATE ... COMMIT."""
        with self._write_lock:
            c = self._writer
            c.execute("BEGIN IMMEDIATE")
            try:
                yield c
                c.execute("COMMIT")
            except BaseException:
                c.execute("ROLLBACK")
                raise

    def generation(self) -> int:
        """Increases whenever the database may have changed."""
        with self._watch_lock:
            version = self._watcher.execute("PRAGMA data_version").fetchone()[0]
            if version != self._last_data_version:
                self._last_data_version = version
                self._generation += 1
            return self._generation

    def checkpoint(self) -> tuple[int, int, bool]:
        """Same policy as the Rust backend: PASSIVE, then TRUNCATE once the WAL
        passes 64 MB and has been fully copied, waiting at most 50 ms."""
        with self._write_lock:
            c = self._writer
            _, wal_pages, copied = c.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
            if wal_pages < 16_384 or copied < wal_pages:
                return wal_pages, copied, False
            c.execute("PRAGMA busy_timeout = 50")
            try:
                truncated = c.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[1] == 0
            finally:
                c.execute("PRAGMA busy_timeout = 5000")
            return wal_pages, copied, truncated

    def truncate_wal(self) -> None:
        """Copy the whole WAL into the database and empty it (waits for readers)."""
        with self._write_lock:
            self._writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def start_checkpointer(self, every_seconds: float = 5.0) -> None:
        def loop():
            while True:
                time.sleep(every_seconds)
                try:
                    self.checkpoint()
                except sqlite3.Error as e:  # busy or similar; try again next tick
                    logging.getLogger("address_book").warning("WAL checkpoint failed: %s", e)

        threading.Thread(target=loop, name="checkpointer", daemon=True).start()


def _split_sql(script: str) -> list[str]:
    """Split a migration file into statements (sqlite3.complete_statement
    handles semicolons inside strings and CREATE TRIGGER bodies)."""
    statements, buf = [], ""
    for line in script.splitlines(keepends=True):
        if not buf and line.strip().startswith("--"):
            continue
        buf += line
        if sqlite3.complete_statement(buf):
            statements.append(buf.strip())
            buf = ""
    if buf.strip():
        statements.append(buf.strip())
    return statements

