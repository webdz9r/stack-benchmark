# In-process response cache; same policy as the Rust backend's cache.rs.
#
# Keys include a change count refreshed from SQLite at most once per
# max_staleness, so other users see writes within ~1 s. `X-Fresh` requests key
# on the live count (read-your-writes). Concurrent misses for a key share one
# query. Entries carry an ETag for If-None-Match revalidation.
#
# Each Puma worker has its own cache; they stay consistent because each
# detects changes through SQLite (see Db#generation), not a local counter.
class ResponseCache
  TTL_SECONDS = 30.0
  Entry = Struct.new(:body, :etag, :at)

  class << self
    def instance
      @instance ||= new(Db.instance, max_bytes: 64 * 1024 * 1024, max_staleness: 1.0)
    end

    def reset!
      @instance = nil
    end
  end

  def initialize(db, max_bytes:, max_staleness:)
    @db = db
    @max_bytes = max_bytes
    @max_staleness = max_staleness
    @entries = {} # insertion order = LRU order
    @bytes = 0
    @lock = Mutex.new
    @inflight = {}
    @published = 0
    @published_at = -Float::INFINITY
  end

  # Returns [status, headers, body] for compute's JSON, cached when unchanged.
  def json(request, key)
    full_key = [generation(request), key]
    entry = get(full_key)
    unless entry
      gate = @lock.synchronize { @inflight[full_key] ||= Mutex.new }
      gate.synchronize do # one thread computes; the rest wait and reuse it
        entry = get(full_key)
        unless entry
          body = JSON.generate(yield)
          entry = Entry.new(body, %("#{Digest::SHA1.hexdigest(body)[0, 16]}"), now)
          put(full_key, entry)
        end
      end
      @lock.synchronize { @inflight.delete(full_key) }
    end

    headers = { "etag" => entry.etag, "cache-control" => "no-cache" }
    return [304, headers, nil] if etag_matches?(request.headers["If-None-Match"], entry.etag)
    [200, headers, entry.body]
  end

  private

  def generation(request)
    return @db.generation if request.headers["X-Fresh"]
    t = now
    if t - @published_at >= @max_staleness
      @published = @db.generation
      @published_at = t
    end
    @published
  end

  def get(key)
    @lock.synchronize do
      entry = @entries[key] or return nil
      if now - entry.at > TTL_SECONDS
        drop(key)
        return nil
      end
      @entries[key] = @entries.delete(key) # move to the back (most recently used)
    end
  end

  def put(key, entry)
    @lock.synchronize do
      drop(key) if @entries.key?(key)
      @entries[key] = entry
      @bytes += entry.body.bytesize + key[1].bytesize
      drop(@entries.first[0]) while @bytes > @max_bytes && !@entries.empty?
    end
  end

  def drop(key)
    entry = @entries.delete(key)
    @bytes -= entry.body.bytesize + key[1].bytesize
  end

  def now = Process.clock_gettime(Process::CLOCK_MONOTONIC)

  def etag_matches?(header, etag)
    return false if header.nil? || header.empty?
    header.split(",").any? { |t| t = t.strip.delete_prefix("W/"); t == "*" || t == etag }
  end
end
