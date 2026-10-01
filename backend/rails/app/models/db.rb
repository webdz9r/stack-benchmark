# SQLite access with the sqlite3 gem, mirroring the other backends' design.
#
# Rails' routing and controllers sit on top, but queries go straight to the
# sqlite3 driver with the same SQL as the Rust backend, so the comparison is of
# runtimes and frameworks rather than ORMs. (ActiveRecord models would add
# object allocation and query building on every request.)
#
# Per Puma worker process: one writer (behind a mutex), a read connection per
# thread, and a watcher connection for change detection. Writers in different
# workers are serialized by SQLite's lock, with BEGIN IMMEDIATE + a busy
# timeout making them queue instead of failing.
class Db
  PRAGMAS = <<~SQL
    PRAGMA journal_mode = WAL;
    PRAGMA synchronous = NORMAL;
    PRAGMA foreign_keys = ON;
    PRAGMA cache_size = -64000;
    PRAGMA temp_store = MEMORY;
    PRAGMA mmap_size = 268435456;
    PRAGMA journal_size_limit = 67108864;
  SQL

  # The shared migration files (backend/migrations), so the schema can't drift.
  MIGRATIONS_DIR = File.expand_path("../../../migrations", __dir__)

  class << self
    # This process's instance, created on first use (after Puma forks).
    def instance
      @instance ||= new(ENV.fetch("DATABASE_PATH", "data/address-book.db"))
    end

    def reset!
      @instance = nil
    end
  end

  def initialize(path)
    @path = path
    FileUtils.mkdir_p(File.dirname(path))
    @writer = connect(readonly: false)
    @write_lock = Mutex.new
    @readers = Concurrent::Map.new
    @watcher = connect(readonly: true)
    @watch_lock = Mutex.new
    @last_data_version = nil
    @generation = 0
    migrate
    start_checkpointer
  end

  # This thread's read-only connection.
  def reader
    @readers.compute_if_absent(Thread.current.object_id) { connect(readonly: true) }
  end

  # The process's write connection inside BEGIN IMMEDIATE ... COMMIT.
  def transaction
    @write_lock.synchronize do
      @writer.execute("BEGIN IMMEDIATE")
      begin
        result = yield @writer
        @writer.execute("COMMIT")
        result
      rescue Exception
        @writer.execute("ROLLBACK")
        raise
      end
    end
  end

  # Increases whenever the database may have changed. PRAGMA data_version on
  # the watcher changes whenever any other connection commits: this worker's
  # writer, the other workers, or the seeder.
  def generation
    @watch_lock.synchronize do
      version = @watcher.get_first_value("PRAGMA data_version")
      if version != @last_data_version
        @last_data_version = version
        @generation += 1
      end
      @generation
    end
  end

  # Same policy as the Rust backend: PASSIVE, then TRUNCATE once the WAL
  # passes 64 MB and has been fully copied, waiting at most 50 ms.
  def checkpoint
    @write_lock.synchronize do
      _, wal_pages, copied = @writer.execute("PRAGMA wal_checkpoint(PASSIVE)").first
      next if wal_pages < 16_384 || copied < wal_pages
      @writer.busy_handler_timeout = 50
      begin
        @writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
      ensure
        @writer.busy_handler_timeout = 5000
      end
    end
  end

  def truncate_wal
    @write_lock.synchronize { @writer.execute("PRAGMA wal_checkpoint(TRUNCATE)") }
  end

  private

  def connect(readonly:)
    db = SQLite3::Database.new(@path, readonly: readonly)
    # Waits for locks without holding the GVL, so other threads keep running.
    db.busy_handler_timeout = 5000
    db.execute_batch(PRAGMAS)
    db.extend(StatementCache)
    db
  end

  def migrate
    files = Dir[File.join(MIGRATIONS_DIR, "*.sql")].sort
    transaction do |c|
      current = c.get_first_value("PRAGMA user_version")
      files.drop(current).each.with_index(current + 1) do |file, version|
        c.execute_batch(File.read(file))
        c.execute("PRAGMA user_version = #{version}")
      end
    end
  end

  def start_checkpointer
    Thread.new do
      loop do
        sleep 5
        begin
          checkpoint
        rescue SQLite3::Exception => e
          Rails.logger.warn("WAL checkpoint failed: #{e.message}")
        end
      end
    end
  end

  # Prepared statements reused per connection (each connection is used by one
  # thread at a time). Every statement is reset after use: one left mid-result
  # keeps its read transaction open, pinning an old snapshot and blocking
  # WAL checkpoints.
  module StatementCache
    def query_all(sql, *binds)
      with_stmt(sql) { |s| s.execute(*binds).to_a }
    end

    def query_row(sql, *binds)
      with_stmt(sql) { |s| s.execute(*binds).next }
    end

    def run(sql, *binds)
      with_stmt(sql) { |s| s.execute(*binds).to_a }
      changes
    end

    private

    def with_stmt(sql)
      s = (@statements ||= {})[sql] ||= prepare(sql)
      yield s
    ensure
      s&.reset!
    end
  end
end
