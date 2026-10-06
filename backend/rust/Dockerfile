# syntax=docker/dockerfile:1
# Rust reference backend (docs/requirements/07-containers.md).
# Build from the repo root: docker build -f backend/rust/Dockerfile -t stack-benchmark-rust .

FROM node:26-trixie-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json ./
RUN --mount=type=cache,target=/root/.npm npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM rust:1-slim-trixie AS build
# make builds the bundled jemalloc (tikv-jemalloc-sys).
RUN apt-get update && apt-get install -y --no-install-recommends make && rm -rf /var/lib/apt/lists/*
WORKDIR /app/backend/rust
COPY backend/migrations /app/backend/migrations
COPY backend/rust/ ./
# .cargo/config.toml (copied above) carries the SQLite build flags (DB-2).
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/app/backend/rust/target \
    cargo build --release --locked \
 && mkdir -p /out \
 && cp target/release/address-book target/release/seed /out/ \
 && grep -m1 '#define SQLITE_VERSION ' \
      "$(find /usr/local/cargo/registry/src -path '*libsqlite3-sys-*/sqlite3/sqlite3.c' | head -1)" \
    | cut -d'"' -f2 > /out/sqlite-version

FROM debian:trixie-slim
WORKDIR /app/backend/rust
COPY --from=build /out/address-book /out/seed ./
COPY --from=build /out/sqlite-version /app/sqlite-version
COPY --from=frontend /app/frontend/dist /app/frontend/dist
COPY backend/migrations /app/backend/migrations
COPY --chmod=755 <<'EOF' /usr/local/bin/entrypoint
#!/bin/sh
set -e
cmd="${1:-serve}"; [ $# -gt 0 ] && shift
case "$cmd" in
  serve) exec ./address-book "$@" ;;
  seed)  exec ./seed "$@" ;;
  *)     exec "$cmd" "$@" ;;
esac
EOF
ENTRYPOINT ["entrypoint"]
CMD ["serve"]
