# syntax=docker/dockerfile:1
# Rails backend, both data layers (RAILS_DATA picks one at run time)
# (docs/requirements/07-containers.md).
# Build from the repo root: docker build -f backend/rails/Dockerfile -t stack-benchmark-rails .

FROM node:26-trixie-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json ./
RUN --mount=type=cache,target=/root/.npm npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM ruby:4.0.1-slim-trixie AS build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libyaml-dev \
 && rm -rf /var/lib/apt/lists/*
ENV BUNDLE_DEPLOYMENT=1 BUNDLE_WITHOUT="development:test" BUNDLE_PATH=/usr/local/bundle
WORKDIR /app/backend/rails
COPY backend/rails/Gemfile backend/rails/Gemfile.lock ./
RUN bundle install --jobs 4 && rm -rf /usr/local/bundle/ruby/*/cache

FROM ruby:4.0.1-slim-trixie
ENV BUNDLE_DEPLOYMENT=1 BUNDLE_WITHOUT="development:test" BUNDLE_PATH=/usr/local/bundle
WORKDIR /app/backend/rails
COPY --from=build /usr/local/bundle /usr/local/bundle
COPY backend/rails/ ./
COPY --from=frontend /app/frontend/dist /app/frontend/dist
COPY backend/migrations /app/backend/migrations
RUN mkdir -p log tmp/pids storage \
 && bundle exec ruby -e 'require "sqlite3"; puts SQLite3::SQLITE_LOADED_VERSION' > /app/sqlite-version
COPY --chmod=755 <<'EOT' /usr/local/bin/entrypoint
#!/bin/sh
set -e
cmd="${1:-serve}"; [ $# -gt 0 ] && shift
case "$cmd" in
  serve) exec bundle exec puma "$@" ;;
  seed)  exec bin/rails runner script/seed.rb "$@" ;;
  *)     exec "$cmd" "$@" ;;
esac
EOT
ENTRYPOINT ["entrypoint"]
CMD ["serve"]
