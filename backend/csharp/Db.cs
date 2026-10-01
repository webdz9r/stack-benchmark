using System.Collections.Concurrent;
using Microsoft.Data.Sqlite;

namespace AddressBook;

/// <summary>
/// A pool of read-only connections plus a single write connection, like the
/// Rust reference. Under WAL, reads run in parallel and never wait on the
/// writer; writes are serialized in-process instead of contending for SQLite's
/// lock. Microsoft.Data.Sqlite's own pooling is off: connections here are kept
/// open with their PRAGMAs applied and their prepared commands cached.
/// </summary>
public sealed class Db
{
    const string Pragmas = """
        PRAGMA journal_mode = WAL;
        PRAGMA synchronous = NORMAL;
        PRAGMA busy_timeout = 5000;
        PRAGMA foreign_keys = ON;
        PRAGMA cache_size = -64000;
        PRAGMA temp_store = MEMORY;
        PRAGMA mmap_size = 268435456;
        PRAGMA journal_size_limit = 67108864;
        """;

    readonly string _path;
    readonly Conn _writer;
    readonly SemaphoreSlim _writeLock = new(1, 1);
    readonly ConcurrentBag<Conn> _readers = [];
    readonly SemaphoreSlim _readSlots;
    long _generation;

    // The bundled e_sqlite3 is built without SQLITE_DEFAULT_MEMSTATUS=0, so memory
    // statistics take a global mutex on every malloc/free and serialize the
    // readers (DB-2). Turning them off at runtime has the same effect; it must
    // happen before SQLite initializes, i.e. before the first connection opens.
    static Db()
    {
        const int SQLITE_CONFIG_MEMSTATUS = 9;
        SQLitePCL.Batteries_V2.Init();
        if (SQLitePCL.raw.sqlite3_config(SQLITE_CONFIG_MEMSTATUS, 0) != SQLitePCL.raw.SQLITE_OK)
            Console.Error.WriteLine("warning: could not disable SQLite memory statistics");
    }

    public Db(string path, int readers, string migrationsDir)
    {
        _path = path;
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path))!);
        // Open the writer first so the file exists, WAL is on and migrations
        // have run before any reader connects.
        _writer = Open(readOnly: false);
        Migrate(migrationsDir);
        for (var i = 0; i < readers; i++) _readers.Add(Open(readOnly: true));
        _readSlots = new SemaphoreSlim(readers, readers);
    }

    Conn Open(bool readOnly)
    {
        var mode = readOnly ? SqliteOpenMode.ReadOnly : SqliteOpenMode.ReadWriteCreate;
        var cs = new SqliteConnectionStringBuilder { DataSource = _path, Mode = mode, Pooling = false }.ToString();
        var conn = new SqliteConnection(cs);
        conn.Open();
        using (var cmd = conn.CreateCommand())
        {
            cmd.CommandText = Pragmas;
            cmd.ExecuteNonQuery();
        }
        return new Conn(conn);
    }

    /// <summary>Run a read on a pooled read-only connection.</summary>
    public async Task<T> Read<T>(Func<Conn, T> fn)
    {
        await _readSlots.WaitAsync();
        _readers.TryTake(out var conn);
        try
        {
            return fn(conn!);
        }
        finally
        {
            _readers.Add(conn!);
            _readSlots.Release();
        }
    }

    /// <summary>Run fn inside BEGIN IMMEDIATE ... COMMIT on the write connection.</summary>
    public async Task<T> Write<T>(Func<Conn, T> fn)
    {
        await _writeLock.WaitAsync();
        try
        {
            return InTransaction(_writer, fn);
        }
        finally
        {
            // Bump even on error: a failed write may still have changed data.
            Interlocked.Increment(ref _generation);
            _writeLock.Release();
        }
    }

    /// <summary>Synchronous write, for the seeder.</summary>
    public T WriteBlocking<T>(Func<Conn, T> fn)
    {
        _writeLock.Wait();
        try { return InTransaction(_writer, fn); }
        finally { _writeLock.Release(); }
    }

    static T InTransaction<T>(Conn c, Func<Conn, T> fn)
    {
        c.Exec("BEGIN IMMEDIATE");
        try
        {
            var result = fn(c);
            c.Exec("COMMIT");
            return result;
        }
        catch
        {
            c.Exec("ROLLBACK");
            throw;
        }
    }

    /// <summary>Counts writes by this process; response caches key on it.</summary>
    public long Generation => Interlocked.Read(ref _generation);

    void Migrate(string dir)
    {
        var files = Directory.GetFiles(dir, "*.sql").Order(StringComparer.Ordinal).ToArray();
        if (files.Length == 0) throw new InvalidOperationException($"no migrations found in {dir}");
        WriteBlocking(c =>
        {
            var current = (int)c.Scalar<long>("PRAGMA user_version");
            for (var i = current; i < files.Length; i++)
            {
                c.Exec(File.ReadAllText(files[i]));
                c.Exec($"PRAGMA user_version = {i + 1}");
            }
            return 0;
        });
    }

    /// <summary>Same policy as the Rust backend: PASSIVE, then TRUNCATE once the
    /// WAL passes 64 MB and has been fully copied, waiting at most 50 ms.</summary>
    public async Task Checkpoint()
    {
        await _writeLock.WaitAsync();
        try
        {
            var (walPages, copied) = _writer.Row("PRAGMA wal_checkpoint(PASSIVE)", [], r => (r.GetInt64(1), r.GetInt64(2)));
            if (walPages < 16_384 || copied < walPages) return;
            _writer.Exec("PRAGMA busy_timeout = 50");
            try { _writer.Exec("PRAGMA wal_checkpoint(TRUNCATE)"); }
            finally { _writer.Exec("PRAGMA busy_timeout = 5000"); }
        }
        finally
        {
            _writeLock.Release();
        }
    }

    public Timer StartCheckpointer() =>
        new(_ =>
        {
            try { Checkpoint().Wait(); }
            catch (Exception e) { Console.Error.WriteLine($"warning: WAL checkpoint failed: {e.GetBaseException().Message}"); }
        }, null, 5000, 5000);

    public void TruncateWal() => _writer.Exec("PRAGMA wal_checkpoint(TRUNCATE)");
}

/// <summary>
/// One open connection with its prepared commands cached. SQL uses `?`
/// placeholders (as in the other backends); they're rewritten to named
/// parameters once, when the command is first prepared.
/// </summary>
public sealed class Conn(SqliteConnection connection)
{
    readonly Dictionary<string, SqliteCommand> _commands = [];

    SqliteCommand Command(string sql, object?[] args)
    {
        if (!_commands.TryGetValue(sql, out var cmd))
        {
            cmd = connection.CreateCommand();
            var n = 0;
            cmd.CommandText = string.Concat(sql.Select(ch => ch == '?' ? $"$p{n++}" : ch.ToString()));
            for (var i = 0; i < n; i++) cmd.Parameters.Add(new SqliteParameter($"$p{i}", null));
            cmd.Prepare();
            _commands[sql] = cmd;
        }
        for (var i = 0; i < args.Length; i++) cmd.Parameters[i].Value = args[i] ?? DBNull.Value;
        return cmd;
    }

    public int Run(string sql, params object?[] args) => Command(sql, args).ExecuteNonQuery();

    public T Scalar<T>(string sql, params object?[] args) => (T)Command(sql, args).ExecuteScalar()!;

    public T? Row<T>(string sql, object?[] args, Func<SqliteDataReader, T> map)
    {
        using var r = Command(sql, args).ExecuteReader();
        return r.Read() ? map(r) : default;
    }

    public List<T> Rows<T>(string sql, object?[] args, Func<SqliteDataReader, T> map)
    {
        using var r = Command(sql, args).ExecuteReader();
        var list = new List<T>();
        while (r.Read()) list.Add(map(r));
        return list;
    }

    public long LastInsertId => Scalar<long>("SELECT last_insert_rowid()");

    /// <summary>Run a statement or script without caching (migrations, PRAGMAs).</summary>
    public void Exec(string sql)
    {
        using var cmd = connection.CreateCommand();
        cmd.CommandText = sql;
        cmd.ExecuteNonQuery();
    }
}
