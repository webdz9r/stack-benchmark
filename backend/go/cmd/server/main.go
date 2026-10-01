// Address book API server (Go).
//
//	GOMAXPROCS=4 DB_READERS=4 go run ./cmd/server
package main

import (
	"log"
	"net/http"
	"os"
	"runtime"
	"strconv"

	"github.com/klauspost/compress/gzhttp"

	"addressbook/app"
)

func env(name, fallback string) string {
	if v := os.Getenv(name); v != "" {
		return v
	}
	return fallback
}

func main() {
	readers, err := strconv.Atoi(env("DB_READERS", strconv.Itoa(runtime.GOMAXPROCS(0))))
	if err != nil {
		log.Fatal("DB_READERS must be a number")
	}
	dbPath := env("DATABASE_PATH", "data/address-book.db")
	db, err := app.Open(dbPath, readers, env("MIGRATIONS_DIR", "../migrations"))
	if err != nil {
		log.Fatalf("open database: %v", err)
	}
	db.StartCheckpointer()

	// gzip level 6 over 32 bytes: matches tower-http's defaults on the Rust side.
	gzip, err := gzhttp.NewWrapper(gzhttp.CompressionLevel(6), gzhttp.MinSize(32))
	if err != nil {
		log.Fatal(err)
	}
	handler := gzip(app.NewServer(db).Routes(env("STATIC_DIR", "../../frontend/dist")))

	addr := env("BIND_ADDR", "127.0.0.1:7883")
	log.Printf("database ready: %s (%d readers); listening on http://%s", dbPath, readers, addr)
	log.Fatal(http.ListenAndServe(addr, handler))
}
