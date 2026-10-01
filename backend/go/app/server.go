package app

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"time"
)

// Server holds the database and response cache behind the HTTP handlers.
type Server struct {
	db    *Db
	cache *ResponseCache
}

func NewServer(db *Db) *Server {
	// Other users see a write within ~1 s; the writer sees it at once (X-Fresh).
	return &Server{db: db, cache: NewResponseCache(db, 64<<20, time.Second)}
}

// Routes returns the API plus, if staticDir has a built frontend, the UI.
func (s *Server) Routes(staticDir string) http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /api/health", func(w http.ResponseWriter, _ *http.Request) { w.Write([]byte("ok")) })
	mux.HandleFunc("GET /api/stats", s.stats)
	mux.HandleFunc("GET /api/contacts", s.listContacts)
	mux.HandleFunc("GET /api/contacts/letters", s.listLetters)
	mux.HandleFunc("GET /api/contacts/{id}", s.getContact)
	mux.HandleFunc("POST /api/contacts", s.createContact)
	mux.HandleFunc("PUT /api/contacts/{id}", s.updateContact)
	mux.HandleFunc("DELETE /api/contacts/{id}", s.deleteContact)
	mux.HandleFunc("PUT /api/contacts/{id}/favorite", s.setFavorite)
	mux.HandleFunc("GET /api/tags", s.listTags)
	mux.HandleFunc("POST /api/tags", s.createTag)
	mux.HandleFunc("PUT /api/tags/{id}", s.updateTag)
	mux.HandleFunc("DELETE /api/tags/{id}", s.deleteTag)
	// Unknown /api paths get a JSON 404 rather than the SPA's index.html.
	mux.HandleFunc("/api/", func(w http.ResponseWriter, _ *http.Request) { writeError(w, NotFound()) })

	index := filepath.Join(staticDir, "index.html")
	if _, err := os.Stat(index); err == nil {
		files := http.FileServer(http.Dir(staticDir))
		mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
			if _, err := os.Stat(filepath.Join(staticDir, filepath.Clean(r.URL.Path))); err != nil {
				http.ServeFile(w, r, index) // SPA fallback
				return
			}
			files.ServeHTTP(w, r)
		})
	}
	return mux
}

// ---------------------------------------------------------------- reads

func (s *Server) stats(w http.ResponseWriter, r *http.Request) {
	s.cache.JSON(w, r, "stats", func() (any, error) { return GetStats(r.Context(), s.db.Reader()) })
}

func (s *Server) listContacts(w http.ResponseWriter, r *http.Request) {
	q, err := listQuery(r)
	if err != nil {
		writeError(w, err)
		return
	}
	compute := func() (any, error) { return ListContacts(r.Context(), s.db.Reader(), q) }
	if q.Tag == nil && !q.Favorite && FtsQuery(q.Q) == "" {
		// Unfiltered pages walk the sort index and are cheap; not worth caching.
		respond(w, http.StatusOK)(compute())
		return
	}
	key := "list|" + filterKey(q) + "|" + optInt(q.Limit) + "|" + optInt(q.Offset)
	s.cache.JSON(w, r, key, compute)
}

func (s *Server) listLetters(w http.ResponseWriter, r *http.Request) {
	q, err := listQuery(r)
	if err != nil {
		writeError(w, err)
		return
	}
	s.cache.JSON(w, r, "letters|"+filterKey(q), func() (any, error) { return ListLetters(r.Context(), s.db.Reader(), q) })
}

func (s *Server) getContact(w http.ResponseWriter, r *http.Request) {
	id, err := pathID(r)
	if err != nil {
		writeError(w, err)
		return
	}
	respond(w, http.StatusOK)(GetContact(r.Context(), s.db.Reader(), id))
}

func (s *Server) listTags(w http.ResponseWriter, r *http.Request) {
	s.cache.JSON(w, r, "tags", func() (any, error) { return ListTags(r.Context(), s.db.Reader()) })
}

// ---------------------------------------------------------------- writes

func (s *Server) createContact(w http.ResponseWriter, r *http.Request) {
	var in ContactInput
	if err := decode(r, &in); err != nil {
		writeError(w, err)
		return
	}
	var c *Contact
	err := s.db.Transaction(r.Context(), func(tx *sql.Tx) error {
		id, err := InsertContact(r.Context(), tx, &in)
		if err != nil {
			return err
		}
		c, err = GetContact(r.Context(), tx, id)
		return err
	})
	respond(w, http.StatusCreated)(c, err)
}

func (s *Server) updateContact(w http.ResponseWriter, r *http.Request) {
	id, err := pathID(r)
	if err != nil {
		writeError(w, err)
		return
	}
	var in ContactInput
	if err := decode(r, &in); err != nil {
		writeError(w, err)
		return
	}
	var c *Contact
	err = s.db.Transaction(r.Context(), func(tx *sql.Tx) error {
		if err := UpdateContact(r.Context(), tx, id, &in); err != nil {
			return err
		}
		c, err = GetContact(r.Context(), tx, id)
		return err
	})
	respond(w, http.StatusOK)(c, err)
}

func (s *Server) setFavorite(w http.ResponseWriter, r *http.Request) {
	id, err := pathID(r)
	if err != nil {
		writeError(w, err)
		return
	}
	var body struct {
		Favorite *bool `json:"favorite"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.Favorite == nil {
		writeError(w, Validation("favorite must be true or false"))
		return
	}
	s.noContent(w, r, func(ctx context.Context, tx *sql.Tx) error { return SetFavorite(ctx, tx, id, *body.Favorite) })
}

func (s *Server) deleteContact(w http.ResponseWriter, r *http.Request) {
	id, err := pathID(r)
	if err != nil {
		writeError(w, err)
		return
	}
	s.noContent(w, r, func(ctx context.Context, tx *sql.Tx) error { return DeleteContact(ctx, tx, id) })
}

func (s *Server) createTag(w http.ResponseWriter, r *http.Request) {
	var in TagInput
	if err := decode(r, &in); err != nil {
		writeError(w, err)
		return
	}
	var t *Tag
	err := s.db.Transaction(r.Context(), func(tx *sql.Tx) (err error) {
		t, err = InsertTag(r.Context(), tx, &in)
		return err
	})
	respond(w, http.StatusCreated)(t, err)
}

func (s *Server) updateTag(w http.ResponseWriter, r *http.Request) {
	id, err := pathID(r)
	if err != nil {
		writeError(w, err)
		return
	}
	var in TagInput
	if err := decode(r, &in); err != nil {
		writeError(w, err)
		return
	}
	var t *Tag
	err = s.db.Transaction(r.Context(), func(tx *sql.Tx) (err error) {
		t, err = UpdateTag(r.Context(), tx, id, &in)
		return err
	})
	respond(w, http.StatusOK)(t, err)
}

func (s *Server) deleteTag(w http.ResponseWriter, r *http.Request) {
	id, err := pathID(r)
	if err != nil {
		writeError(w, err)
		return
	}
	s.noContent(w, r, func(ctx context.Context, tx *sql.Tx) error { return DeleteTag(ctx, tx, id) })
}

func (s *Server) noContent(w http.ResponseWriter, r *http.Request, fn func(context.Context, *sql.Tx) error) {
	if err := s.db.Transaction(r.Context(), func(tx *sql.Tx) error { return fn(r.Context(), tx) }); err != nil {
		writeError(w, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// ---------------------------------------------------------------- helpers

// validator is implemented by request bodies that normalize and check themselves.
type validator interface{ Validate() error }

func decode(r *http.Request, v validator) error {
	if err := json.NewDecoder(r.Body).Decode(v); err != nil {
		return &AppError{http.StatusBadRequest, "invalid JSON: " + err.Error()}
	}
	return v.Validate()
}

// respond returns a writer for a (value, error) result pair.
func respond(w http.ResponseWriter, status int) func(any, error) {
	return func(v any, err error) {
		if err != nil {
			writeError(w, err)
			return
		}
		body, err := json.Marshal(v)
		if err != nil {
			writeError(w, err)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(status)
		w.Write(body)
	}
}

func writeError(w http.ResponseWriter, err error) {
	status, message := http.StatusInternalServerError, "internal server error"
	var app *AppError
	if errors.As(err, &app) {
		status, message = app.Status, app.Message
	} else {
		log.Printf("internal error: %v", err)
	}
	body, _ := json.Marshal(map[string]string{"error": message})
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	w.Write(body)
}

func pathID(r *http.Request) (int64, error) {
	id, err := strconv.ParseInt(r.PathValue("id"), 10, 64)
	if err != nil {
		return 0, &AppError{http.StatusBadRequest, "invalid id"}
	}
	return id, nil
}

func listQuery(r *http.Request) (ListQuery, error) {
	v := r.URL.Query()
	if f := v.Get("favorite"); f != "" && f != "true" && f != "false" {
		return ListQuery{}, &AppError{http.StatusBadRequest, "favorite must be true or false"}
	}
	q := ListQuery{Q: v.Get("q"), Favorite: v.Get("favorite") == "true"}
	for name, dst := range map[string]**int64{"tag": &q.Tag, "limit": &q.Limit, "offset": &q.Offset} {
		if s := v.Get(name); s != "" {
			n, err := strconv.ParseInt(s, 10, 64)
			if err != nil {
				return q, &AppError{http.StatusBadRequest, name + " must be an integer"}
			}
			*dst = &n
		}
	}
	return q, nil
}

// filterKey is the cache key part for a filtered query; search text is
// normalized first, so "Smith" and "smith " share an entry.
func filterKey(q ListQuery) string {
	return FtsQuery(q.Q) + "|" + optInt(q.Tag) + "|" + strconv.FormatBool(q.Favorite)
}

func optInt(v *int64) string {
	if v == nil {
		return ""
	}
	return strconv.FormatInt(*v, 10)
}
