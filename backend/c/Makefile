# C backend. Needs a C11 compiler, pkg-config, libmicrohttpd, yyjson and zlib:
#   macOS:  brew install libmicrohttpd yyjson
#   Debian/Ubuntu: apt install libmicrohttpd-dev libyyjson-dev zlib1g-dev
# SQLite is compiled in from the official amalgamation (downloaded on first build),
# pinned to the same version the Rust reference bundles.

SQLITE_VERSION := 3530200
SQLITE_YEAR    := 2026
SQLITE_DIR     := vendor/sqlite-amalgamation-$(SQLITE_VERSION)

CC      ?= cc
PKGS    := libmicrohttpd yyjson zlib
CFLAGS  ?= -O3
CFLAGS  += -std=c11 -Wall -Wextra -Wno-unused-parameter -pthread -D_DEFAULT_SOURCE -D_DARWIN_C_SOURCE \
           $(shell pkg-config --cflags $(PKGS)) -I$(SQLITE_DIR)
LDLIBS  += $(shell pkg-config --libs $(PKGS)) -lpthread -lm

# Same options as the Rust reference's bundled SQLite that affect this workload:
# FTS5, STAT4 (query planner statistics), and no global malloc statistics
# mutex (DB-2).
SQLITE_CFLAGS := -O3 -DSQLITE_ENABLE_FTS5 -DSQLITE_ENABLE_STAT4 -DSQLITE_DEFAULT_MEMSTATUS=0 \
                 -DSQLITE_THREADSAFE=1 -DSQLITE_USE_URI -DHAVE_USLEEP=1 -DSQLITE_OMIT_LOAD_EXTENSION

COMMON  := build/db.o build/repo.o build/json.o build/text.o build/validate.o build/sqlite3.o
SERVER  := build/main.o build/http.o build/cache.o $(COMMON)
SEED    := build/seed.o $(COMMON)

all: server seed

server: $(SERVER)
	$(CC) $(CFLAGS) -o $@ $^ $(LDLIBS)

seed: $(SEED)
	$(CC) $(CFLAGS) -o $@ $^ $(LDLIBS)

build/%.o: src/%.c src/*.h $(SQLITE_DIR)/sqlite3.h | build
	$(CC) $(CFLAGS) -c -o $@ $<

build/sqlite3.o: $(SQLITE_DIR)/sqlite3.c | build
	$(CC) $(SQLITE_CFLAGS) -c -o $@ $<

# One rule downloads both files. The header depends on the source rather than
# sharing its rule, so `make -j` doesn't run the download twice at once (a
# grouped target, &:, would need GNU make 4.3; macOS ships 3.81).
$(SQLITE_DIR)/sqlite3.h: $(SQLITE_DIR)/sqlite3.c
	touch $@

$(SQLITE_DIR)/sqlite3.c:
	mkdir -p vendor
	curl -fsSL -o vendor/sqlite.zip https://sqlite.org/$(SQLITE_YEAR)/sqlite-amalgamation-$(SQLITE_VERSION).zip
	cd vendor && unzip -oq sqlite.zip && rm sqlite.zip
	touch $@

build:
	mkdir -p build

# Regenerate the Unicode word-character table (committed; needs Python 3).
unicode:
	python3 scripts/gen_unicode.py > src/unicode_table.h

clean:
	rm -rf build server seed

.PHONY: all clean unicode
