#include "http.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <zlib.h>

#include "json.h"

reply_t json_reply(int status, char *body, size_t len) {
    reply_t r = {.status = status, .body = body, .len = len, .type = "application/json"};
    return r;
}

reply_t error_reply(int status, const char *msg) {
    buf_t b = {0};
    buf_puts(&b, "{\"error\":");
    json_str(&b, msg);
    buf_putc(&b, '}');
    size_t len;
    char *body = buf_take(&b, &len);
    return json_reply(status, body, len);
}

static int compressible(const char *type) {
    return type && (strncmp(type, "application/json", 16) == 0 || strncmp(type, "text/", 5) == 0 ||
                    strncmp(type, "application/javascript", 22) == 0 || strncmp(type, "image/svg+xml", 13) == 0);
}

static char *gzip_bytes(const char *in, size_t len, size_t *out_len) {
    z_stream z = {0};
    if (deflateInit2(&z, 6, Z_DEFLATED, 15 + 16, 8, Z_DEFAULT_STRATEGY) != Z_OK) return NULL;
    size_t cap = deflateBound(&z, (uLong)len);
    char *out = malloc(cap);
    z.next_in = (Bytef *)in;
    z.avail_in = (uInt)len;
    z.next_out = (Bytef *)out;
    z.avail_out = (uInt)cap;
    int rc = deflate(&z, Z_FINISH);
    *out_len = z.total_out;
    deflateEnd(&z);
    if (rc != Z_STREAM_END) {
        free(out);
        return NULL;
    }
    return out;
}

void finish_reply(reply_t *r, int accept_gzip) {
    if (r->body && !r->gzipped && r->len >= 32 && compressible(r->type) && accept_gzip) {
        size_t zlen;
        char *z = gzip_bytes(r->body, r->len, &zlen);
        if (z) {
            free(r->body);
            r->body = z;
            r->len = zlen;
            r->gzipped = 1;
        }
    }
}

enum MHD_Result send_reply(struct MHD_Connection *conn, reply_t *r) {
    struct MHD_Response *resp;
    int gz = r->gzipped;
    if (r->body) resp = MHD_create_response_from_buffer_with_free_callback(r->len, r->body, &free);
    else resp = MHD_create_response_empty(MHD_RF_NONE);
    r->body = NULL;
    if (r->type && r->status != 304) MHD_add_response_header(resp, MHD_HTTP_HEADER_CONTENT_TYPE, r->type);
    if (gz) {
        MHD_add_response_header(resp, MHD_HTTP_HEADER_CONTENT_ENCODING, "gzip");
        MHD_add_response_header(resp, MHD_HTTP_HEADER_VARY, "accept-encoding");
    }
    if (r->etag[0]) {
        MHD_add_response_header(resp, MHD_HTTP_HEADER_ETAG, r->etag);
        MHD_add_response_header(resp, MHD_HTTP_HEADER_CACHE_CONTROL, "no-cache");
    }
    enum MHD_Result ret = MHD_queue_response(conn, (unsigned)r->status, resp);
    MHD_destroy_response(resp);
    return ret;
}

static const char *mime_type(const char *path) {
    const char *dot = strrchr(path, '.');
    if (!dot) return "application/octet-stream";
    static const struct { const char *ext, *type; } types[] = {
        {".html", "text/html; charset=utf-8"}, {".js", "text/javascript; charset=utf-8"},
        {".css", "text/css; charset=utf-8"}, {".svg", "image/svg+xml"}, {".json", "application/json"},
        {".png", "image/png"}, {".ico", "image/x-icon"}, {".woff2", "font/woff2"}, {".txt", "text/plain; charset=utf-8"},
    };
    for (size_t i = 0; i < sizeof types / sizeof *types; i++)
        if (strcmp(dot, types[i].ext) == 0) return types[i].type;
    return "application/octet-stream";
}

static int read_file(const char *path, char **data, size_t *len) {
    struct stat st;
    if (stat(path, &st) != 0 || !S_ISREG(st.st_mode)) return 0;
    FILE *f = fopen(path, "rb");
    if (!f) return 0;
    *data = malloc((size_t)st.st_size + 1);
    *len = fread(*data, 1, (size_t)st.st_size, f);
    fclose(f);
    return 1;
}

int static_reply(const char *dir, const char *url, reply_t *r) {
    char path[4096];
    char *data;
    size_t len;
    memset(r, 0, sizeof *r);
    int safe = strstr(url, "..") == NULL;
    const char *rel = strcmp(url, "/") == 0 ? "/index.html" : url;
    snprintf(path, sizeof path, "%s%s", dir, rel);
    if (safe && read_file(path, &data, &len)) {
        *r = (reply_t){.status = 200, .body = data, .len = len, .type = mime_type(path)};
        return 1;
    }
    snprintf(path, sizeof path, "%s/index.html", dir);
    if (!read_file(path, &data, &len)) return 0;
    *r = (reply_t){.status = 200, .body = data, .len = len, .type = "text/html; charset=utf-8"};
    return 1;
}
