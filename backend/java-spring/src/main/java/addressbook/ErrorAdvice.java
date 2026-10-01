package addressbook;

import addressbook.Models.ApiException;
import addressbook.Models.ErrorBody;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.HttpMediaTypeNotSupportedException;
import org.springframework.web.ErrorResponse;
import org.springframework.web.HttpRequestMethodNotSupportedException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.servlet.NoHandlerFoundException;
import org.springframework.web.servlet.resource.NoResourceFoundException;
import org.sqlite.SQLiteException;

/** Every error is JSON {"error": ...} (03-api.md §6-7); a 500 never shows its cause. */
@RestControllerAdvice
public class ErrorAdvice {
    private static final Logger log = LoggerFactory.getLogger(ErrorAdvice.class);

    @ExceptionHandler(ApiException.class)
    ResponseEntity<byte[]> api(ApiException e) {
        return error(HttpStatus.valueOf(e.status()), e.getMessage());
    }

    @ExceptionHandler(MethodArgumentTypeMismatchException.class)
    ResponseEntity<byte[]> badPath(MethodArgumentTypeMismatchException e) {
        return error(HttpStatus.BAD_REQUEST, "invalid " + e.getName());
    }

    @ExceptionHandler(HttpRequestMethodNotSupportedException.class)
    ResponseEntity<byte[]> method(HttpRequestMethodNotSupportedException e) {
        return error(HttpStatus.METHOD_NOT_ALLOWED, "method not allowed");
    }

    @ExceptionHandler(HttpMediaTypeNotSupportedException.class)
    ResponseEntity<byte[]> mediaType(HttpMediaTypeNotSupportedException e) {
        return error(HttpStatus.UNSUPPORTED_MEDIA_TYPE, "unsupported content type");
    }

    @ExceptionHandler({NoHandlerFoundException.class, NoResourceFoundException.class})
    ResponseEntity<byte[]> notFound(Exception e) {
        return error(HttpStatus.NOT_FOUND, "not found");
    }

    @ExceptionHandler(ApiController.DatabaseException.class)
    ResponseEntity<byte[]> database(ApiController.DatabaseException e) {
        if (e.getCause() instanceof SQLiteException s && Store.isConstraint(s)) {
            return error(HttpStatus.CONFLICT, "that conflicts with an existing record");
        }
        log.error("database error: {}", e.getMessage(), e.getCause());
        return error(HttpStatus.INTERNAL_SERVER_ERROR, "internal server error");
    }

    @ExceptionHandler(Exception.class)
    ResponseEntity<byte[]> other(Exception e) {
        if (e instanceof ErrorResponse framework && framework.getStatusCode().value() < 500) {
            // Spring MVC's own client errors (bad request line, unreadable body, ...) keep their status.
            HttpStatus status = HttpStatus.valueOf(framework.getStatusCode().value());
            return error(status, status.getReasonPhrase().toLowerCase());
        }
        log.error("internal error: {}", e.getMessage(), e);
        return error(HttpStatus.INTERNAL_SERVER_ERROR, "internal server error");
    }

    private static ResponseEntity<byte[]> error(HttpStatus status, String message) {
        return ApiController.json(status, Json.write(new ErrorBody(message)));
    }
}
