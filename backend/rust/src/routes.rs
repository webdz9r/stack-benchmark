use axum::extract::{Path, Query, State};
use axum::http::{HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, put};
use axum::{Json, Router};
use serde::Deserialize;

use crate::AppState;
use crate::db::Db;
use crate::error::AppError;
use crate::models::*;
use crate::repo;

pub fn api() -> Router<AppState> {
    Router::new()
        .route("/health", get(|| async { "ok" }))
        .route("/stats", get(stats))
        .route("/contacts", get(list_contacts).post(create_contact))
        .route("/contacts/letters", get(list_letters))
        .route(
            "/contacts/{id}",
            get(get_contact).put(update_contact).delete(delete_contact),
        )
        .route("/contacts/{id}/favorite", put(set_favorite))
        .route("/tags", get(list_tags).post(create_tag))
        .route("/tags/{id}", put(update_tag).delete(delete_tag))
        // Unknown /api paths get a JSON 404 rather than the SPA's index.html.
        .fallback(|| async { AppError::NotFound })
}

async fn stats(State(s): State<AppState>, headers: HeaderMap) -> Result<Response, AppError> {
    s.cache.json(&s.db, &headers, "stats".into(), repo::stats).await
}

/// Cache key for a filtered query; search text is normalized first, so
/// "Smith" and "smith " share an entry.
fn filter_key(q: &ListQuery) -> String {
    let search = q.q.as_deref().and_then(repo::fts_query).unwrap_or_default();
    format!("{search}|{:?}|{}", q.tag, q.favorite == Some(true))
}

async fn list_contacts(
    State(s): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<ListQuery>,
) -> Result<Response, AppError> {
    let filtered = q.tag.is_some()
        || q.favorite == Some(true)
        || q.q.as_deref().and_then(repo::fts_query).is_some();
    if !filtered {
        // Unfiltered pages walk the sort index and take ~0.5 ms; not worth caching.
        return Ok(Json(s.db.read(move |c| repo::list_contacts(c, &q)).await?).into_response());
    }
    let key = format!("list|{}|{:?}|{:?}", filter_key(&q), q.limit, q.offset);
    s.cache.json(&s.db, &headers, key, move |c| repo::list_contacts(c, &q)).await
}

async fn list_letters(
    State(s): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<ListQuery>,
) -> Result<Response, AppError> {
    let key = format!("letters|{}", filter_key(&q));
    s.cache.json(&s.db, &headers, key, move |c| repo::list_letters(c, &q)).await
}

async fn get_contact(State(db): State<Db>, Path(id): Path<i64>) -> Result<Json<Contact>, AppError> {
    Ok(Json(db.read(move |c| repo::get_contact(c, id)).await?))
}

async fn create_contact(
    State(db): State<Db>,
    Json(input): Json<ContactInput>,
) -> Result<(StatusCode, Json<Contact>), AppError> {
    let input = input.validate()?;
    let contact = db
        .write(move |c| {
            let tx = c.transaction()?;
            let id = repo::insert_contact(&tx, &input)?;
            let contact = repo::get_contact(&tx, id)?;
            tx.commit()?;
            Ok(contact)
        })
        .await?;
    Ok((StatusCode::CREATED, Json(contact)))
}

async fn update_contact(
    State(db): State<Db>,
    Path(id): Path<i64>,
    Json(input): Json<ContactInput>,
) -> Result<Json<Contact>, AppError> {
    let input = input.validate()?;
    let contact = db
        .write(move |c| {
            let tx = c.transaction()?;
            repo::update_contact(&tx, id, &input)?;
            let contact = repo::get_contact(&tx, id)?;
            tx.commit()?;
            Ok(contact)
        })
        .await?;
    Ok(Json(contact))
}

#[derive(Deserialize)]
struct FavoriteBody {
    favorite: bool,
}

async fn set_favorite(
    State(db): State<Db>,
    Path(id): Path<i64>,
    Json(body): Json<FavoriteBody>,
) -> Result<StatusCode, AppError> {
    db.write(move |c| repo::set_favorite(c, id, body.favorite)).await?;
    Ok(StatusCode::NO_CONTENT)
}

async fn delete_contact(State(db): State<Db>, Path(id): Path<i64>) -> Result<StatusCode, AppError> {
    db.write(move |c| {
        let tx = c.transaction()?;
        repo::delete_contact(&tx, id)?;
        tx.commit()?;
        Ok(())
    })
    .await?;
    Ok(StatusCode::NO_CONTENT)
}

async fn list_tags(State(s): State<AppState>, headers: HeaderMap) -> Result<Response, AppError> {
    s.cache.json(&s.db, &headers, "tags".into(), repo::list_tags).await
}

async fn create_tag(
    State(db): State<Db>,
    Json(input): Json<TagInput>,
) -> Result<(StatusCode, Json<Tag>), AppError> {
    let input = input.validate()?;
    let tag = db.write(move |c| repo::insert_tag(c, &input)).await?;
    Ok((StatusCode::CREATED, Json(tag)))
}

async fn update_tag(
    State(db): State<Db>,
    Path(id): Path<i64>,
    Json(input): Json<TagInput>,
) -> Result<Json<Tag>, AppError> {
    let input = input.validate()?;
    Ok(Json(db.write(move |c| repo::update_tag(c, id, &input)).await?))
}

async fn delete_tag(State(db): State<Db>, Path(id): Path<i64>) -> Result<StatusCode, AppError> {
    db.write(move |c| repo::delete_tag(c, id)).await?;
    Ok(StatusCode::NO_CONTENT)
}
