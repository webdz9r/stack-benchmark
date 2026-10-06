use std::path::PathBuf;

use address_book::{AppState, cache::ResponseCache, db::Db, database_path, routes};
use axum::Router;
use tower_http::compression::CompressionLayer;
use tower_http::services::{ServeDir, ServeFile};
use tower_http::trace::TraceLayer;
use tracing_subscriber::EnvFilter;

// jemalloc instead of the system allocator. On Linux (Docker), glibc's malloc
// cost ~25% of throughput on list pages; SQLite still uses the system malloc.
#[global_allocator]
static GLOBAL: tikv_jemallocator::Jemalloc = tikv_jemallocator::Jemalloc;

fn main() {
    // One read connection per core by default; DB_READERS overrides it (e.g. to
    // mimic a small VM together with TOKIO_WORKER_THREADS).
    let readers = std::env::var("DB_READERS")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or_else(|| std::thread::available_parallelism().map_or(4, |n| n.get() as u32));
    // Every query runs on the blocking pool. Tokio would grow it to 512 threads,
    // and under load ~80 of them queued for the read connections, each query
    // waking and parking several (3 context switches per request in Docker).
    // One thread per read connection lets them take queued work without
    // parking; writes and the checkpoint queue in the same pool.
    tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .max_blocking_threads(readers as usize)
        .build()
        .expect("failed to start the Tokio runtime")
        .block_on(run(readers));
}

async fn run(readers: u32) {
    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "address_book=info,tower_http=info".into()),
        )
        .init();

    let db_path = database_path();
    let db = Db::open(&db_path, readers).expect("failed to open database");
    tracing::info!(path = %db_path, readers, "database ready");

    // Keep the WAL from growing after bursts of writes; see `Db::checkpoint`.
    let checkpointer = db.clone();
    tokio::spawn(async move {
        let mut tick = tokio::time::interval(std::time::Duration::from_secs(5));
        loop {
            tick.tick().await;
            match checkpointer.checkpoint().await {
                Ok(cp) if cp.wal_pages > 0 => tracing::debug!(
                    wal_pages = cp.wal_pages, copied = cp.copied, truncated = cp.truncated, "checkpoint"
                ),
                Ok(_) => {}
                Err(e) => tracing::warn!("checkpoint failed: {e}"),
            }
        }
    });

    // Other users see a write within ~1 s; the writer sees it at once (X-Fresh).
    let cache = ResponseCache::new(64 * 1024 * 1024, std::time::Duration::from_secs(1));
    let state = AppState { db, cache };
    let mut app = Router::new().nest("/api", routes::api()).with_state(state);

    // In production the built frontend is served from the same process, so the
    // whole app is one binary plus one database file.
    let static_dir = PathBuf::from(
        std::env::var("STATIC_DIR").unwrap_or_else(|_| "../../frontend/dist".into()),
    );
    if static_dir.join("index.html").exists() {
        tracing::info!(dir = %static_dir.display(), "serving frontend");
        let spa = ServeDir::new(&static_dir)
            .fallback(ServeFile::new(static_dir.join("index.html")));
        app = app.fallback_service(spa);
    }

    // No CORS layer: the Vite dev server proxies /api, and in production the
    // frontend is same-origin, so other sites can't read your contacts.
    // gzip shrinks a 60-row list page from ~11.5 KB to ~1.7 KB.
    let app = app.layer(CompressionLayer::new()).layer(TraceLayer::new_for_http());

    let addr = std::env::var("BIND_ADDR").unwrap_or_else(|_| "127.0.0.1:7878".into());
    let listener = tokio::net::TcpListener::bind(&addr).await.expect("failed to bind");
    tracing::info!("listening on http://{addr}");
    axum::serve(listener, app)
        .with_graceful_shutdown(async {
            let _ = tokio::signal::ctrl_c().await;
        })
        .await
        .expect("server error");
}
