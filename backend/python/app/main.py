"""FastAPI version of the address book API; same routes and JSON as the Rust backend.

    uv run uvicorn app.main:app --port 7879 --workers 4

Handlers are plain `def`: FastAPI runs them in a thread pool, and sqlite3
releases the GIL while SQLite executes, so queries overlap across threads.
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

import anyio.to_thread
import orjson
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.gzip import GZipMiddleware

from . import repo
from .cache import ResponseCache
from .db import Db
from .errors import AppError
from .models import ContactInput, FavoriteBody, TagInput

DATABASE_PATH = os.environ.get("DATABASE_PATH", "data/address-book.db")
# Threads per worker process running handlers (each gets a read connection).
THREADS = int(os.environ.get("DB_READERS", "4"))
STATIC_DIR = Path(os.environ.get("STATIC_DIR", "../../frontend/dist"))

db = Db(DATABASE_PATH)
cache = ResponseCache(db, max_bytes=64 * 1024 * 1024, max_staleness=1.0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    anyio.to_thread.current_default_thread_limiter().total_tokens = THREADS
    db.start_checkpointer()
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
# Level 6 and a 32-byte floor match tower-http's defaults on the Rust side.
app.add_middleware(GZipMiddleware, minimum_size=32, compresslevel=6)


def json(data, status: int = 200) -> Response:
    return Response(orjson.dumps(data), status_code=status, media_type="application/json")


@app.exception_handler(AppError)
async def app_error(_: Request, e: AppError):
    return json({"error": e.message}, e.status)


@app.exception_handler(RequestValidationError)
async def bad_request(_: Request, e: RequestValidationError):
    # Bad path/query values and malformed JSON are 400; a well-formed body with
    # wrong field types is 422 (spec §7).
    first = e.errors()[0] if e.errors() else {}
    loc = first.get("loc", ())
    status = 400 if (loc and loc[0] in ("path", "query")) or first.get("type") == "json_invalid" else 422
    return json({"error": first.get("msg", "invalid request")}, status)


@app.exception_handler(StarletteHTTPException)
async def http_error(_: Request, e: StarletteHTTPException):
    return json({"error": "not found" if e.status_code == 404 else str(e.detail)}, e.status_code)


# ---------------------------------------------------------------- reads


@app.get("/api/health")
def health():
    return PlainTextResponse("ok")


@app.get("/api/stats")
def stats(request: Request):
    return cache.json(request, "stats", lambda: orjson.dumps(repo.stats(db.reader())))


def _filter_key(q, tag, favorite) -> str:
    return f"{repo.fts_query(q) or ''}|{tag}|{favorite is True}"


@app.get("/api/contacts")
def list_contacts(
    request: Request,
    q: str | None = None,
    tag: int | None = None,
    favorite: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
):
    favorite = _favorite(favorite)
    def compute():
        return orjson.dumps(repo.list_contacts(db.reader(), q, tag, favorite, limit, offset))

    if tag is None and favorite is not True and repo.fts_query(q) is None:
        # Unfiltered pages walk the sort index and are cheap; not worth caching.
        return Response(compute(), media_type="application/json")
    key = f"list|{_filter_key(q, tag, favorite)}|{limit}|{offset}"
    return cache.json(request, key, compute)


def _favorite(value: str | None) -> bool:
    """Only the exact strings "true" and "false" are accepted (spec §7)."""
    if value not in (None, "true", "false"):
        raise AppError(400, "favorite must be true or false")
    return value == "true"


@app.get("/api/contacts/letters")
def list_letters(request: Request, q: str | None = None, tag: int | None = None, favorite: str | None = None):
    favorite = _favorite(favorite)
    return cache.json(
        request,
        f"letters|{_filter_key(q, tag, favorite)}",
        lambda: orjson.dumps(repo.list_letters(db.reader(), q, tag, favorite)),
    )


@app.get("/api/contacts/{contact_id}")
def get_contact(contact_id: int):
    return json(repo.get_contact(db.reader(), contact_id))


@app.get("/api/tags")
def list_tags(request: Request):
    return cache.json(request, "tags", lambda: orjson.dumps(repo.list_tags(db.reader())))


# ---------------------------------------------------------------- writes


@app.post("/api/contacts")
def create_contact(body: ContactInput):
    body = body.validated()
    with db.transaction() as tx:
        contact_id = repo.insert_contact(tx, body)
        contact = repo.get_contact(tx, contact_id)
    return json(contact, 201)


@app.put("/api/contacts/{contact_id}")
def update_contact(contact_id: int, body: ContactInput):
    body = body.validated()
    with db.transaction() as tx:
        repo.update_contact(tx, contact_id, body)
        contact = repo.get_contact(tx, contact_id)
    return json(contact)


@app.put("/api/contacts/{contact_id}/favorite")
def set_favorite(contact_id: int, body: FavoriteBody):
    with db.transaction() as tx:
        repo.set_favorite(tx, contact_id, body.favorite)
    return Response(status_code=204)


@app.delete("/api/contacts/{contact_id}")
def delete_contact(contact_id: int):
    with db.transaction() as tx:
        repo.delete_contact(tx, contact_id)
    return Response(status_code=204)


@app.post("/api/tags")
def create_tag(body: TagInput):
    body = body.validated()
    with db.transaction() as tx:
        tag = repo.insert_tag(tx, body)
    return json(tag, 201)


@app.put("/api/tags/{tag_id}")
def update_tag(tag_id: int, body: TagInput):
    body = body.validated()
    with db.transaction() as tx:
        tag = repo.update_tag(tx, tag_id, body)
    return json(tag)


@app.delete("/api/tags/{tag_id}")
def delete_tag(tag_id: int):
    with db.transaction() as tx:
        repo.delete_tag(tx, tag_id)
    return Response(status_code=204)


class SpaStaticFiles(StaticFiles):
    """Serve the built frontend; paths that aren't files get index.html (the SPA
    fallback), except under /api, which stay JSON 404s."""

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as e:
            if e.status_code != 404 or path == "api" or path.startswith("api/"):
                raise
            return FileResponse(STATIC_DIR / "index.html")


# Serve the built frontend, like the Rust binary does.
if (STATIC_DIR / "index.html").exists():
    app.mount("/", SpaStaticFiles(directory=STATIC_DIR, html=True), name="frontend")
