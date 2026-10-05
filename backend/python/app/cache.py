"""In-process response cache; same policy as the Rust backend's cache.rs.

Keys include a change count that's refreshed from the database at most once
per `max_staleness`, so other users see writes within ~1 s and the cache
empties at most once a second. `X-Fresh` requests key on the live count
(read-your-writes). Concurrent misses for a key share one query. Entries carry
an ETag for `If-None-Match` revalidation.

Each worker process has its own cache; they stay consistent because each one
detects changes through SQLite (see `Db.generation`), not a local counter.
"""

import hashlib
import threading
import time
from collections import OrderedDict
from collections.abc import Callable

from starlette.requests import Request
from starlette.responses import Response

from .db import Db

TTL_SECONDS = 30.0


class ResponseCache:
    def __init__(self, db: Db, max_bytes: int, max_staleness: float):
        self._db = db
        self._max_bytes = max_bytes
        self._max_staleness = max_staleness
        self._entries: OrderedDict[tuple[int, str], tuple[float, bytes, str]] = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()
        self._inflight: dict[tuple[int, str], threading.Lock] = {}
        self._published = 0
        self._published_at = float("-inf")

    def _generation(self, request: Request) -> int:
        if "x-fresh" in request.headers:
            return self._db.generation()
        now = time.monotonic()
        if now - self._published_at >= self._max_staleness:
            self._published = self._db.generation()
            self._published_at = now
        return self._published

    def json(self, request: Request, key: str, compute: Callable[[], bytes]) -> Response:
        """Serve `compute()`'s JSON bytes, from cache when the data hasn't changed.
        Runs on the event loop (the read handlers are async)."""
        full_key = (self._generation(request), key)
        entry = self._get(full_key)
        if entry is None:
            with self._lock:
                gate = self._inflight.setdefault(full_key, threading.Lock())
            with gate:  # one thread computes; the rest wait and reuse it
                entry = self._get(full_key)
                if entry is None:
                    body = compute()
                    etag = '"' + hashlib.blake2b(body, digest_size=8).hexdigest() + '"'
                    entry = (time.monotonic(), body, etag)
                    self._put(full_key, entry)
            with self._lock:
                self._inflight.pop(full_key, None)

        _, body, etag = entry
        headers = {"etag": etag, "cache-control": "no-cache"}
        if _etag_matches(request.headers.get("if-none-match"), etag):
            return Response(status_code=304, headers=headers)
        return Response(body, media_type="application/json", headers=headers)

    def _get(self, key):
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if time.monotonic() - entry[0] > TTL_SECONDS:
                self._drop(key)
                return None
            self._entries.move_to_end(key)
            return entry

    def _put(self, key, entry) -> None:
        with self._lock:
            if key in self._entries:
                self._drop(key)
            self._entries[key] = entry
            self._bytes += len(entry[1]) + len(key[1])
            while self._bytes > self._max_bytes and self._entries:
                self._drop(next(iter(self._entries)))

    def _drop(self, key) -> None:
        _, body, _ = self._entries.pop(key)
        self._bytes -= len(body) + len(key[1])


def _etag_matches(header: str | None, etag: str) -> bool:
    if not header:
        return False
    return any(t.strip().removeprefix("W/") in ("*", etag) for t in header.split(","))
