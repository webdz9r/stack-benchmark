# syntax=docker/dockerfile:1
# C backend (docs/requirements/07-containers.md).
# Build from the repo root: docker build -f backend/c/Dockerfile -t stack-benchmark-c .

FROM node:26-trixie-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json ./
RUN --mount=type=cache,target=/root/.npm npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM debian:trixie-slim AS build
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential pkg-config curl ca-certificates unzip \
      libmicrohttpd-dev libyyjson-dev zlib1g-dev \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app/backend/c
COPY backend/c/ ./
# The Makefile downloads the pinned SQLite amalgamation and keeps -O3 (DB-2).
RUN make -j"$(nproc)" server seed \
 && mkdir -p /out && cp server seed /out/ \
 && grep -m1 '#define SQLITE_VERSION ' vendor/*/sqlite3.c | cut -d'"' -f2 > /out/sqlite-version

FROM debian:trixie-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
      libmicrohttpd12t64 libyyjson0 zlib1g locales \
 && sed -i 's/^# *en_US.UTF-8/en_US.UTF-8/' /etc/locale.gen && locale-gen \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app/backend/c
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
