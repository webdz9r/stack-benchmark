package addressbook;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.locks.ReentrantLock;
import java.util.stream.Stream;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.sqlite.SQLiteConfig;
import org.sqlite.SQLiteOpenMode;

/**
 * One writer connection behind a lock, plus a pool of read-only connections
 * (ARCH-12). Every connection gets the 8 pragmas (DB-6) and caches its
 * prepared statements (DB-14).
 */
public final class Db implements AutoCloseable {
    private static final Logger log = LoggerFactory.getLogger(Db.class);

    private static final String[] PRAGMAS = {
        "PRAGMA journal_mode = WAL",
        "PRAGMA synchronous = NORMAL",
        "PRAGMA busy_timeout = 5000",
        "PRAGMA foreign_keys = ON",
        "PRAGMA cache_size = -64000",
        "PRAGMA temp_store = MEMORY",
        "PRAGMA mmap_size = 268435456",
        "PRAGMA journal_size_limit = 67108864",
    };
    private static final long RESET_AT_PAGES = 16384; // 64 MB of 4 KB pages (DB-7)

    @FunctionalInterface
    public interface SqlFn<T> {
        T apply(Conn c) throws SQLException;
    }

    /** A connection with its own prepared-statement cache. Used by one thread at a time. */
    public static final class Conn implements AutoCloseable {
        private final Connection conn;
        private final Statement plain;
        private final Map<String, PreparedStatement> cache = new HashMap<>();

        Conn(Connection conn) throws SQLException {
            this.conn = conn;
            this.plain = conn.createStatement();
        }

        public PreparedStatement prepare(String sql) throws SQLException {
            PreparedStatement ps = cache.get(sql);
            if (ps == null) {
                ps = conn.prepareStatement(sql);
                cache.put(sql, ps);
            }
            return ps;
        }

        /** Runs SQL without a result: a pragma, BEGIN/COMMIT, or a whole migration file. */
        public void exec(String sql) throws SQLException {
            plain.executeUpdate(sql);
        }

        public long queryLong(String sql, Object... params) throws SQLException {
            PreparedStatement ps = bind(prepare(sql), params);
            try (ResultSet rs = ps.executeQuery()) {
                rs.next();
                return rs.getLong(1);
            }
        }

        public int update(String sql, Object... params) throws SQLException {
            return bind(prepare(sql), params).executeUpdate();
        }

        public long lastInsertRowid() throws SQLException {
            return queryLong("SELECT last_insert_rowid()");
        }

        public <T> T transaction(SqlFn<T> fn) throws SQLException {
            exec("BEGIN IMMEDIATE");
            try {
                T result = fn.apply(this);
                exec("COMMIT");
                return result;
            } catch (SQLException | RuntimeException e) {
                try {
                    exec("ROLLBACK");
                } catch (SQLException rollback) {
                    e.addSuppressed(rollback);
                }
                throw e;
            }
        }

        public static PreparedStatement bind(PreparedStatement ps, Object... params) throws SQLException {
            for (int i = 0; i < params.length; i++) {
                ps.setObject(i + 1, params[i]);
            }
            return ps;
        }

        @Override
        public void close() throws SQLException {
            for (PreparedStatement ps : cache.values()) {
                ps.close();
            }
            plain.close();
            conn.close();
        }
    }

    private final Conn writer;
    private final ReentrantLock writeLock = new ReentrantLock();
    private final BlockingQueue<Conn> readers;
    private final List<Conn> allReaders = new ArrayList<>();
    private final AtomicLong generation = new AtomicLong();
    private final ScheduledExecutorService checkpointer;

    private Db(Conn writer, List<Conn> readerConns, boolean runCheckpoints) {
        this.writer = writer;
        this.readers = new ArrayBlockingQueue<>(Math.max(1, readerConns.size()));
        this.readers.addAll(readerConns);
        this.allReaders.addAll(readerConns);
        if (runCheckpoints) {
            checkpointer = Executors.newSingleThreadScheduledExecutor(r -> {
                Thread t = new Thread(r, "wal-checkpoint");
                t.setDaemon(true);
                return t;
            });
            checkpointer.scheduleWithFixedDelay(this::checkpoint, 5, 5, TimeUnit.SECONDS);
        } else {
            checkpointer = null;
        }
    }

    /**
     * Opens the writer, runs migrations, then opens the readers (ARCH-14).
     * The seeder passes readers = 0 and no checkpoint task.
     */
    public static Db open(Path path, Path migrationsDir, int readerCount, boolean runCheckpoints)
            throws SQLException, IOException {
        Path parent = path.toAbsolutePath().getParent();
        if (parent != null) {
            Files.createDirectories(parent);
        }
        String url = "jdbc:sqlite:" + path;

        SQLiteConfig writerConfig = new SQLiteConfig();
        writerConfig.setOpenMode(SQLiteOpenMode.NOMUTEX);
        Conn writer = new Conn(writerConfig.createConnection(url));
        applyPragmas(writer);
        migrate(writer, migrationsDir);

        List<Conn> readerConns = new ArrayList<>();
        for (int i = 0; i < readerCount; i++) {
            SQLiteConfig readerConfig = new SQLiteConfig();
            readerConfig.setReadOnly(true);
            readerConfig.setOpenMode(SQLiteOpenMode.NOMUTEX);
            Conn reader = new Conn(readerConfig.createConnection(url));
            applyPragmas(reader);
            readerConns.add(reader);
        }
        return new Db(writer, readerConns, runCheckpoints);
    }

    private static void applyPragmas(Conn c) throws SQLException {
        for (String pragma : PRAGMAS) {
            c.exec(pragma);
        }
    }

    /** DB-3/DB-4: apply backend/migrations/NNN_*.sql in filename order, one transaction each. */
    private static void migrate(Conn c, Path dir) throws SQLException, IOException {
        List<Path> files;
        try (Stream<Path> s = Files.list(dir)) {
            files = s.filter(p -> p.getFileName().toString().matches("\\d+_.*\\.sql")).sorted().toList();
        }
        long applied = c.queryLong("PRAGMA user_version");
        for (int i = 1; i <= files.size(); i++) {
            if (i <= applied) {
                continue;
            }
            Path file = files.get(i - 1);
            String sql = Files.readString(file);
            int version = i;
            c.transaction(tx -> {
                // Re-check inside the write lock, in case another process just migrated.
                if (tx.queryLong("PRAGMA user_version") >= version) {
                    return null;
                }
                tx.exec(sql);
                tx.exec("PRAGMA user_version = " + version);
                return null;
            });
            log.info("applied migration {}", file.getFileName());
        }
    }

    public <T> T read(SqlFn<T> fn) throws SQLException {
        Conn c;
        try {
            c = readers.take();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new SQLException("interrupted waiting for a read connection", e);
        }
        try {
            return fn.apply(c);
        } finally {
            readers.offer(c);
        }
    }

    /** Serialized writes; the generation moves after every write, success or failure (CACHE-9). */
    public <T> T write(SqlFn<T> fn) throws SQLException {
        writeLock.lock();
        try {
            return fn.apply(writer);
        } finally {
            generation.incrementAndGet();
            writeLock.unlock();
        }
    }

    public long generation() {
        return generation.get();
    }

    /** DB-7: PASSIVE every tick; TRUNCATE once the WAL passes 64 MB and is fully copied. */
    void checkpoint() {
        writeLock.lock();
        try {
            long walPages;
            long copied;
            try (ResultSet rs = writer.prepare("PRAGMA wal_checkpoint(PASSIVE)").executeQuery()) {
                rs.next();
                walPages = rs.getLong(2);
                copied = rs.getLong(3);
            }
            if (walPages < RESET_AT_PAGES || copied < walPages) {
                return;
            }
            try {
                writer.exec("PRAGMA busy_timeout = 50");
                try (ResultSet rs = writer.prepare("PRAGMA wal_checkpoint(TRUNCATE)").executeQuery()) {
                    rs.next(); // a busy result is fine: try again next tick
                }
            } finally {
                writer.exec("PRAGMA busy_timeout = 5000");
            }
        } catch (SQLException e) {
            log.warn("WAL checkpoint failed: {}", e.getMessage()); // DB-8
        } finally {
            writeLock.unlock();
        }
    }

    /** DB-10: after the seeder's single transaction. */
    public void truncateWal() throws SQLException {
        writeLock.lock();
        try (ResultSet rs = writer.prepare("PRAGMA wal_checkpoint(TRUNCATE)").executeQuery()) {
            rs.next();
        } finally {
            writeLock.unlock();
        }
    }

    @Override
    public void close() {
        if (checkpointer != null) {
            checkpointer.shutdownNow();
        }
        writeLock.lock();
        try {
            for (Conn c : allReaders) {
                c.close();
            }
            writer.close();
        } catch (SQLException e) {
            log.warn("closing database: {}", e.getMessage());
        } finally {
            writeLock.unlock();
        }
    }
}
