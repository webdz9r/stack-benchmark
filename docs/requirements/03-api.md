# 03 — HTTP API

All routes are under `/api`. Request and response bodies are JSON (UTF-8), except
for `/api/health`. The frontend (`frontend/src/api.js`), the load generator
(`loadtest/`) and the parity check (`bench/parity.py`) all depend on this contract.

## 1. Route table

| # | Method | Path | Success | Cached? |
| --- | --- | --- | --- | --- |
| 1 | GET | `/api/health` | 200 `text/plain` body `ok` | no |
| 2 | GET | `/api/stats` | 200 Stats | **yes** |
| 3 | GET | `/api/contacts` | 200 ContactPage | only when filtered |
| 4 | GET | `/api/contacts/letters` | 200 `LetterIndex[]` | **yes** |
| 5 | GET | `/api/contacts/{id}` | 200 Contact | no |
| 6 | POST | `/api/contacts` | **201** Contact | — (write) |
| 7 | PUT | `/api/contacts/{id}` | 200 Contact | — (write) |
| 8 | DELETE | `/api/contacts/{id}` | **204**, empty body | — (write) |
| 9 | PUT | `/api/contacts/{id}/favorite` | **204**, empty body | — (write) |
| 10 | GET | `/api/tags` | 200 `TagWithCount[]` | **yes** |
| 11 | POST | `/api/tags` | **201** Tag | — (write) |
| 12 | PUT | `/api/tags/{id}` | 200 Tag | — (write) |
| 13 | DELETE | `/api/tags/{id}` | **204**, empty body | — (write) |
| — | any | any other `/api/...` | **404** `{"error":"not found"}` | — |

- **API-1** `/api/contacts/letters` MUST be matched before `/api/contacts/{id}`.
  `letters` is not an id.
- **API-2** `{id}` is a signed 64-bit integer.
- **API-3** Every non-empty JSON response MUST have `Content-Type:
  application/json`.
- **API-4** "Cached?" refers to the response cache in
  [04-caching-and-http.md](04-caching-and-http.md). Cached responses carry `ETag`
  and `Cache-Control: no-cache`; uncached ones don't.

## 2. JSON types

The field order below is the reference serialization order. The parity check
compares parsed JSON, so order isn't strictly required, but matching it keeps the
bodies byte-comparable and gzip sizes equal. Implementations SHOULD keep it.

JSON output MUST be compact: no whitespace or newlines between tokens.

```jsonc
// Tag
{ "id": 1, "name": "Family", "color": "red" }

// TagWithCount  (a Tag, flattened, plus the count)
{ "id": 1, "name": "Family", "color": "red", "contact_count": 13118 }

// LabeledValue
{ "label": "home", "value": "ada@example.com" }

// Address
{ "label": "home", "street": "", "city": "London", "region": "", "postal_code": "", "country": "UK" }

// Contact  (full record)
{
  "id": 1,
  "first_name": "James", "last_name": "Sato",
  "company": "Massive Dynamic", "job_title": "Data Scientist",
  "birthday": null,                 // string "YYYY-MM-DD" or null
  "notes": "",
  "favorite": false,                // JSON boolean, never 0/1
  "emails":    [LabeledValue],      // ordered by position
  "phones":    [LabeledValue],      // ordered by position
  "addresses": [Address],           // ordered by position
  "tags":      [Tag],               // ordered by name, case-insensitive
  "created_at": "2026-09-29T17:02:50.401Z",
  "updated_at": "2026-09-29T17:02:50.401Z"
}

// ContactSummary  (a list row)
{
  "id": 380, "first_name": "Amara", "last_name": "Abara",
  "company": "", "job_title": "", "favorite": false,
  "email": "amara.abara379@example.com",   // first email by position, or null
  "phone": "+1 555-814-6457",              // first phone by position, or null
  "tag_ids": [1, 4]                        // ascending; [] when none
}

// ContactPage
{ "items": [ContactSummary], "total": 110002, "limit": 60, "offset": 0 }

// LetterIndex
{ "letter": "A", "offset": 0, "count": 4123 }

// Stats
{ "contacts": 110002, "favorites": 5498 }

// Error
{ "error": "human-readable message" }
```

- **API-5** Timestamps are the strings that SQLite's default expression stores
  (`YYYY-MM-DDTHH:MM:SS.sssZ`, UTC, milliseconds), returned unchanged. The backend
  MUST NOT reformat them.
- **API-6** Integers MUST be JSON numbers, not strings.

## 3. Endpoints in detail

### 3.1 `GET /api/health`

Returns `200` with body `ok` and a `text/plain` Content-Type (`charset=utf-8`
optional). It doesn't touch the database. The benchmark polls it to measure startup time.

### 3.2 `GET /api/stats`

Returns `Stats` (§7.8 of [02-database.md](02-database.md#78-stats)). It is cached
under the key `stats`.

### 3.3 `GET /api/contacts`

Query parameters:

| Param | Type | Default | Handling |
| --- | --- | --- | --- |
| `q` | string | none | Search text → `fts_query`. If that yields NONE (empty, whitespace or symbols only), there is no search filter. |
| `tag` | int64 | none | Only contacts that have this tag. An unknown tag id gives an empty result, not an error. |
| `favorite` | `true`/`false` | false | Only `true` filters. `false` is the same as omitting it. |
| `limit` | int64 | 50 | **Clamped** to `[1, 200]`. `limit=0` → 1, `limit=9999` → 200. |
| `offset` | int64 | 0 | Negative values become 0. Past the end → `items: []` with the correct `total`. |

- **API-L1** The response echoes the **effective** (clamped) `limit` and `offset`.
- **API-L2** `total` is the number of contacts matching the filters, ignoring
  limit and offset.
- Rows use the canonical order (`sort_key`, `first_name`, `id`, case-insensitive).
- **Caching:** the request is **filtered** if `tag` is present, or `favorite=true`,
  or `fts_query(q)` is not NONE. Filtered requests go through the cache.
  Unfiltered requests are always computed directly, because they walk the sort
  index in about 0.5 ms and aren't worth caching.

### 3.4 `GET /api/contacts/letters`

Takes the same `q`, `tag` and `favorite` filters, and ignores `limit` and `offset`.
It returns, for each A–Z rail letter, where that letter's first contact sits in the
sorted, filtered list, so the UI can jump there by fetching the page at `offset`.

- **API-L3** Build the response from the ordered `(sort_letter, count)` buckets
  (§7.3), keeping a running `offset` that starts at 0:
  ```
  letters = []
  offset  = 0
  for (letter, count) in buckets:           // ordered '#' < 'A'..'Z' < '~'
      if letter == '~':
          if letters has an entry with letter '#':  that_entry.count += count
          else: letters.push({letter: '#', offset, count})
      else:
          letters.push({letter, offset, count})
      offset += count
  ```
  So `'~'` names (after Z) fold into `'#'`. If there is already a `'#'` bucket,
  its offset stays that of the first `'#'` contact; otherwise the entry is added at
  the end, with the offset of the first `'~'` contact.
- Letters with no contacts are left out. No filter matches → `[]`.
- Always cached.

### 3.5 `GET /api/contacts/{id}`

Returns the full `Contact`, or `404 {"error":"not found"}`.

### 3.6 `POST /api/contacts`

The body is a **ContactInput** (§4). Validate it; insert the contact, its children
and its FTS row in one transaction; read the contact back in the same transaction;
commit. Return **201** with the full `Contact`.

### 3.7 `PUT /api/contacts/{id}`

The body is a **ContactInput**. This is a **full replace**: fields left out take
their defaults, so leaving out `emails` deletes all the emails. Child rows are
deleted and re-inserted with positions `0..n-1`. `updated_at` is set to now;
`created_at` is kept.

- **API-C1** Order of checks: **validate the body first** (422), then the existence
  of the contact (404). A missing contact with a valid body → `404 {"error":"not
  found"}`.

Returns **200** with the full `Contact`.

### 3.8 `DELETE /api/contacts/{id}`

Deletes the FTS row, then the contact. Children and tag links cascade. Returns
`204`, or `404 {"error":"not found"}`.

### 3.9 `PUT /api/contacts/{id}/favorite`

Body: `{"favorite": true|false}`. Sets the flag and `updated_at`. Returns `204`, or
`404 {"error":"not found"}`. It doesn't touch child rows or the FTS table.

### 3.10 `GET /api/tags`

Returns every tag with its `contact_count` (0 when unused), ordered by name,
case-insensitive. Cached under the key `tags`.

### 3.11 `POST /api/tags`

The body is a **TagInput** (§5). The color defaults to `slate`. Returns **201**
with the `Tag`.
A duplicate name, compared case-insensitively → **409** `{"error":"a tag named '<name>' already exists"}`,
where `<name>` is the **trimmed input** name (for example `family`, not the stored
`Family`).

### 3.12 `PUT /api/tags/{id}`

The body is a **TagInput**. `name` is required. `color` is optional: if it is left
out or null, the current color is kept. Returns **200** with the updated `Tag`.
Errors: 422 validation, 404 unknown id (checked after validation), 409 when the
name conflicts with **another** tag.

### 3.13 `DELETE /api/tags/{id}`

Deletes the tag. It disappears from every contact through `ON DELETE CASCADE`.
Contacts' `updated_at` is **not** changed. Returns `204`, or `404`.

## 4. ContactInput and its validation

Body shape. Every field is optional:

```jsonc
{
  "first_name": "", "last_name": "", "company": "", "job_title": "",
  "birthday": null,           // string or null
  "notes": "",
  "favorite": false,
  "emails":    [{ "label": "", "value": "" }],
  "phones":    [{ "label": "", "value": "" }],
  "addresses": [{ "label": "", "street": "", "city": "", "region": "", "postal_code": "", "country": "" }],
  "tag_ids": []
}
```

Unknown fields MUST be **ignored**. The load generator PUTs back a full `Contact`,
including `id`, `tags`, `created_at` and so on, with `tag_ids` added.

Validation and normalization, **in this exact order**. The first failure is
returned as `422 {"error": "<message>"}`:

| Step | Rule | Error message |
| --- | --- | --- |
| V1 | Trim (leading and trailing Unicode whitespace) `first_name`, `last_name`, `company`, `job_title`, `notes` | — |
| V2 | If `first_name`, `last_name` and `company` are **all** empty after trimming → error | `a name or company is required` |
| V3 | `birthday`: trim it; if empty, set it to `null` | — |
| V4 | If `birthday` isn't null, it must be `DDDD-DD-DD`: 3 dash-separated parts of lengths 4/2/2, all digits, month `01`–`12`, day `01`–`31`. The day is **not** checked against the month (`2023-02-31` passes) | `birthday must be YYYY-MM-DD` |
| V5 | `emails` and `phones`: drop rows whose `value` is empty after trimming; trim `value`; normalize `label` (see below) | — |
| V6 | Check each remaining email, in order: split at the **first** `@`; the part before it must be non-empty, the part after it must contain a `.`, and the whole value must contain no whitespace | `'<value>' is not a valid email` (the trimmed value, in single quotes) |
| V7 | `addresses`: drop rows where `street`, `city`, `region`, `postal_code` and `country` are **all** empty after trimming (the label doesn't count); normalize the label; trim all five fields | — |
| V8 | `tag_ids`: sort ascending and remove duplicates | — |
| V9 | *(during the insert)* the first `tag_id`, in ascending order, that doesn't exist | `tag <id> does not exist` |

**Label normalization:** trim, lowercase, and use `"other"` if the result is empty.
A missing label counts as empty. Phones get no format validation. No field has a
length limit, except tag names.

Example: `{"first_name":"  Parity ","emails":[{"label":"Work","value":" p@t.io "},{"value":""}],"addresses":[{"city":" X "},{}],"tag_ids":[3,1,3]}`
is stored as `first_name:"Parity"`, one email `{label:"work",value:"p@t.io"}`, one
address `{label:"other",city:"X",…}` and `tag_ids [1,3]`.

## 5. TagInput and its validation

```jsonc
{ "name": "Family", "color": "red" }   // color optional
```

| Step | Rule | Error message |
| --- | --- | --- |
| T1 | Trim `name`. If it's empty → error | `tag name is required` |
| T2 | More than **40 Unicode scalar values** (code points, not bytes) → error | `tag name must be 40 characters or fewer` |
| T3 | If `color` is given, it must be one of `slate, red, orange, amber, green, teal, sky, indigo, violet, pink` (exact, case-sensitive) | `unknown tag color '<color>'` |

## 6. Error model

Every application error is JSON: `{"error": "<message>"}`.

| Status | When | Message |
| --- | --- | --- |
| 404 | Row not found; unknown `/api` path | `not found` |
| 409 | Duplicate tag name | `a tag named '<name>' already exists` |
| 409 | Any other SQLite constraint violation that isn't mapped more specifically | `that conflicts with an existing record` |
| 422 | Validation failure (§4, §5), including an unknown `tag_id` | see the tables above |
| 500 | Anything else | `internal server error` (details go only to the server log) |

- **API-E1** A SQLite "no rows" result on a single-row lookup MUST map to 404.
- **API-E2** The error texts above are compared **byte for byte** by the parity
  check.

## 7. Framework-level behavior

These come from the web framework rather than the application, so frameworks
differ. The spec allows a **set** of statuses where the difference doesn't matter
to a client, and pins a single answer where it does (a crash, or a request that
silently changes data). Error bodies SHOULD be JSON `{"error": "..."}`. The
parity check's contract section (`bench/parity.py`) tests every row.

| Situation | Allowed status |
| --- | --- |
| Malformed JSON body | 400 or 422 |
| JSON body where a field has the wrong type (for example `"first_name": 5`, `"favorite": "yes"`) | 400 or 422. Values MUST NOT be coerced: `"yes"`, `1` or `"true"` are not booleans, and `"3"` is not an integer |
| `PUT /favorite` without a `favorite` field | 422 |
| POST or PUT without a `Content-Type` header | 415 or 400, or accept the body as JSON (and then validate it as usual) |
| Non-integer path id (`/api/contacts/abc`) | 400 or 404 |
| Non-integer `tag`, `limit` or `offset` | 400 |
| `favorite` query parameter other than `true` or `false` (for example `favorite=1`) | 400. It MUST NOT be treated as `true` |
| Known path, wrong method (`DELETE /api/stats`) | 405 or 404 |
| Any of the above | never 500 |

- **API-U1** An email or phone row without a `value` MUST be treated as having an
  empty value, so validation drops the row (V5). It MUST NOT be rejected.
- **API-U2** A DELETE whose body is empty MUST be accepted, even when it's labeled
  `application/json`.
