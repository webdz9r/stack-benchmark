use axum::Json;
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use r2d2_sqlite::rusqlite::{self, ErrorCode};
use serde_json::json;

#[derive(Debug, Clone, thiserror::Error)]
pub enum AppError {
    #[error("not found")]
    NotFound,
    #[error("{0}")]
    Validation(String),
    #[error("{0}")]
    Conflict(String),
    #[error("internal error: {0}")]
    Internal(String),
}

impl AppError {
    pub fn internal(msg: impl Into<String>) -> Self {
        Self::Internal(msg.into())
    }
}

impl From<rusqlite::Error> for AppError {
    fn from(e: rusqlite::Error) -> Self {
        match e {
            rusqlite::Error::QueryReturnedNoRows => Self::NotFound,
            rusqlite::Error::SqliteFailure(f, _) if f.code == ErrorCode::ConstraintViolation => {
                Self::Conflict("that conflicts with an existing record".into())
            }
            other => Self::Internal(other.to_string()),
        }
    }
}

impl From<r2d2::Error> for AppError {
    fn from(e: r2d2::Error) -> Self {
        Self::Internal(format!("connection pool: {e}"))
    }
}

impl From<tokio::task::JoinError> for AppError {
    fn from(e: tokio::task::JoinError) -> Self {
        Self::Internal(format!("blocking task failed: {e}"))
    }
}

impl IntoResponse for AppError {
    fn into_response(self) -> Response {
        let status = match &self {
            Self::NotFound => StatusCode::NOT_FOUND,
            Self::Validation(_) => StatusCode::UNPROCESSABLE_ENTITY,
            Self::Conflict(_) => StatusCode::CONFLICT,
            Self::Internal(msg) => {
                tracing::error!("{msg}");
                StatusCode::INTERNAL_SERVER_ERROR
            }
        };
        let message = match self {
            Self::Internal(_) => "internal server error".to_string(),
            other => other.to_string(),
        };
        (status, Json(json!({ "error": message }))).into_response()
    }
}
