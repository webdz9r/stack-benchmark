package addressbook;

import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.locks.ReentrantLock;
import java.util.function.Supplier;

/**
 * Serialized JSON bodies keyed by (generation, key) (04-caching-and-http.md §2):
 * LRU bounded by bytes that always admits new entries, a TTL from insertion, and
 * one computation per key for concurrent misses.
 */
public final class ResponseCache {
    private record Key(long generation, String key) {
    }

    private record Entry(byte[] body, long size, long expiresAt) {
    }

    private final long maxBytes;
    private final long ttlNanos;
    private final ReentrantLock lock = new ReentrantLock();
    private final LinkedHashMap<Key, Entry> entries = new LinkedHashMap<>(1024, 0.75f, true);
    private final ConcurrentHashMap<Key, CompletableFuture<byte[]>> inflight = new ConcurrentHashMap<>();
    private long bytes;

    public ResponseCache(long maxBytes, long ttlMillis) {
        this.maxBytes = maxBytes;
        this.ttlNanos = ttlMillis * 1_000_000L;
    }

    public byte[] get(long generation, String key, Supplier<byte[]> compute) {
        Key k = new Key(generation, key);
        byte[] hit = lookup(k);
        if (hit != null) {
            return hit;
        }
        CompletableFuture<byte[]> mine = new CompletableFuture<>();
        CompletableFuture<byte[]> running = inflight.putIfAbsent(k, mine);
        if (running != null) {
            try {
                return running.join();
            } catch (CompletionException e) {
                throw e.getCause() instanceof RuntimeException re ? re : e;
            }
        }
        try {
            byte[] body = compute.get();
            insert(k, body);
            mine.complete(body);
            return body;
        } catch (RuntimeException e) {
            mine.completeExceptionally(e);
            throw e;
        } finally {
            inflight.remove(k, mine);
        }
    }

    private byte[] lookup(Key k) {
        lock.lock();
        try {
            Entry e = entries.get(k);
            if (e == null) {
                return null;
            }
            if (System.nanoTime() - e.expiresAt >= 0) {
                entries.remove(k);
                bytes -= e.size;
                return null;
            }
            return e.body;
        } finally {
            lock.unlock();
        }
    }

    private void insert(Key k, byte[] body) {
        long size = k.key.length() + body.length;
        long now = System.nanoTime();
        lock.lock();
        try {
            Entry old = entries.put(k, new Entry(body, size, now + ttlNanos));
            if (old != null) {
                bytes -= old.size;
            }
            bytes += size;
            // From the least recently used end: drop expired entries, then evict until under the limit.
            Iterator<Map.Entry<Key, Entry>> it = entries.entrySet().iterator();
            while (it.hasNext()) {
                Map.Entry<Key, Entry> eldest = it.next();
                boolean expired = now - eldest.getValue().expiresAt >= 0;
                if (!expired && bytes <= maxBytes) {
                    break;
                }
                if (eldest.getKey().equals(k)) {
                    continue;
                }
                bytes -= eldest.getValue().size;
                it.remove();
            }
        } finally {
            lock.unlock();
        }
    }
}
