# Troubleshooting

This guide covers common problems and verified troubleshooting steps for the current Adapt implementation.

## Server Startup Problems

### Port Already in Use

```bash
netstat -ano | findstr :8000
adapt serve . --port 8001
```

### Invalid Configuration

```bash
adapt check .
```

Check `.adapt/conf.json` for invalid keys or JSON syntax errors.

### TLS Startup Error

If one TLS flag is provided without the other, startup fails.

Use both together:

```bash
adapt serve . --tls-cert /path/to/cert.pem --tls-key /path/to/key.pem
```

## Authentication Problems

### Login Fails

- Confirm username exists
- Verify password
- Check user is active

Useful checks:

```bash
adapt admin list-users .
sqlite3 .adapt/adapt.db "SELECT username, is_active FROM users;"
```

### API Key Returns 401

- Confirm header format: `X-API-Key: <key>`
- Ensure key is active and not expired

```bash
curl -H "X-API-Key: your-key" http://localhost:8000/auth/me
```

## Authorization Problems (`403`)

- Verify group membership
- Verify resource permission names
- Confirm required action (`read` vs `write`)

Useful checks:

```bash
adapt admin list-groups .
adapt admin list-resources .
```

Generated API, schema, and UI routes require authentication plus the
corresponding resource permission. `create-permissions` creates individual
groups named `<resource>_readonly` and `<resource>_readwrite`; combined group
names include a suffix made from all selected resources.

### Cookie-Authenticated Mutation Returns `403`

Unsafe requests made with an `adapt_session` cookie must also send the
`adapt_csrf` cookie value in the `X-CSRF-Token` header. This remains true if
the request also includes an API key. For command-line mutations, use an API
key without a session cookie to avoid CSRF handling.

## Resource Discovery Problems

### Files Not Appearing

- Confirm file extension is supported by plugin registry
- Confirm file is under docroot
- Restart server after adding files

Supported built-in extensions are:

- Datasets: `.csv`, `.xlsx`, `.parquet`
- Rendered content: `.html`, `.md`
- Python handlers: `.py`
- Generic text and document files served by `FilePlugin`: `.txt`, `.pdf`,
  `.json`, `.xml`, `.svg`
- Generic image files served by `FilePlugin`: `.png`, `.jpg`, `.jpeg`, `.gif`,
  `.webp`
- Streamed media: `.mp4`, `.mp3`, `.avi`, `.mkv`, `.webm`, `.ogg`, `.wav`

`.xls` is present in the default plugin registry, but it is not currently
readable. Convert legacy Excel files to `.xlsx`. Unregistered extensions are
not discovered or served unless you add a plugin mapping for them.

### Companion Files Missing

Run discovery check:

```bash
adapt check .
```

Companion files are generated under `.adapt/` for supported resource types.

## Dataset Write Problems

### `405 Method Not Allowed`

Server may be in read-only mode.

```bash
adapt serve . --readonly
```

### `409 Conflict`

Some runtime write conflicts return `409`. Retry after a short delay. If lock
acquisition reaches its retry timeout, the current implementation can return
`500` instead of `409`; inspect `/admin/locks` and the server log.

### Write Payload Rejected

Dataset mutations require action envelope payloads on `/api/<resource>/`.

Example:

```json
{"action":"update","data":{"_row_id":1,"name":"Updated"}}
```

## Admin API Troubleshooting

Use implemented admin routes under `/admin`, for example:

- `/admin/users`
- `/admin/groups`
- `/admin/permissions`
- `/admin/locks`
- `/admin/cache`
- `/admin/api-keys`
- `/admin/audit-logs`

## Plugin Troubleshooting

### Custom Plugin Not Loading

Verify class path format in `plugin_registry`:

```json
{
  "plugin_registry": {
    ".ext": "module.path.ClassName"
  }
}
```

Current loader expects dotted class paths, not `module:path` syntax.

### Import Errors

Test import manually:

```bash
python -c "from module.path import ClassName"
```

## Useful Diagnostic Commands

```bash
adapt check .
adapt list-endpoints .
adapt admin list-resources .
adapt reindex .
```

`adapt check` initializes storage and reports a discovered-resource count. It
also reports TLS file problems and top-level route collisions. It does not
migrate resource schemas or list each resource.

`adapt list-endpoints` is a best-effort diagnostic. It can omit sub-resources,
including Excel sheets. Compare its output with the effective application
routes when complete route coverage is required.

`adapt reindex` rebuilds the full-text search index. Add `--force` to index
resources whose file metadata is unchanged.

## When to Collect Logs

Capture logs when reporting issues:

- startup failure output
- traceback for 500 errors
- request path and response code
- relevant config from `.adapt/conf.json`

Manual navigation: [Previous: Architecture](architecture.md) | [Index](index.md)
