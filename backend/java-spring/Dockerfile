# syntax=docker/dockerfile:1
# Java (Spring Boot) backend (docs/requirements/07-containers.md). There's no
# official JDK 27 image yet, so Eclipse Temurin 27 is installed on
# debian:trixie-slim (CTR-2): the JDK plus Maven to build, the JRE to run.
# Build from the repo root: docker build -f backend/java-spring/Dockerfile -t stack-benchmark-java-spring .

FROM node:26-trixie-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json ./
RUN --mount=type=cache,target=/root/.npm npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM debian:trixie-slim AS build
ARG TARGETARCH
ARG MAVEN_VERSION=3.9.16
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*
RUN arch=$([ "$TARGETARCH" = arm64 ] && echo aarch64 || echo x64) \
 && mkdir -p /opt/jdk /opt/maven \
 && curl -fsSL "https://api.adoptium.net/v3/binary/latest/27/ga/linux/$arch/jdk/hotspot/normal/eclipse" \
    | tar -xz -C /opt/jdk --strip-components=1 \
 && curl -fsSL "https://archive.apache.org/dist/maven/maven-3/$MAVEN_VERSION/binaries/apache-maven-$MAVEN_VERSION-bin.tar.gz" \
    | tar -xz -C /opt/maven --strip-components=1
ENV JAVA_HOME=/opt/jdk PATH=/opt/jdk/bin:/opt/maven/bin:$PATH
WORKDIR /app/backend/java-spring
COPY backend/java-spring/pom.xml ./
RUN --mount=type=cache,target=/root/.m2 mvn -q -B dependency:go-offline
COPY backend/java-spring/ ./
RUN --mount=type=cache,target=/root/.m2 mvn -q -B package -DskipTests

FROM debian:trixie-slim
ARG TARGETARCH
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
 && arch=$([ "$TARGETARCH" = arm64 ] && echo aarch64 || echo x64) \
 && mkdir -p /opt/jre \
 && curl -fsSL "https://api.adoptium.net/v3/binary/latest/27/ga/linux/$arch/jre/hotspot/normal/eclipse" \
    | tar -xz -C /opt/jre --strip-components=1 \
 && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*
ENV JAVA_HOME=/opt/jre
WORKDIR /app/backend/java-spring
COPY --from=build /app/backend/java-spring/target/address-book.jar target/address-book.jar
COPY backend/java-spring/run.sh ./
COPY --from=frontend /app/frontend/dist /app/frontend/dist
COPY backend/migrations /app/backend/migrations
RUN ./run.sh sqlite-version > /app/sqlite-version
COPY --chmod=755 <<'EOT' /usr/local/bin/entrypoint
#!/bin/sh
set -e
cmd="${1:-serve}"; [ $# -gt 0 ] && shift
case "$cmd" in
  serve) exec ./run.sh "$@" ;;
  seed)  exec ./run.sh seed "$@" ;;
  *)     exec "$cmd" "$@" ;;
esac
EOT
ENTRYPOINT ["entrypoint"]
CMD ["serve"]
