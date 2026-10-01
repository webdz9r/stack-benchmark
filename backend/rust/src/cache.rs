//! In-process cache of serialized JSON responses for the expensive reads.
//!
//! Invalidation: `Db` counts writes, and every cache key includes a *published*
//! copy of that count, which catches up with the real one at most once per
//! `max_staleness`. Other users therefore see a write within about a second,
//! and the cache empties at most once a second instead of on every write
//! (flushing per write collapsed the hit rate at just 8 writes/s in load
//! tests). Older entries become unreachable and age out via the size limit or
//! TTL. The TTL also covers writes that bypass the server (the seeder, a manual
//! `sqlite3` session), which the count misses.
//!
//! Read-your-writes: a request with an `X-Fresh` header is keyed on the live
//! count instead, so it always reflects every write so far. The frontend sends
//! it for a couple of seconds after the user saves something.
//!
//! Concurrent misses for the same key share a single query.
//!
//! Responses carry an ETag (a hash of the body), so browsers revalidate with
//! `If-None-Match` and get an empty 304 when nothing changed.

use std::hash::{DefaultHasher, Hash, Hasher};
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Duration, Instant};

use axum::body::Bytes;
use axum::http::{HeaderMap, HeaderValue, StatusCode, header};
use axum::response::{IntoResponse, Response};
use moka::future::Cache;
use moka::policy::EvictionPolicy;
use r2d2_sqlite::rusqlite::Connection;
use serde::Serialize;

use crate::db::Db;
use crate::error::AppError;

#[derive(Clone)]
struct Entry {
    body: Bytes,
    etag: HeaderValue,
}

#[derive(Clone)]
pub struct ResponseCache {
    entries: Cache<(u64, String), Entry>,
    published: Arc<Published>,
}

/// The write count cache keys use, refreshed from `Db` at most every `max_staleness`.
struct Published {
    generation: AtomicU64,
    at_ms: AtomicU64, // when `generation` was last refreshed, relative to `epoch`
    epoch: Instant,
    max_staleness: Duration,
}

impl ResponseCache {
    pub fn new(max_bytes: u64, max_staleness: Duration) -> Self {
        let entries = Cache::builder()
            .max_capacity(max_bytes)
            .weigher(|(_, key): &(u64, String), e: &Entry| (key.len() + e.body.len()) as u32)
            .time_to_live(Duration::from_secs(30))
            // Plain LRU, not moka's default TinyLFU. Every generation bump makes
            // all keys new (frequency zero), so TinyLFU admission would reject
            // them in favour of stale entries that can never be hit again.
            .eviction_policy(EvictionPolicy::lru())
            .build();
        let published = Arc::new(Published {
            generation: AtomicU64::new(0),
            at_ms: AtomicU64::new(0),
            epoch: Instant::now(),
            max_staleness,
        });
        Self { entries, published }
    }

    /// The write count to key this request on.
    fn generation(&self, db: &Db, request_headers: &HeaderMap) -> u64 {
        if request_headers.contains_key("x-fresh") {
            return db.generation();
        }
        let p = &self.published;
        let now = p.epoch.elapsed().as_millis() as u64;
        if now.saturating_sub(p.at_ms.load(Ordering::Acquire)) >= p.max_staleness.as_millis() as u64 {
            // Racing refreshes store near-identical values; either is fine.
            p.generation.store(db.generation(), Ordering::Release);
            p.at_ms.store(now, Ordering::Release);
        }
        p.generation.load(Ordering::Acquire)
    }

    /// Serve `query`'s result as JSON, from cache when the data hasn't changed.
    pub async fn json<T, F>(
        &self,
        db: &Db,
        request_headers: &HeaderMap,
        key: String,
        query: F,
    ) -> Result<Response, AppError>
    where
        T: Serialize + Send + 'static,
        F: FnOnce(&Connection) -> Result<T, AppError> + Send + 'static,
    {
        // Read the write count before querying: if a write lands mid-query, the
        // entry is filed under the older count, so it's replaced on the next refresh.
        let key = (self.generation(db, request_headers), key);
        let entry = self
            .entries
            .try_get_with(key, async {
                let body = db
                    .read(move |c| {
                        serde_json::to_vec(&query(c)?).map_err(|e| AppError::internal(e.to_string()))
                    })
                    .await?;
                Ok::<_, AppError>(Entry::new(body))
            })
            .await
            .map_err(|e: Arc<AppError>| (*e).clone())?;

        let headers = [
            (header::ETAG, entry.etag.clone()),
            // Store, but check with the server before reusing.
            (header::CACHE_CONTROL, HeaderValue::from_static("no-cache")),
        ];
        if etag_matches(request_headers, &entry.etag) {
            return Ok((StatusCode::NOT_MODIFIED, headers).into_response());
        }
        let content_type = (header::CONTENT_TYPE, HeaderValue::from_static("application/json"));
        Ok((headers, [content_type], entry.body).into_response())
    }
}

impl Entry {
    fn new(body: Vec<u8>) -> Self {
        let mut hasher = DefaultHasher::new();
        body.hash(&mut hasher);
        let etag = HeaderValue::from_str(&format!("\"{:016x}\"", hasher.finish()))
            .expect("hex is a valid header value");
        Self { body: Bytes::from(body), etag }
    }
}

fn etag_matches(headers: &HeaderMap, etag: &HeaderValue) -> bool {
    let Some(Ok(value)) = headers.get(header::IF_NONE_MATCH).map(|v| v.to_str()) else {
        return false;
    };
    let etag = etag.to_str().unwrap_or_default();
    value.split(',').map(|t| t.trim().trim_start_matches("W/")).any(|t| t == "*" || t == etag)
}
