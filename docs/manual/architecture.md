# Architecture

This document describes the current Adapt architecture.

## High-Level Design

Adapt is a FastAPI application that:

1. Loads configuration from `DOCROOT/.adapt/conf.json`
2. Initializes SQLite-backed storage and cache
3. Discovers resources in docroot using extension-to-plugin mapping
4. Generates API/UI/schema/media routes per discovered resource
5. Enforces authentication and authorization through dependencies

## Core Components

### Application Layer

Key responsibilities in `adapt/app.py`:

- app creation and shared state initialization
- middleware registration
- auth/admin router mounting
- dynamic route generation
- health and landing/media-gallery routes

### Discovery and Plugin Layer

Key modules:

- `adapt/discovery.py`
- `adapt/plugins/*`
- `adapt/routes.py`

Flow:

- Discovery scans docroot
- Extension determines plugin class via `plugin_registry`
- Plugin `load()` returns one or more resource descriptors
- Discovery assigns schema, UI, and options companion paths
- Plugin `apply_options()` can modify each descriptor
- Plugins can generate companion files under `.adapt/`
- Route configs from plugin are mounted into the app

The `detect()` method is part of the plugin interface. Current resource
discovery does not call it because the registry extension selects the plugin.

### Data and Security Layer

Key modules:

- `adapt/storage.py` (SQLModel tables + DB engine)
- `adapt/auth/*` (sessions, password, dependencies)
- `adapt/security.py` (CSRF + security headers)
- `adapt/locks.py` (lock manager)
- `adapt/cache.py` (SQLite-backed cache)

## Implemented Middleware and Security Flow

Current middleware stack includes:

- Trusted host middleware
- security middleware (CSRF validation + security headers)
- auth middleware (session user hydration)

Request flow for unsafe methods with session authentication:

1. CSRF token validated (`adapt_csrf` cookie + `X-CSRF-Token`)
2. user resolved from session or API key
3. endpoint dependency checks permission
4. route handler executes

## Route Generation Model

For each resource, plugins provide `(prefix, router)` pairs.

Routes are mounted with permission dependencies and namespace variants.

Each resource has an extensionless namespace and an extension-qualified
namespace. For example, `data.csv` uses both `data` and `data.csv`. An Excel
sheet adds its sub-namespace to both forms, such as `data/Sheet1` and
`data.xlsx/Sheet1`.

Common prefixes:

- `api`
- `schema`
- `ui`
- `media`

Dataset plugins use `ui_path` for an HTML template. The media plugin writes
JSON metadata to `ui_path` and renders its HTML player from the built-in
template.

## Data Model Summary

Primary tables include:

- `users`
- `groups`
- `permission`
- `usergroup`
- `grouppermission`
- `dbsession`
- `apikey`
- `auditlog`
- `lock_records`

All live in docroot-local SQLite (`.adapt/adapt.db`).

## Caching Model

Current cache implementation is SQLite-backed (`adapt/cache.py`).

- cache table name: `cache`
- TTL-based entries
- resource-scoped invalidation
- used by plugins and admin cache endpoints

Caching is plugin-specific, not a response-wide FastAPI cache. CSV, Excel,
and Parquet plugins cache parsed rows; dataset schemas are cached separately;
HTML and Markdown plugins cache rendered/read content; and the media plugin
caches extracted metadata. Generic file response bodies and streamed media
bodies are not cached.

## Locking Model

Locking uses DB records with per-resource uniqueness and expiration.

- one lock record can exist per resource
- lock acquisition retries with exponential backoff
- stale locks can be cleaned
- write operations use lock context manager
- built-in dataset writers replace the target atomically where supported

The lock timeout currently escapes as a server error instead of reliably
becoming a `409`. Locking and atomic replacement reduce risk but do not promise
that writes are race-free or cannot be interrupted.

## Observability

- Python logging configured via `conf.json` `logging` section
- audit logs available via `/admin/audit-logs`
- health endpoint at `/health`

## Deployment Notes

Current implementation is optimized for single-instance docroot-local operation.

Multi-instance, shared DB/cache, and websocket-style real-time update architectures are future design topics, not current built-in behavior.

Manual navigation: [Previous: Plugin Development](plugin_development.md) | [Index](index.md) | [Next: Troubleshooting](troubleshooting.md)
