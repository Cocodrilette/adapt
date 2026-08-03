# Known Limitations

This page lists important limitations in the running implementation on `main`.
The workarounds apply until the implementation changes.

## File Support

### Legacy Excel Files

Adapt can discover and read each sheet in a legacy `.xls` workbook. The API,
schema, search index, and DataTables UI support these sheets.

Legacy `.xls` sheets are read-only. A `POST`, `PATCH`, or `DELETE` request
returns `405`. Convert the workbook to `.xlsx` before you modify it through
Adapt. This restriction prevents formula and workbook-feature loss.

## Server and CLI

### Reload Mode

The `--reload` option is accepted, but it does not activate Uvicorn file
watching. Restart the server after a source change.

### Endpoint Listing

`adapt list-endpoints` reports paths from discovered resource descriptors. It
can omit sub-resources such as Excel sheets. It does not show the effective
application route table.

Use this command as a best-effort diagnostic. When you need complete route
coverage, inspect the application route table.

## Plugin Interface

### Plugin Detection

`Plugin.detect()` is an abstract interface method. Resource discovery selects
plugins from `plugin_registry` by file extension and does not call `detect()`.

Custom plugins must implement this unused method. Treat the registry mapping
as the current plugin-selection mechanism.

## Dataset Writes

### Schema Validation

Dataset writes are not validated against inferred or companion schemas. These
schemas control serialization and UI columns. They are not write validators.

If the backing file requires a strict schema, validate values before a write.
A custom plugin can implement additional validation.

### Exhausted Lock Conflicts

Adapt retries lock acquisition with exponential backoff. If all retries fail,
the conflict can return a server error instead of `409 Conflict`.

Inspect `/admin/locks` and the server log after this error. Then retry the
write after the competing operation finishes.

### Write-Level Row Security

`Plugin.filter_for_user()` filters direct dataset reads. The shared search
index does not apply this filter at the row level.

The shared mutation path does not safely enforce row-level security for
writes. Row-level security therefore does not cover all reads and writes.

Do not use this hook as write authorization. If a plugin requires row-level
write authorization, implement and test a custom write path.

Do not index rows that contain data with per-user access restrictions.

## Audit Coverage

Adapt records selected authentication and administrative actions. Dataset
`POST`, `PATCH`, and `DELETE` operations do not create audit entries.

The audit log is not a complete history of writes. When a complete request
history is required, use access logs from a trusted reverse proxy.

## Authentication

### Inactive Users

Authentication does not enforce the `is_active` value for a user. Login,
session, and API-key authentication can accept an inactive user.

When access must stop, revoke all sessions and API keys for the user. If the
account is no longer required, delete the user.

### Password Changes

Adapt has no supported workflow to change the password of an existing user.
The Profile UI manages API keys but does not manage passwords.

The admin API and CLI can create or delete users. They cannot set a new
password for an existing user.

When a password must change, create a replacement account. Assign its access
before you delete the old account.

## Package Versions

The repository can contain changes that are newer than the published
`adapt-server` package on PyPI. When you compare behavior with this manual,
record the source commit or installed package version.

## Related Guides

- [Installation](installation.md)
- [API Reference](api_reference.md)
- [Admin Guide](admin_guide.md)
- [Security](security.md)
- [Configuration](configuration.md)
- [Plugin Development](plugin_development.md)
- [Architecture](architecture.md)
- [Troubleshooting](troubleshooting.md)

Manual navigation: [Previous: Troubleshooting](troubleshooting.md) | [Index](index.md)
