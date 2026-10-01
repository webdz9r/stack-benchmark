#!/bin/sh
# Launches the server (./run.sh) or the seeder (./run.sh seed 100000) on the
# Homebrew JDK. /usr/bin/java on macOS is a stub unless a JDK is linked, so
# prefer JAVA_HOME, then Homebrew's keg-only openjdk.
if [ -n "$JAVA_HOME" ]; then
  JAVA="$JAVA_HOME/bin/java"
elif [ -x /opt/homebrew/opt/openjdk/bin/java ]; then
  JAVA=/opt/homebrew/opt/openjdk/bin/java
else
  JAVA=java
fi

if [ "$1" = "--version" ]; then
  "$JAVA" -version 2>&1 | head -1
  exit 0
fi

# JAVA_CPUS caps the processors the JVM sees: GC, JIT and common-pool threads
# size themselves from it (ARCH-9/10). Defaults to all cores.
CPU_FLAG=""
if [ -n "$JAVA_CPUS" ]; then
  CPU_FLAG="-XX:ActiveProcessorCount=$JAVA_CPUS"
fi

# Parallel GC by default: under load the read pool is the bottleneck, and
# Parallel's short young-generation pauses with no concurrent GC threads beat
# G1 at 5,000-6,000 users in every A/B run (p99 71 vs 84 ms, 77 vs 172 ms at
# 5,000). ZGC was worse (126 ms): its concurrent threads compete for the 4
# cores. A collector chosen in JAVA_OPTS wins (the JVM refuses two).
GC_FLAG="-XX:+UseParallelGC"
case "$JAVA_OPTS" in
  *-XX:+Use*GC*) GC_FLAG="" ;;
esac

cd "$(dirname "$0")" || exit 1
exec "$JAVA" $CPU_FLAG $GC_FLAG $JAVA_OPTS --enable-native-access=ALL-UNNAMED \
  -jar target/address-book.jar "$@"
