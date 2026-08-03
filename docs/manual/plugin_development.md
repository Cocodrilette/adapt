# Plugin Development

[Previous](configuration) | [Next](architecture) | [Index](index)

This guide describes the plugin APIs that are currently implemented in Adapt.

## Core Plugin Interfaces

Adapt plugin interfaces live in `adapt/plugins/base.py`.

### `PluginContext`

`PluginContext` provides shared execution context:

- `engine`
- `root`
- `readonly`
- `lock_manager`

### `ResourceDescriptor`

A discovered resource is represented by:

- `path`
- `resource_type`
- `schema_path`
- `ui_path`
- `metadata`

### `Plugin` Base Class

A plugin must implement:

- `detect(path)`
- `load(path)`
- `schema(resource)`
- `read(resource, request)`
- `write(resource, data, request, context)`

Optional extension points:

- `get_route_configs(descriptor)`
- `filter_for_user(resource, user, rows)`
- `default_ui(descriptor)`
- `generate_companion_files(descriptor)`

## How Discovery Works

Discovery scans docroot and selects plugins by file extension via `plugin_registry`.

Important behavior:

- Extension mapping is authoritative.
- `detect()` remains part of the plugin contract, but discovery currently selects plugin classes from extension mapping first.

## Plugin Registration

Configure plugins in `DOCROOT/.adapt/conf.json` under `plugin_registry`.

Use dotted class paths (not `module:Class`):

```json
{
  "plugin_registry": {
    ".csv": "adapt.plugins.csv_plugin.CsvPlugin",
    ".myext": "my_plugin.plugin.MyPlugin"
  }
}
```

## Route Mounting Model

Plugins return route configs as `(prefix, router)` pairs.

Generated mounting combines prefix and namespace into routes such as:

- `/api/<namespace>`
- `/schema/<namespace>`
- `/ui/<namespace>`
- `/media/<namespace>`

For each resource, Adapt mounts routes for both extensionless and extension-qualified namespaces where applicable.

## Implementing a Dataset-Style Plugin

Dataset-style plugins can inherit from `DatasetPlugin` to reuse schema/UI/mutation patterns.

Expected mutation contract:

- `POST /api/<resource>` with `{ "action": "create", "data": [...] }`
- `PATCH /api/<resource>` with `{ "action": "update", "data": { ... } }`
- `DELETE /api/<resource>` with `{ "action": "delete", "data": { ... } }`

Mutations should:

- Respect `context.readonly`
- Use `lock_manager` to avoid unsafe concurrent writes
- Invalidate cache after successful changes

The schema returned by `schema()` supplies serialization hints and UI column
metadata. Dataset mutation code does not use it to validate writes, including
when the schema is hand-maintained.

`filter_for_user()` is applied on dataset reads and is available as a
row-filtering extension point. The shared mutation implementation does not
provide safe write-level row-security enforcement: it reads and rewrites the
row collection, and row identifiers can diverge after filtering. A plugin
that needs row-level write authorization must implement and test its own
write path rather than relying on this hook.

## Example Skeleton

```python
from pathlib import Path
from typing import Any
from fastapi import Request

from adapt.plugins.base import Plugin, ResourceDescriptor, PluginContext


class MyPlugin(Plugin):
    def detect(self, path: Path) -> bool:
        return path.suffix.lower() == ".myext"

    def load(self, path: Path) -> ResourceDescriptor:
        return ResourceDescriptor(path=path, resource_type="myext")

    def schema(self, resource: ResourceDescriptor) -> dict[str, Any]:
        return {}

    def read(self, resource: ResourceDescriptor, request: Request) -> Any:
        return {"ok": True}

    def write(self, resource: ResourceDescriptor, data: Any, request: Request, context: PluginContext) -> Any:
        if context.readonly:
            raise RuntimeError("read-only mode")
        return {"success": True}
```

## Python Handler Plugins

The built-in Python handler plugin (`.py`) loads modules and mounts an `APIRouter` named `router` under `/api/<filename>`.

If import fails, the handler is skipped.

## Companion Files

Built-in dataset plugins generate companion files under `.adapt/`:

- `*.schema.json`
- `*.index.html`

Media plugins may write metadata-style companion content via `ui_path` handling.

A generated `*.schema.json` carries `"generated_by": "adapt"`. Adapt refreshes such a
file when the resource's shape changes, and leaves any schema without that key alone,
so hand-written schemas are never overwritten. The key is stripped before the schema is
served from `/schema/<resource>`.

### Resource Options

You may also hand-write `*.options.json` alongside the generated files to override how a
resource is parsed. The naming matches the other companion files — for the sheet
`Dashboard` in `report.xlsx`, that is `.adapt/report.Dashboard.options.json`.

Supported keys:

| Key | Applies to | Meaning |
| --- | --- | --- |
| `header_row` | `.xlsx` | 1-based row holding the column names. Defaults to `1`. |

Use `header_row` when a sheet opens with a title banner instead of column names — the
banner would otherwise be parsed as the header, turning a sentence into a column name:

```json
{ "header_row": 3 }
```

Rows above the header row are ignored on both read and write. An unreadable options file
or an invalid value is logged and ignored rather than raised, so a typo cannot take the
server down.

Plugins consume options by overriding `apply_options(descriptor)`, which discovery calls
after `load()` (which sees only a path, and so cannot locate the companion directory) and
before `generate_companion_files()` (so a derived schema reflects the options).

## Testing Recommendations

When creating plugins, test:

- Discovery and load behavior
- Schema generation
- Read/write behavior
- Read-only mode behavior
- Lock conflict behavior
- Route registration and endpoint responses

## Compatibility Notes

- Keep plugin class paths stable for `plugin_registry` users.
- Prefer additive schema changes when possible.
- Document any plugin-specific configuration keys clearly.

[Previous](configuration) | [Next](architecture) | [Index](index)
