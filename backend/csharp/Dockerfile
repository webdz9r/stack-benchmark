# syntax=docker/dockerfile:1
# C# backend (docs/requirements/07-containers.md). Microsoft publishes no
# Debian-based .NET 10 image, so the runtime is Microsoft's ASP.NET Core build
# installed on debian:trixie-slim with dotnet-install.sh (CTR-2).
# Build from the repo root: docker build -f backend/csharp/Dockerfile -t stack-benchmark-csharp .

FROM node:26-trixie-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json ./
RUN --mount=type=cache,target=/root/.npm npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build
WORKDIR /app/backend/csharp
COPY backend/csharp/*.csproj ./
RUN --mount=type=cache,target=/root/.nuget/packages dotnet restore
COPY backend/csharp/ ./
RUN --mount=type=cache,target=/root/.nuget/packages \
    dotnet publish -c Release --no-restore -o /out --nologo

FROM debian:trixie-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl libicu76 libssl3t64 libstdc++6 tzdata zlib1g \
 && curl -fsSL https://dot.net/v1/dotnet-install.sh -o /tmp/dotnet-install.sh \
 && bash /tmp/dotnet-install.sh --channel 10.0 --runtime aspnetcore --install-dir /usr/share/dotnet \
 && ln -s /usr/share/dotnet/dotnet /usr/local/bin/dotnet \
 && rm /tmp/dotnet-install.sh && apt-get purge -y curl && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*
ENV DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
WORKDIR /app/backend/csharp
COPY --from=build /out ./
COPY --from=frontend /app/frontend/dist /app/frontend/dist
COPY backend/migrations /app/backend/migrations
RUN dotnet AddressBook.dll sqlite-version > /app/sqlite-version
COPY --chmod=755 <<'EOT' /usr/local/bin/entrypoint
#!/bin/sh
set -e
cmd="${1:-serve}"; [ $# -gt 0 ] && shift
case "$cmd" in
  serve) exec dotnet AddressBook.dll "$@" ;;
  seed)  exec dotnet AddressBook.dll seed "$@" ;;
  *)     exec "$cmd" "$@" ;;
esac
EOT
ENTRYPOINT ["entrypoint"]
CMD ["serve"]
