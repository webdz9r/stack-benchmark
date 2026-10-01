pub mod cache;
pub mod db;
pub mod error;
pub mod models;
pub mod repo;
pub mod routes;

use axum::extract::FromRef;

/// Shared state for the HTTP handlers.
#[derive(Clone)]
pub struct AppState {
    pub db: db::Db,
    pub cache: cache::ResponseCache,
}

impl FromRef<AppState> for db::Db {
    fn from_ref(state: &AppState) -> Self {
        state.db.clone()
    }
}

/// Database path from `DATABASE_PATH`, defaulting to `data/address-book.db`.
pub fn database_path() -> String {
    std::env::var("DATABASE_PATH").unwrap_or_else(|_| "data/address-book.db".into())
}
