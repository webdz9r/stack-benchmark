package app

// In-process response cache; same policy as the Rust backend's cache.rs.
//
// Keys include a copy of the write count that catches up at most once per
// maxStaleness, so other users see writes within ~1 s and the cache empties at
// most once a second. X-Fresh requests key on the live count
// (read-your-writes). Concurrent misses for a key share one query
// (singleflight). Entries carry an ETag for If-None-Match revalidation.

import (
	"container/list"
	"crypto/sha1"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"golang.org/x/sync/singleflight"
)

const cacheTTL = 30 * time.Second

type cacheEntry struct {
	key  string
	body []byte
	etag string
	at   time.Time
}

type ResponseCache struct {
	db           *Db
	maxBytes     int
	maxStaleness time.Duration

	mu      sync.Mutex
	entries map[string]*list.Element
	lru     *list.List // front = most recently used
	bytes   int
	flight  singleflight.Group

	published   atomic.Uint64
	publishedAt atomic.Int64 // unix nanos
}

func NewResponseCache(db *Db, maxBytes int, maxStaleness time.Duration) *ResponseCache {
	return &ResponseCache{db: db, maxBytes: maxBytes, maxStaleness: maxStaleness,
		entries: map[string]*list.Element{}, lru: list.New()}
}

func (c *ResponseCache) generation(r *http.Request) uint64 {
	if r.Header.Get("X-Fresh") != "" {
		return c.db.Generation()
	}
	now := time.Now().UnixNano()
	if now-c.publishedAt.Load() >= int64(c.maxStaleness) {
		// Racing refreshes store near-identical values; either is fine.
		c.published.Store(c.db.Generation())
		c.publishedAt.Store(now)
	}
	return c.published.Load()
}

// JSON serves compute's result, from cache when the data hasn't changed.
func (c *ResponseCache) JSON(w http.ResponseWriter, r *http.Request, key string, compute func() (any, error)) {
	// Read the write count before querying: if a write lands mid-query, the
	// entry is filed under the older count, so it's replaced on the next refresh.
	fullKey := strconv.FormatUint(c.generation(r), 10) + "|" + key
	e := c.get(fullKey)
	if e == nil {
		v, err, _ := c.flight.Do(fullKey, func() (any, error) {
			if e := c.get(fullKey); e != nil {
				return e, nil
			}
			data, err := compute()
			if err != nil {
				return nil, err
			}
			body, err := json.Marshal(data)
			if err != nil {
				return nil, err
			}
			sum := sha1.Sum(body)
			e := &cacheEntry{key: fullKey, body: body, etag: `"` + hex.EncodeToString(sum[:8]) + `"`, at: time.Now()}
			c.put(e)
			return e, nil
		})
		if err != nil {
			writeError(w, err)
			return
		}
		e = v.(*cacheEntry)
	}

	h := w.Header()
	h.Set("ETag", e.etag)
	h.Set("Cache-Control", "no-cache")
	if etagMatches(r.Header.Get("If-None-Match"), e.etag) {
		w.WriteHeader(http.StatusNotModified)
		return
	}
	h.Set("Content-Type", "application/json")
	w.Write(e.body)
}

func (c *ResponseCache) get(key string) *cacheEntry {
	c.mu.Lock()
	defer c.mu.Unlock()
	el, ok := c.entries[key]
	if !ok {
		return nil
	}
	e := el.Value.(*cacheEntry)
	if time.Since(e.at) > cacheTTL {
		c.drop(el)
		return nil
	}
	c.lru.MoveToFront(el)
	return e
}

func (c *ResponseCache) put(e *cacheEntry) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if el, ok := c.entries[e.key]; ok {
		c.drop(el)
	}
	c.entries[e.key] = c.lru.PushFront(e)
	c.bytes += len(e.body) + len(e.key)
	for c.bytes > c.maxBytes && c.lru.Len() > 0 {
		c.drop(c.lru.Back())
	}
}

func (c *ResponseCache) drop(el *list.Element) {
	e := c.lru.Remove(el).(*cacheEntry)
	delete(c.entries, e.key)
	c.bytes -= len(e.body) + len(e.key)
}

func etagMatches(header, etag string) bool {
	for _, t := range strings.Split(header, ",") {
		t = strings.TrimPrefix(strings.TrimSpace(t), "W/")
		if t == "*" || t == etag {
			return true
		}
	}
	return false
}
