# syntax=docker/dockerfile:1
# Go backend (docs/requirements/07-containers.md).
# Build from the repo root: docker build -f backend/go/Dockerfile -t stack-benchmark-go .

FROM node:26-trixie-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json ./
RUN --mount=type=cache,target=/root/.npm npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM golang:1-trixie AS build
WORKDIR /app/backend/go
COPY backend/go/go.mod backend/go/go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download
COPY backend/go/ ./
# Same flags as bench.json: keep -O2 (DB-2), FTS5 needs the build tag.
ENV CGO_CFLAGS="-O2 -g -DSQLITE_DEFAULT_MEMSTATUS=0"
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    go build -tags sqlite_fts5 -o /out/server ./cmd/server \
 && go build -tags sqlite_fts5 -o /out/seed ./cmd/seed \
 && grep -m1 '#define SQLITE_VERSION ' "$(find /go/pkg/mod/github.com/mattn -name sqlite3-binding.c | head -1)" \
    | cut -d'"' -f2 > /out/sqlite-version

FROM debian:trixie-slim
WORKDIR /app/backend/go
COPY --from=build /out/server /out/seed ./
COPY --from=build /out/sqlite-version /app/sqlite-version
COPY --from=frontend /app/frontend/dist /app/frontend/dist
COPY backend/migrations /app/backend/migrations
COPY --chmod=755 <<'EOT' /usr/local/bin/entrypoint
#!/bin/sh
set -e
cmd="${1:-serve}"; [ $# -gt 0 ] && shift
case "$cmd" in
  serve) exec ./server "$@" ;;
  seed)  exec ./seed "$@" ;;
  *)     exec "$cmd" "$@" ;;
esac
EOT
ENTRYPOINT ["entrypoint"]
CMD ["serve"]
