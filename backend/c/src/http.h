/* Building and sending HTTP responses (gzip, static files) with libmicrohttpd. */
#ifndef HTTP_H
#define HTTP_H

#include <microhttpd.h>
#include <stddef.h>

typedef struct {
    int status;
    char *body;        /* malloc'd, or NULL for no body */
    size_t len;
    const char *type;  /* Content-Type, or NULL */
    char etag[20];     /* set for cached responses ("" otherwise) */
    int gzipped;       /* body is gzip-compressed (set by finish_reply) */
} reply_t;

/* gzip the body (level 6) when the client accepts it and the body is at least
 * 32 bytes of a compressible type. CPU work, so workers call it, not I/O threads. */
void finish_reply(reply_t *r, int accept_gzip);

/* Queue a finished reply, with ETag + Cache-Control for cached replies. */
enum MHD_Result send_reply(struct MHD_Connection *conn, reply_t *r);

/* A JSON reply {"error": msg}. */
reply_t error_reply(int status, const char *msg);
reply_t json_reply(int status, char *body, size_t len);

/* Serve a file from the built frontend, falling back to index.html (the SPA
 * fallback). Returns 0 when there's no frontend at all. */
int static_reply(const char *static_dir, const char *url, reply_t *r);

#endif
