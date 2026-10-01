# syntax=docker/dockerfile:1
# Node backend (docs/requirements/07-containers.md).
# Build from the repo root: docker build -f backend/node/Dockerfile -t stack-benchmark-node .

FROM node:26-trixie-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json ./
RUN --mount=type=cache,target=/root/.npm npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# The full image has python3, make and g++ in case better-sqlite3 must compile.
FROM node:26-trixie AS build
WORKDIR /app/backend/node
COPY backend/node/package.json backend/node/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --omit=dev --no-audit --no-fund

FROM node:26-trixie-slim
WORKDIR /app/backend/node
COPY --from=build /app/backend/node/node_modules ./node_modules
COPY backend/node/ ./
COPY --from=frontend /app/frontend/dist /app/frontend/dist
COPY backend/migrations /app/backend/migrations
RUN node -e "console.log(require('better-sqlite3')(':memory:').prepare('select sqlite_version() v').get().v)" > /app/sqlite-version
COPY --chmod=755 <<'EOT' /usr/local/bin/entrypoint
#!/bin/sh
set -e
cmd="${1:-serve}"; [ $# -gt 0 ] && shift
case "$cmd" in
  serve) exec node src/main.js "$@" ;;
  seed)  exec node src/seed.js "$@" ;;
  *)     exec "$cmd" "$@" ;;
esac
EOT
ENTRYPOINT ["entrypoint"]
CMD ["serve"]
