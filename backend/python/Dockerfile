# syntax=docker/dockerfile:1
# Python backend (docs/requirements/07-containers.md). sqlite3 links Debian's
# libsqlite3 here, so its SQLite version differs from native (see /app/sqlite-version).
# Build from the repo root: docker build -f backend/python/Dockerfile -t stack-benchmark-python .

FROM node:26-trixie-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json ./
RUN --mount=type=cache,target=/root/.npm npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.14-slim-trixie AS build
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PYTHON=/usr/local/bin/python3.14
WORKDIR /app/backend/python
COPY backend/python/pyproject.toml backend/python/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project

FROM python:3.14-slim-trixie
WORKDIR /app/backend/python
COPY --from=build /app/backend/python/.venv ./.venv
COPY backend/python/ ./
COPY --from=frontend /app/frontend/dist /app/frontend/dist
COPY backend/migrations /app/backend/migrations
RUN .venv/bin/python -c "import sqlite3; print(sqlite3.sqlite_version)" > /app/sqlite-version
# Host, port and workers come from UVICORN_HOST / UVICORN_PORT / UVICORN_WORKERS (bench.json).
COPY --chmod=755 <<'EOT' /usr/local/bin/entrypoint
#!/bin/sh
set -e
cmd="${1:-serve}"; [ $# -gt 0 ] && shift
case "$cmd" in
  serve) exec .venv/bin/uvicorn app.main:app --loop uvloop --http httptools --no-access-log "$@" ;;
  seed)  exec .venv/bin/python seed.py "$@" ;;
  *)     exec "$cmd" "$@" ;;
esac
EOT
ENTRYPOINT ["entrypoint"]
CMD ["serve"]
