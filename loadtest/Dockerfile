# syntax=docker/dockerfile:1
# The load generator, for `bench/run.py --mode docker --loadgen network`: it runs
# on the Docker network and reaches each server by its stack name.
# Build from the repo root: docker build -f loadtest/Dockerfile -t stack-benchmark-loadtest .

FROM rust:1-slim-trixie AS build
WORKDIR /app/loadtest
COPY loadtest/ ./
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/app/loadtest/target \
    cargo build --release --locked && cp target/release/loadtest /loadtest

FROM debian:trixie-slim
COPY --from=build /loadtest /usr/local/bin/loadtest
ENTRYPOINT ["loadtest"]
