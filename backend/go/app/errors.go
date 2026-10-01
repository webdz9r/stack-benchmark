package app

import (
	"errors"

	"github.com/mattn/go-sqlite3"
)

// AppError is an error with an HTTP status; rendered as {"error": message}.
type AppError struct {
	Status  int
	Message string
}

func (e *AppError) Error() string { return e.Message }

func NotFound() error                 { return &AppError{404, "not found"} }
func Validation(message string) error { return &AppError{422, message} }
func Conflict(message string) error   { return &AppError{409, message} }

func isConstraint(err error) bool {
	var se sqlite3.Error
	return errors.As(err, &se) && se.Code == sqlite3.ErrConstraint
}
