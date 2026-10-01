"""Parity check (VER-2): is a candidate backend indistinguishable from the reference?

    python3 bench/parity.py http://127.0.0.1:7880/api [reference-url]
    (default candidate: Python on :7879; default reference: Rust on :7878)

Two parts:

1. Identical responses. The same requests go to both servers, and the status
   codes and parsed JSON must match (ids and timestamps are ignored for writes).
   It covers reads, paging edge cases, search tokenization, filters, the A–Z
   index, creates, every validation error, tag conflicts and 404s.
2. Contract checks. Framework-level behavior where the spec allows a set of
   answers (docs/requirements/03-api.md §7), plus caching and HTTP rules
   (04-caching-and-http.md). Each check runs against both servers, so a failing
   reference shows up too.

Both servers must hold the same data. Writes create contacts on both and delete
them again. The last line is the summary that bench/run.py reads.
"""

import gzip
import http.client
import json
import re
import sys
import urllib.parse

CANDIDATE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:7879/api"
REFERENCE = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:7878/api"


def raw(base, method, path, body=None, headers=None, root=False):
    """(status, lowercase headers, body bytes), with no client-side magic.
    `path` is relative to the API base (e.g. /contacts), or to the server root
    when root=True (frontend paths)."""
    u = urllib.parse.urlsplit(base)
    conn = http.client.HTTPConnection(u.hostname, u.port, timeout=30)
    conn.request(method, path if root else u.path + path, body=body, headers=headers or {})
    r = conn.getresponse()
    data = r.read()
    conn.close()
    return r.status, {k.lower(): v for k, v in r.getheaders()}, data


def call(base, method, path, body=None):
    headers = {"Content-Type": "application/json", "X-Fresh": "1"}
    status, h, data = raw(base, method, path, json.dumps(body).encode() if body is not None else None, headers)
    if h.get("content-encoding") == "gzip":
        data = gzip.decompress(data)
    return status, json.loads(data) if data else None


# ---------------------------------------------------------------- 1. identical responses

VOLATILE = {"id", "created_at", "updated_at"}


def strip(v):
    if isinstance(v, dict):
        return {k: strip(x) for k, x in v.items() if k not in VOLATILE}
    if isinstance(v, list):
        return [strip(x) for x in v]
    return v


same = diff = 0


def compare(label, method, path, body=None, volatile=False):
    global same, diff
    a, b = call(REFERENCE, method, path, body), call(CANDIDATE, method, path, body)
    if volatile:
        a, b = (a[0], strip(a[1])), (b[0], strip(b[1]))
    if a == b:
        same += 1
    else:
        diff += 1
        print(f"MISMATCH {label}: {method} {path}\n  reference: {str(a)[:300]}\n  candidate: {str(b)[:300]}")


SEARCHES = [
    "smith", "Smith ", "jo smi", "o'bri", "aus", "a", "martinez@", "ava.walsh1", '"quoted"', "***", "müller", "555-12",
    # Tokenizer: a word is Unicode letters, marks and numbers (L*, M*, N*) plus @ . '
    "xu²", "Ⅻ", "café", "नमस्ते",
]
gets = ["/stats", "/tags", "/contacts", "/contacts?limit=60", "/contacts?limit=200&offset=55000",
        "/contacts?offset=109990", "/contacts?limit=0", "/contacts?limit=9999&offset=-5", "/contacts/letters",
        "/contacts/1", "/contacts/77777", "/contacts/999999"]
for q in SEARCHES:
    enc = urllib.parse.quote(q)
    gets += [f"/contacts?q={enc}&limit=60", f"/contacts/letters?q={enc}"]
for f in ["tag=3", "favorite=true", "tag=2&favorite=true", "q=walsh&tag=1", "tag=999"]:
    gets += [f"/contacts?{f}&limit=60&offset=60", f"/contacts/letters?{f}"]
for g in gets:
    compare("get", "GET", g)

creates = [
    {"first_name": "  Parity ", "last_name": "Test", "emails": [{"label": "Work", "value": " p@t.io "}, {"value": ""}],
     "phones": [{"value": "555 1"}], "addresses": [{"city": " X "}, {}], "tag_ids": [3, 1, 3], "birthday": "1990-01-02"},
    {"company": "Only Co"},
    # API-U1: a row without "value" is dropped, not rejected
    {"first_name": "Parity", "last_name": "Novalue", "emails": [{"label": "home"}], "phones": [{}]},
]
invalid = [{"first_name": " "}, {"first_name": "x", "emails": [{"value": "nope"}]},
           {"first_name": "x", "birthday": "1990-13-01"}, {"first_name": "x", "birthday": "90-1-1"},
           {"first_name": "x", "tag_ids": [999]}]
for b in creates:
    compare("create", "POST", "/contacts", b, volatile=True)
for b in invalid:
    compare("invalid", "POST", "/contacts", b)
compare("tag conflict", "POST", "/tags", {"name": "family"})
compare("tag bad color", "POST", "/tags", {"name": "zz", "color": "neon"})
compare("tag empty", "POST", "/tags", {"name": "  "})
compare("favorite on missing contact", "PUT", "/contacts/999999/favorite", {"favorite": True})
compare("update missing", "PUT", "/contacts/999999", {"first_name": "x"})
compare("delete missing", "DELETE", "/contacts/999999")
compare("search after create", "GET", "/contacts?q=parity", volatile=True)
compare("letters after create", "GET", "/contacts/letters?q=parity%20test")
for base in (REFERENCE, CANDIDATE):  # clean up
    for q in ("parity", "only%20co"):
        for c in call(base, "GET", f"/contacts?q={q}&limit=200")[1]["items"]:
            call(base, "DELETE", f"/contacts/{c['id']}")
compare("stats after cleanup", "GET", "/stats")

# ---------------------------------------------------------------- 2. contract checks

JSON = {"Content-Type": "application/json"}
passed = total = 0


def expect(label, ok_fn, method, path, body=None, headers=None, root=False):
    """Run one request on both servers; ok_fn(status, headers, body) -> bool."""
    global passed, total
    for name, base in (("reference", REFERENCE), ("candidate", CANDIDATE)):
        total += 1
        try:
            status, h, data = raw(base, method, path, body, headers, root)
            ok = ok_fn(status, h, data)
        except Exception as e:  # noqa: BLE001 - report anything as a failure
            status, h, ok = f"error {type(e).__name__}", {}, False
        if ok:
            passed += 1
        else:
            print(f"CONTRACT {name}: {label}: {method} {path} -> {status} "
                  f"{h.get('content-type', '')} {h.get('content-encoding', '')}".rstrip())


def status_in(*codes):
    return lambda s, h, d: s in codes


def is_json_error(message):
    return lambda s, h, d: s == 404 and json.loads(d or b"null") == {"error": message}


expect("health is text/plain ok", lambda s, h, d: s == 200 and h.get("content-type", "").startswith("text/plain")
       and d == b"ok", "GET", "/health")
expect("unknown /api path", is_json_error("not found"), "GET", "/nope")
expect("malformed JSON", status_in(400, 422), "POST", "/contacts", b'{"first_name":', JSON)
expect("wrong field type", status_in(400, 422), "POST", "/contacts", b'{"first_name":5}', JSON)
expect("favorite not a boolean", status_in(400, 422), "PUT", "/contacts/1/favorite", b'{"favorite":"yes"}', JSON)
expect("favorite missing", status_in(422), "PUT", "/contacts/1/favorite", b"{}", JSON)
expect("no Content-Type (rejected, or accepted and validated)", status_in(400, 415, 422), "POST", "/tags",
       b'{"name":""}')
expect("non-integer id", status_in(400, 404), "GET", "/contacts/abc")
for param in ("tag", "limit", "offset"):
    expect(f"non-integer {param}", status_in(400), "GET", f"/contacts?{param}=abc")
expect("favorite filter not true/false", status_in(400), "GET", "/contacts?favorite=1")
expect("wrong method", status_in(404, 405), "DELETE", "/stats")
expect("empty DELETE body labeled JSON (API-U2)", status_in(404), "DELETE", "/contacts/999999", b"", JSON)
expect("uncached list has no ETag", lambda s, h, d: s == 200 and "etag" not in h, "GET", "/contacts?limit=5")
expect("cached response has ETag and no-cache",
       lambda s, h, d: s == 200 and re.fullmatch(r'"[0-9a-f]{16}"', h.get("etag", "")) is not None
       and h.get("cache-control") == "no-cache", "GET", "/contacts?q=smith&limit=5")


def revalidates(base):
    _, h, _ = raw(base, "GET", "/stats")
    status, _, data = raw(base, "GET", "/stats", headers={"If-None-Match": h.get("etag", '"none"')})
    return status == 304 and data == b""


for name, base in (("reference", REFERENCE), ("candidate", CANDIDATE)):
    total += 1
    if revalidates(base):
        passed += 1
    else:
        print(f"CONTRACT {name}: If-None-Match does not give an empty 304")

GZ = {"Accept-Encoding": "gzip"}
expect("gzip with Vary on bodies of 32+ bytes",
       lambda s, h, d: h.get("content-encoding") == "gzip" and "accept-encoding" in h.get("vary", "").lower(),
       "GET", "/contacts?limit=5", headers=GZ)
expect("no gzip under 32 bytes", lambda s, h, d: s == 200 and "content-encoding" not in h,
       "GET", "/contacts/letters?q=zzqqxx", headers={**GZ, "X-Fresh": "1"})

# Frontend serving: only when the server has a built frontend.
status, h, index = raw(CANDIDATE, "GET", "/", root=True)
if status == 200 and h.get("content-type", "").startswith("text/html"):
    expect("SPA deep link gets index.html",
           lambda s, h, d: s == 200 and h.get("content-type", "").startswith("text/html"), "GET", "/some/deep/link",
           root=True)
    asset = re.search(rb'src="(/assets/[^"]+\.js)"', index)
    if asset:
        expect("static files are gzipped", lambda s, h, d: s == 200 and h.get("content-encoding") == "gzip",
               "GET", asset.group(1).decode(), headers=GZ, root=True)

print(f"\n{same} identical, {diff} mismatched; {passed}/{total} contract checks passed")
