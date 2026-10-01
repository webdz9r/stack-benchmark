using System.Collections.Concurrent;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Serialization.Metadata;

namespace AddressBook;

/// <summary>
/// In-process response cache; same policy as the Rust backend's cache.rs.
/// Keys include a copy of the write count that catches up at most once per
/// maxStaleness, so other users see writes within ~1 s and the cache empties
/// at most once a second. X-Fresh requests key on the live count
/// (read-your-writes). Concurrent misses for a key share one query. Entries
/// carry an ETag for If-None-Match revalidation.
/// </summary>
public sealed class ResponseCache(Db db, long maxBytes, TimeSpan maxStaleness)
{
    static readonly TimeSpan Ttl = TimeSpan.FromSeconds(30);

    sealed record Entry(byte[] Body, string ETag, DateTime At);

    readonly ConcurrentDictionary<string, Lazy<Task<Entry>>> _entries = new();
    readonly ConcurrentQueue<string> _order = new(); // insertion order, for eviction
    long _bytes;
    long _published;
    long _publishedAtTicks = long.MinValue;

    long Generation(HttpRequest request)
    {
        if (request.Headers.ContainsKey("X-Fresh")) return db.Generation;
        var now = Environment.TickCount64;
        if (now - Interlocked.Read(ref _publishedAtTicks) >= (long)maxStaleness.TotalMilliseconds)
        {
            // Racing refreshes store near-identical values; either is fine.
            Interlocked.Exchange(ref _published, db.Generation);
            Interlocked.Exchange(ref _publishedAtTicks, now);
        }
        return Interlocked.Read(ref _published);
    }

    /// <summary>Serve compute's result as JSON, from cache when the data hasn't changed.</summary>
    public async Task Json<T>(HttpContext ctx, string key, Func<Conn, T> compute, JsonTypeInfo<T> type)
    {
        // Read the write count before querying: if a write lands mid-query, the
        // entry is filed under the older count, so it's replaced on the next refresh.
        var fullKey = $"{Generation(ctx.Request)}|{key}";
        Entry entry;
        while (true)
        {
            // Lazy makes concurrent misses for a key share one query.
            var lazy = _entries.GetOrAdd(fullKey, k => new Lazy<Task<Entry>>(() => Compute(k, compute, type)));
            try
            {
                entry = await lazy.Value;
            }
            catch
            {
                _entries.TryRemove(fullKey, out _); // don't cache failures
                throw;
            }
            if (DateTime.UtcNow - entry.At <= Ttl) break;
            if (_entries.TryRemove(new KeyValuePair<string, Lazy<Task<Entry>>>(fullKey, lazy)))
                Interlocked.Add(ref _bytes, -(entry.Body.Length + fullKey.Length));
        }

        var response = ctx.Response;
        response.Headers.ETag = entry.ETag;
        response.Headers.CacheControl = "no-cache";
        if (ETagMatches(ctx.Request.Headers.IfNoneMatch, entry.ETag))
        {
            response.StatusCode = StatusCodes.Status304NotModified;
            return;
        }
        response.ContentType = "application/json";
        // A known length lets the compression middleware skip bodies under 32 bytes.
        response.ContentLength = entry.Body.Length;
        await response.Body.WriteAsync(entry.Body);
    }

    async Task<Entry> Compute<T>(string key, Func<Conn, T> compute, JsonTypeInfo<T> type)
    {
        var value = await db.Read(compute);
        var body = JsonSerializer.SerializeToUtf8Bytes(value, type);
        var etag = $"\"{Convert.ToHexStringLower(SHA1.HashData(body), 0, 8)}\"";
        _order.Enqueue(key);
        // Evict oldest entries past the size limit.
        if (Interlocked.Add(ref _bytes, body.Length + key.Length) > maxBytes)
        {
            while (Interlocked.Read(ref _bytes) > maxBytes && _order.TryDequeue(out var old))
            {
                if (_entries.TryRemove(old, out var gone) && gone.IsValueCreated && gone.Value.IsCompletedSuccessfully)
                    Interlocked.Add(ref _bytes, -(gone.Value.Result.Body.Length + old.Length));
            }
        }
        return new Entry(body, etag, DateTime.UtcNow);
    }

    static bool ETagMatches(string? header, string etag) =>
        header is { Length: > 0 } && header.Split(',').Any(t => t.Trim().TrimStart('W', '/') is var v && (v == "*" || v == etag));
}
