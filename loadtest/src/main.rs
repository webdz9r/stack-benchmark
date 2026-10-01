//! Simulated-user load test for the address book API.
//!
//!     cargo run --release -- users=2000 duration=60 think=3000
//!     cargo run --release -- users=64 think=0          # max throughput
//!
//! Each virtual user opens the app, then loops: pause ("think"), do one action
//! the way the UI would (the same requests, fired the same way), repeat.
//! Only requests started after the warm-up are measured.

use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use serde_json::Value;

const SEARCH_TERMS: &[&str] = &[
    "smith", "martinez", "walsh", "nguyen", "patel", "kim", "garcia", "okafor", "tanaka",
    "o'brien", "andersen", "kowalski", "cohen", "sato", "fischer", "reyes", "zhou", "larsen",
    "olivia", "noah", "priya", "hiroshi", "fatima", "diego", "grace", "marcus", "nadia", "theo",
    "austin", "portland", "denver", "toronto", "berlin", "sydney", "london", "seattle",
    "acme", "globex", "initech", "hooli", "wonka", "dunder", "oscorp", "umbrella",
    "ava walsh", "jo smi", "emma aus",
    // Not "555" or "example.com": in the seed data every phone and email
    // contains them, so they'd match (and sort) all 110k contacts.
];

struct Config {
    url: String,
    users: usize,
    duration: Duration,
    warmup: Duration,
    think_ms: u64,
    max_id: u64,
    /// Percent of actions that edit a contact.
    edit_pct: u64,
    /// If set, every user just GETs this API path in a loop (single-endpoint benchmark).
    endpoint: Option<String>,
    /// If set, also write the results as JSON to this file (used by bench/run.py).
    json: Option<String>,
}

impl Config {
    fn from_args() -> Self {
        let args: HashMap<String, String> = std::env::args()
            .skip(1)
            .filter_map(|a| a.split_once('=').map(|(k, v)| (k.to_string(), v.to_string())))
            .collect();
        let get = |k: &str, d: &str| args.get(k).cloned().unwrap_or_else(|| d.to_string());
        Config {
            url: get("url", "http://127.0.0.1:7878"),
            users: get("users", "1000").parse().expect("users"),
            duration: Duration::from_secs(get("duration", "40").parse().expect("duration")),
            warmup: Duration::from_secs(get("warmup", "10").parse().expect("warmup")),
            think_ms: get("think", "3000").parse().expect("think"),
            max_id: get("max_id", "110000").parse().expect("max_id"),
            edit_pct: get("edits", "5").parse().expect("edits"),
            endpoint: args.get("endpoint").cloned(),
            json: args.get("json").cloned(),
        }
    }
}

#[derive(Default)]
struct Stats {
    latencies: HashMap<&'static str, Vec<u32>>, // microseconds
    errors: HashMap<String, u64>,
    actions: u64,
    not_modified: u64,
}

#[derive(Clone)]
struct Ctx {
    cfg: Arc<Config>,
    http: reqwest::Client,
    stats: Arc<Mutex<Stats>>,
    /// Per-user browser cache: URL -> (ETag, body), revalidated with If-None-Match.
    etags: Arc<Mutex<HashMap<String, (String, Value)>>>,
    /// Like the UI: reads within 2 s of this user's last write send X-Fresh.
    last_write: Arc<Mutex<Option<Instant>>>,
    measure_from: Instant,
    stop_at: Instant,
}

impl Ctx {
    async fn get(&self, kind: &'static str, path: &str) -> Option<Value> {
        let url = format!("{}/api{}", self.cfg.url, path);
        let mut req = self.http.get(&url);
        if let Some((etag, _)) = self.etags.lock().unwrap().get(&url) {
            req = req.header("If-None-Match", etag.as_str());
        }
        if self.last_write.lock().unwrap().is_some_and(|t| t.elapsed() < Duration::from_secs(2)) {
            req = req.header("X-Fresh", "1");
        }
        self.send_inner(kind, req, Some(url)).await
    }

    async fn send(&self, kind: &'static str, req: reqwest::RequestBuilder) -> Option<Value> {
        let result = self.send_inner(kind, req, None).await;
        *self.last_write.lock().unwrap() = Some(Instant::now());
        result
    }

    async fn send_inner(&self, kind: &'static str, req: reqwest::RequestBuilder, url: Option<String>) -> Option<Value> {
        let started = Instant::now();
        let result = async {
            let res = req.send().await.map_err(|e| format!("{kind}: connect/send: {}", error_chain(&e)))?;
            let status = res.status();
            let etag = res.headers().get("etag").and_then(|v| v.to_str().ok()).map(str::to_string);
            let body = res.bytes().await.map_err(|e| format!("{kind}: body: {e}"))?;
            if status.as_u16() == 304 {
                let cached = url.as_ref().and_then(|u| self.etags.lock().unwrap().get(u).map(|(_, v)| v.clone()));
                if started >= self.measure_from {
                    self.stats.lock().unwrap().not_modified += 1;
                }
                return Ok(cached.unwrap_or(Value::Null));
            }
            if !status.is_success() {
                return Err(format!("{kind}: HTTP {}", status.as_u16()));
            }
            let value = if body.is_empty() { Value::Null } else { serde_json::from_slice(&body).unwrap_or(Value::Null) };
            if let (Some(url), Some(etag)) = (url, etag) {
                self.etags.lock().unwrap().insert(url, (etag, value.clone()));
            }
            Ok(value)
        }
        .await;
        let elapsed = started.elapsed().as_micros() as u32;
        if started >= self.measure_from && started < self.stop_at {
            let mut s = self.stats.lock().unwrap();
            match &result {
                Ok(_) => s.latencies.entry(kind).or_default().push(elapsed),
                Err(e) => *s.errors.entry(e.clone()).or_default() += 1,
            }
        }
        result.ok()
    }
}

/// Small xorshift PRNG, seeded per user.
struct Rng(u64);
impl Rng {
    fn next(&mut self) -> u64 {
        self.0 ^= self.0 << 13;
        self.0 ^= self.0 >> 7;
        self.0 ^= self.0 << 17;
        self.0
    }
    fn below(&mut self, n: u64) -> u64 {
        self.next() % n.max(1)
    }
    fn percent(&mut self) -> u64 {
        self.below(100)
    }
    /// Exponentially distributed pause with the given mean, so users don't move in lockstep.
    fn think(&mut self, mean_ms: u64) -> Duration {
        if mean_ms == 0 {
            return Duration::ZERO;
        }
        let u = (self.below(1_000_000) as f64 + 1.0) / 1_000_001.0;
        Duration::from_millis(((-u.ln()) * mean_ms as f64).min(mean_ms as f64 * 5.0) as u64)
    }
}

fn filter_query(filter: &str, q: &str) -> String {
    let mut s = String::from(filter);
    if !q.is_empty() {
        s.push_str("&q=");
        s.push_str(&q.replace(' ', "%20").replace('\'', "%27"));
    }
    s
}

/// What the UI does on a fresh list load: page + letter index, in parallel.
async fn load_list(ctx: &Ctx, kind: (&'static str, &'static str), filter: &str, offset: u64) -> Vec<(String, u64)> {
    let page = format!("/contacts?limit=60&offset={offset}{filter}");
    let index = format!("/contacts/letters?{}", filter.trim_start_matches('&'));
    let (_, letters) = tokio::join!(ctx.get(kind.0, &page), ctx.get(kind.1, &index));
    letters
        .and_then(|v| v.as_array().cloned())
        .unwrap_or_default()
        .iter()
        .filter_map(|l| Some((l["letter"].as_str()?.to_string(), l["offset"].as_u64()?)))
        .collect()
}

/// Single-endpoint mode: full responses every time (no ETag revalidation).
async fn hammer(ctx: Ctx, path: String) {
    let url = format!("{}/api{}", ctx.cfg.url, path);
    while Instant::now() < ctx.stop_at {
        ctx.send_inner("endpoint", ctx.http.get(&url), None).await;
    }
}

async fn user(ctx: Ctx, id: u64) {
    let mut rng = Rng(0x9E37_79B9_7F4A_7C15 ^ (id + 1).wrapping_mul(0x2545_F491_4F6C_DD1D));
    // Stagger arrivals so users don't all open the app in the same instant.
    tokio::time::sleep(rng.think(ctx.cfg.think_ms.min(3000))).await;

    // Open the app.
    let mut filter = String::new();
    let (_, _, mut letters) = tokio::join!(
        ctx.get("tags", "/tags"),
        ctx.get("stats", "/stats"),
        load_list(&ctx, ("list", "letters"), "", 0),
    );
    let mut offset = 0;

    while Instant::now() < ctx.stop_at {
        tokio::time::sleep(rng.think(ctx.cfg.think_ms)).await;
        if Instant::now() >= ctx.stop_at {
            break;
        }
        // The last `edit_pct` percent of rolls are edits; the rest keep the mix.
        let roll = rng.percent();
        let edit = roll >= 100 - ctx.cfg.edit_pct.min(100);
        let roll = if edit { 100 } else { roll * 95 / (100 - ctx.cfg.edit_pct.min(99)) };
        if roll < 20 {
            // Scroll: next page of the current view.
            offset += 60;
            ctx.get("list", &format!("/contacts?limit=60&offset={offset}{filter}")).await;
        } else if roll < 35 {
            // Jump with the A–Z rail (letter index is already loaded).
            if !letters.is_empty() {
                offset = letters[rng.below(letters.len() as u64) as usize].1;
                ctx.get("list", &format!("/contacts?limit=60&offset={offset}{filter}")).await;
            }
        } else if roll < 65 {
            // Search, typed: the debounce lets through a request at a couple of pauses.
            let term = SEARCH_TERMS[rng.below(SEARCH_TERMS.len() as u64) as usize];
            let chars: Vec<char> = term.chars().collect();
            let mut cuts = vec![chars.len()];
            if chars.len() > 4 && rng.percent() < 60 {
                cuts.insert(0, 3);
            }
            for cut in cuts {
                let q: String = chars[..cut].iter().collect();
                letters = load_list(&ctx, ("search", "search-letters"), &filter_query(&filter, &q), 0).await;
                // Typing pause; skipped in saturation runs (think=0) so the
                // generator never caps throughput below what the server can do.
                if ctx.cfg.think_ms > 0 {
                    tokio::time::sleep(Duration::from_millis(150)).await;
                }
            }
            offset = 0;
        } else if roll < 90 {
            // Open a contact.
            ctx.get("contact", &format!("/contacts/{}", 1 + rng.below(ctx.cfg.max_id))).await;
        } else if roll < 95 && !edit {
            // Switch view: favorites, a tag, or back to all.
            filter = match rng.below(3) {
                0 => "&favorite=true".to_string(),
                1 => format!("&tag={}", 1 + rng.below(6)),
                _ => String::new(),
            };
            offset = 0;
            letters = load_list(&ctx, ("list", "letters"), &filter, 0).await;
        } else {
            // Edit: open a contact, save it, and the UI refreshes list + sidebar.
            let cid = 1 + rng.below(ctx.cfg.max_id);
            if let Some(Value::Object(mut c)) = ctx.get("contact", &format!("/contacts/{cid}")).await {
                let tag_ids: Vec<Value> = c["tags"].as_array().map(|t| t.iter().map(|t| t["id"].clone()).collect()).unwrap_or_default();
                c.insert("tag_ids".into(), Value::Array(tag_ids));
                let put = ctx.http.put(format!("{}/api/contacts/{cid}", ctx.cfg.url)).json(&c);
                if ctx.send("write", put).await.is_some() {
                    let (_, _, l) = tokio::join!(
                        ctx.get("tags", "/tags"),
                        ctx.get("stats", "/stats"),
                        load_list(&ctx, ("list", "letters"), &filter, offset),
                    );
                    letters = l;
                }
            }
        }
        if Instant::now() >= ctx.measure_from {
            ctx.stats.lock().unwrap().actions += 1;
        }
    }
}

/// "outer: cause: root cause", so a failed request says why (reset, refused, timeout...).
fn error_chain(e: &dyn std::error::Error) -> String {
    let mut text = e.to_string();
    let mut source = e.source();
    while let Some(s) = source {
        text.push_str(": ");
        text.push_str(&s.to_string());
        source = s.source();
    }
    text
}

fn pct(sorted: &[u32], p: f64) -> f64 {
    if sorted.is_empty() {
        return 0.0;
    }
    sorted[((sorted.len() - 1) as f64 * p) as usize] as f64 / 1000.0
}

#[tokio::main]
async fn main() {
    let cfg = Arc::new(Config::from_args());
    let http = reqwest::Client::builder()
        .gzip(true)
        .pool_max_idle_per_host(usize::MAX)
        .timeout(Duration::from_secs(30))
        .build()
        .unwrap();

    let start = Instant::now();
    let ctx = Ctx {
        measure_from: start + cfg.warmup,
        stop_at: start + cfg.warmup + cfg.duration,
        cfg: cfg.clone(),
        http,
        stats: Arc::new(Mutex::new(Stats::default())),
        etags: Arc::default(),
        last_write: Arc::default(),
    };
    println!(
        "{} users, think {} ms, edits {}%, warm-up {}s, measuring {}s against {}",
        cfg.users, cfg.think_ms, cfg.edit_pct, cfg.warmup.as_secs(), cfg.duration.as_secs(), cfg.url
    );

    let tasks: Vec<_> = (0..cfg.users as u64)
        .map(|i| {
            let ctx = Ctx { etags: Arc::default(), last_write: Arc::default(), ..ctx.clone() };
            match cfg.endpoint.clone() {
                Some(path) => tokio::spawn(hammer(ctx, path)),
                None => tokio::spawn(user(ctx, i)),
            }
        })
        .collect();
    for t in tasks {
        let _ = t.await;
    }

    let stats = ctx.stats.lock().unwrap();
    let secs = cfg.duration.as_secs_f64();
    let mut all: Vec<u32> = stats.latencies.values().flatten().copied().collect();
    all.sort_unstable();
    let errors: u64 = stats.errors.values().sum();

    println!("\n{:<16} {:>9} {:>9} {:>8} {:>8} {:>8} {:>8}", "request", "count", "req/s", "p50 ms", "p95 ms", "p99 ms", "max ms");
    let mut kinds: Vec<_> = stats.latencies.iter().collect();
    kinds.sort_by_key(|(k, v)| (std::cmp::Reverse(v.len()), **k));
    for (kind, v) in kinds {
        let mut v = v.clone();
        v.sort_unstable();
        println!(
            "{:<16} {:>9} {:>9.0} {:>8.1} {:>8.1} {:>8.1} {:>8.1}",
            kind, v.len(), v.len() as f64 / secs, pct(&v, 0.5), pct(&v, 0.95), pct(&v, 0.99), pct(&v, 1.0)
        );
    }
    println!(
        "{:<16} {:>9} {:>9.0} {:>8.1} {:>8.1} {:>8.1} {:>8.1}",
        "ALL", all.len(), all.len() as f64 / secs, pct(&all, 0.5), pct(&all, 0.95), pct(&all, 0.99), pct(&all, 1.0)
    );
    let total = all.len() as f64;
    println!(
        "\nuser actions/s: {:.0}   errors: {errors}   304 Not Modified: {} ({:.0}%)",
        stats.actions as f64 / secs, stats.not_modified, 100.0 * stats.not_modified as f64 / total.max(1.0)
    );
    for (e, n) in stats.errors.iter().take(5) {
        println!("  {n} × {e}");
    }
    println!("RESULT users={} req_s={:.0} p50={:.1} p95={:.1} p99={:.1} errors={}", cfg.users, all.len() as f64 / secs, pct(&all, 0.5), pct(&all, 0.95), pct(&all, 0.99), errors);

    if let Some(path) = &cfg.json {
        let summarize = |v: &[u32]| {
            serde_json::json!({
                "count": v.len(),
                "req_s": v.len() as f64 / secs,
                "p50_ms": pct(v, 0.5), "p95_ms": pct(v, 0.95), "p99_ms": pct(v, 0.99), "max_ms": pct(v, 1.0),
            })
        };
        let kinds: serde_json::Map<String, serde_json::Value> = stats
            .latencies
            .iter()
            .map(|(k, v)| {
                let mut v = v.clone();
                v.sort_unstable();
                (k.to_string(), summarize(&v))
            })
            .collect();
        let report = serde_json::json!({
            "users": cfg.users,
            "think_ms": cfg.think_ms,
            "edit_pct": cfg.edit_pct,
            "warmup_s": cfg.warmup.as_secs(),
            "duration_s": cfg.duration.as_secs(),
            "endpoint": cfg.endpoint,
            "all": summarize(&all),
            "errors": errors,
            "error_samples": stats.errors.iter().take(5).map(|(e, n)| format!("{n} × {e}")).collect::<Vec<_>>(),
            "not_modified": stats.not_modified,
            "actions_per_s": stats.actions as f64 / secs,
            "kinds": kinds,
        });
        std::fs::write(path, serde_json::to_string_pretty(&report).unwrap()).expect("write json");
    }
}
