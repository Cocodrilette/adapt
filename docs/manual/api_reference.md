# API Reference

This document describes the API surface that is currently implemented by Adapt.

## Authentication

Adapt supports two authentication methods:

1. Session cookie (`adapt_session`) from web login
2. API key using `X-API-Key: <key>`

Generated resource routes require authentication. Non-superusers must also
have the corresponding `read` or `write` permission. For command-line
mutations, prefer an API key because an API-key-only request is CSRF-exempt.
Cookie-authenticated unsafe requests must send the `adapt_csrf` cookie value
in the `X-CSRF-Token` header (or in the `csrf_token` form field).

Each authentication method requires an active user. An inactive user cannot
log in or authenticate with an existing session or API key.

Authentication endpoints:

- `GET /auth/login` - Login page (HTML)
- `POST /auth/login` - Login using form fields (`username`, `password`)
- `POST /auth/logout` - Logout current session
- `GET /auth/me` - Current authenticated user
- `PUT /auth/password` - Change the current user password
- `GET /profile` - Authenticated profile page

`PUT /auth/password` accepts `current_password` and `new_password`. A
successful change revokes all browser sessions for the user and returns a
message that tells the user to sign in again. The new password must pass the
password-strength check.

User API key endpoints (for the currently authenticated user):

- `POST /api/apikeys`
- `GET /api/apikeys`
- `DELETE /api/apikeys/{key_id}` — deactivates the key (`is_active = false`), returns `204`. The key record is retained in the database but will no longer authenticate.

## Base URL

Default local URL: `http://localhost:8000`

## Generated Dataset APIs

For dataset resources (CSV, Excel sheets, Parquet), Adapt generates routes under:

- `/api/{resource}/`
- `/schema/{resource}/`
- `/ui/{resource}/`

Examples:

- CSV `products.csv` -> `/api/products/`
- Excel `inventory.xlsx` sheet `Stock` -> `/api/inventory/Stock/`
- Legacy Excel `inventory.xls` sheet `Stock` -> `/api/inventory/Stock/`

Legacy `.xls` routes support read and schema requests. Their mutation requests
return `405` because legacy workbooks are read-only.

### List Records

**GET** `/api/{resource}/`

Query parameters:

- `limit` (optional)
- `offset` (optional, default `0`)
- `sort` (optional)
- `order` (optional: `asc` or `desc`, default `asc`)
- `filter` (optional JSON string)

Example:

```bash
curl -H "X-API-Key: key" "http://localhost:8000/api/products/?limit=10&sort=name&order=asc"
```

### Mutations (Create, Update, Delete)

Adapt uses action-based mutation payloads at the collection endpoint.

**POST** `/api/{resource}/`

```json
{
  "action": "create",
  "data": [
    {
      "name": "Keyboard",
      "price": 49.99,
      "category": "Electronics",
      "in_stock": true
    }
  ]
}
```

**PATCH** `/api/{resource}/`

```json
{
  "action": "update",
  "data": {
    "_row_id": 1,
    "price": 39.99
  }
}
```

**DELETE** `/api/{resource}/`

```json
{
  "action": "delete",
  "data": {
    "_row_id": 1
  }
}
```

Notes:

- Dataset mutations are row-oriented and use `_row_id`.
- FastAPI requires the request body to be a JSON object, but dataset values
  are not validated against the inferred or companion schema.
  Unknown or incompatible values can therefore be written to the backing file.
- In read-only mode, mutation endpoints return `405`.
- Legacy `.xls` resources are always read-only and return `405` for mutations.

See [Known Limitations](known_limitations.md#schema-validation) for the effect
of this validation limit.

## Schema Endpoint

**GET** `/schema/{resource}/`

Returns the inferred or companion schema.

For CSV and Excel resources, inference assigns only `string`, `integer`,
`number`, or `boolean`. These types control response serialization and the
default dataset UI columns; they are descriptive metadata, not write
validators. A hand-maintained companion schema has the same limitation.

Example:

```bash
curl -H "X-API-Key: key" http://localhost:8000/schema/products/
```

## Content Endpoints

For HTML and Markdown resources, Adapt mounts content routes using file path namespaces.

- HTML content route: `/{resource}`
- Markdown content route: `/{resource}`

Depending on mount namespace, resources may also be available with extension-qualified paths.

Examples:

- `readme.md` -> `/readme`
- `index.html` -> `/index`

## Media Endpoints

Media resources generate:

- Streaming endpoint: `/media/{resource}`
- Player UI: `/ui/{resource}`
- Gallery UI: `/ui/media`

Example:

```bash
curl -H "X-API-Key: key" http://localhost:8000/media/sample.mp4
```

## Python Handler Endpoints

Python handler files (`.py`) with an `APIRouter` named `router` are mounted under:

- `/api/{handler_name}`

Example:

- `reports.py` with `@router.get("/summary")` -> `/api/reports/summary`

## Search Endpoint

**GET** `/search`

Full-text search across every resource the caller is permitted to read —
datasets, Markdown, HTML, and media metadata all rank in one result list.
Results are filtered by permission *after* the index is queried, so `count`
never reveals the existence of a resource the caller cannot see.

Query parameters:

- `q` (optional; empty returns no results)
- `limit` (optional, default `20`, max `100`)
- `offset` (optional, default `0`)
- `type` (optional, comma-separated resource types, e.g. `csv,markdown`)

Example:

```bash
curl -H "X-API-Key: key" "http://localhost:8000/search?q=parental+leave&type=csv,markdown"
```

Returns JSON by default, or an HTML results page when the client sends
`Accept: text/html`. Each result includes `resource`, `type`, `title`,
`snippet`, `score`, and `ui_url`; dataset row hits also include `api_url` and
`row_id`.

The index is rebuilt incrementally on server startup (`search_on_startup`,
default `true`) and can be rebuilt on demand:

```bash
adapt reindex /path/to/docroot [--force]
```

## MCP Interface

Adapt mounts a [Model Context Protocol](https://modelcontextprotocol.io)
server at `/mcp/`, exposing the same permission-filtered read/write/search
functionality as tools for agentic clients. See the [MCP Guide](mcp_guide.md)
for a full walkthrough from account creation to connecting a client.

| Tool | Equivalent to |
|---|---|
| `list_resources` | `GET /` (JSON) |
| `get_schema` | `GET /schema/{resource}/` |
| `read_resource` | `GET /api/{resource}/` |
| `write_resource` | `POST`/`PATCH`/`DELETE /api/{resource}/` |
| `search` | `GET /search` |

Authentication is enforced when a tool executes, not while the client
initializes or discovers tools. MCP uses Adapt's shared authentication
resolver, which accepts either a session cookie or an API key. API keys are
the supported and recommended mechanism for MCP clients. Set
`mcp_enabled: false` in `.adapt/conf.json` (or `ADAPT_MCP_ENABLED=false`) to
remove `/mcp/` entirely.

## Admin Endpoints

All admin endpoints require superuser authentication and are prefixed with `/admin`.

Users:

- `GET /admin/users`
- `POST /admin/users`
- `PUT /admin/users/{user_id}/password`
- `PUT /admin/users/{user_id}/status`
- `DELETE /admin/users/{user_id}`

The password-reset request contains `new_password`. A successful reset revokes
all browser sessions for the target user. It does not revoke API keys.

The status request contains the Boolean `is_active` value. Deactivation
revokes browser sessions. API keys remain stored and cannot authenticate
until an administrator activates the user.

Groups:

- `GET /admin/groups`
- `GET /admin/groups/{group_id}`
- `POST /admin/groups`
- `DELETE /admin/groups/{group_id}`
- `POST /admin/groups/{group_id}/users/{user_id}`
- `DELETE /admin/groups/{group_id}/users/{user_id}`

Permissions:

- `GET /admin/permissions`
- `POST /admin/permissions`
- `DELETE /admin/permissions/{perm_id}`
- `GET /admin/groups/{group_id}/permissions`
- `POST /admin/groups/{group_id}/permissions/{perm_id}`
- `DELETE /admin/groups/{group_id}/permissions/{perm_id}`

Locks:

- `GET /admin/locks`
- `DELETE /admin/locks/{lock_id}`
- `POST /admin/locks/clean`

Cache:

- `GET /admin/cache`
- `DELETE /admin/cache`
- `DELETE /admin/cache/{key}` (requires `resource` query parameter)

API keys (admin-managed):

- `GET /admin/api-keys`
- `POST /admin/api-keys`
- `DELETE /admin/api-keys/{key_id}`

Audit logs:

- `GET /admin/audit-logs`

Audit entries are currently created for:

- Successful login and logout
- Password changes and administrator resets
- API-key creation and revocation
- User and group creation or deletion
- Group membership changes
- Permission creation, deletion, and group assignment changes
- Manual lock release and stale-lock cleanup
- Cache entry deletion and cache clearing

Dataset `POST`, `PATCH`, and `DELETE` operations are not currently audited.
See [Known Limitations](known_limitations.md#audit-coverage).

Admin UI page:

- `GET /admin/`

## System Endpoint

### Health

**GET** `/health`

- Unauthenticated callers receive base status info.
- Authenticated callers receive additional metrics.

Example fields:

- `status`
- `version`
- `timestamp`
- `uptime_seconds` (authenticated)
- `cache_size` (authenticated)
- `endpoint_count` (authenticated)

## Filtering, Sorting, and Pagination

Dataset and many admin list endpoints support:

- `filter` as JSON
- `sort`
- `order`
- `offset`
- `limit`

Supported filter operators include:

- `$eq`, `$ne`
- `$gt`, `$gte`, `$lt`, `$lte`
- `$contains`, `$startswith`, `$regex`
- `$and`

Example:

```bash
curl -H "X-API-Key: key" "http://localhost:8000/api/products/?filter={\"price\":{\"$gte\":100},\"category\":\"Electronics\"}"
```

## Common Error Codes

- `400` - Invalid request data
- `401` - Not authenticated
- `403` - Permission denied
- `404` - Resource not found
- `405` - Method not allowed (including read-only mode mutations)
- `409` - Some runtime write conflicts
- `422` - FastAPI request or parameter validation failure

Error bodies are not a single Adapt-specific envelope. FastAPI-generated and
most application errors use a `detail` member, for example:

```json
{"detail": "Not authenticated"}
```

Validation failures can use a list of structured objects under `detail`.
After lock acquisition retries are exhausted, the current implementation can
surface a server error instead of the intended `409` response.
See [Known Limitations](known_limitations.md#exhausted-lock-conflicts).

Manual navigation: [Previous: User Guide](user_guide.md) | [Index](index.md) | [Next: Admin Guide](admin_guide.md)
