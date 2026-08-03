# Configuration

This guide documents configuration behavior currently implemented in Adapt.

## Configuration File

Adapt reads configuration from:

- `DOCROOT/.adapt/conf.json`

If the file does not exist, Adapt creates it with defaults on first load.

## Supported Top-Level Keys

Current accepted keys are:

- `plugin_registry`
- `host`
- `port`
- `tls_cert`
- `tls_key`
- `secure_cookies`
- `search_on_startup`
- `readonly`
- `debug`
- `mcp_enabled`
- `logging`

Unknown keys are treated as configuration errors.

## Source Precedence

Effective precedence (later overrides earlier):

1. Built-in defaults
2. `conf.json`
3. Environment variables
4. `adapt serve` CLI arguments

Environment variables currently supported:

- `ADAPT_HOST`
- `ADAPT_PORT`
- `ADAPT_READONLY`
- `ADAPT_DEBUG`
- `ADAPT_MCP_ENABLED`

`ADAPT_HOST` accepts a host string. `ADAPT_PORT` accepts an integer from 1
through 65535. The Boolean variables are `ADAPT_READONLY`, `ADAPT_DEBUG`, and
`ADAPT_MCP_ENABLED`. They accept these case-insensitive values:

- True: `1`, `true`, `yes`, `on`
- False: `0`, `false`, `no`, `off`

Adapt removes surrounding spaces before it reads a Boolean value. An invalid
Boolean value or port stops configuration loading.

## Example `conf.json`

```json
{
  "host": "127.0.0.1",
  "port": 8000,
  "readonly": false,
  "debug": false,
  "mcp_enabled": true,
  "tls_cert": null,
  "tls_key": null,
  "secure_cookies": false,
  "search_on_startup": true,
  "plugin_registry": {
    ".csv": "adapt.plugins.csv_plugin.CsvPlugin",
    ".xlsx": "adapt.plugins.excel_plugin.ExcelPlugin",
    ".xls": "adapt.plugins.excel_plugin.ExcelPlugin",
    ".parquet": "adapt.plugins.parquet_plugin.ParquetPlugin",
    ".py": "adapt.plugins.python_plugin.PythonHandlerPlugin",
    ".html": "adapt.plugins.html_plugin.HtmlPlugin",
    ".txt": "adapt.plugins.file_plugin.FilePlugin",
    ".pdf": "adapt.plugins.file_plugin.FilePlugin",
    ".json": "adapt.plugins.file_plugin.FilePlugin",
    ".xml": "adapt.plugins.file_plugin.FilePlugin",
    ".svg": "adapt.plugins.file_plugin.FilePlugin",
    ".png": "adapt.plugins.file_plugin.FilePlugin",
    ".jpg": "adapt.plugins.file_plugin.FilePlugin",
    ".jpeg": "adapt.plugins.file_plugin.FilePlugin",
    ".gif": "adapt.plugins.file_plugin.FilePlugin",
    ".webp": "adapt.plugins.file_plugin.FilePlugin",
    ".md": "adapt.plugins.markdown_plugin.MarkdownPlugin",
    ".mp4": "adapt.plugins.media_plugin.MediaPlugin",
    ".mp3": "adapt.plugins.media_plugin.MediaPlugin",
    ".avi": "adapt.plugins.media_plugin.MediaPlugin",
    ".mkv": "adapt.plugins.media_plugin.MediaPlugin",
    ".webm": "adapt.plugins.media_plugin.MediaPlugin",
    ".ogg": "adapt.plugins.media_plugin.MediaPlugin",
    ".wav": "adapt.plugins.media_plugin.MediaPlugin"
  },
  "logging": {
    "version": 1,
    "disable_existing_loggers": false,
    "formatters": {
      "json": {
        "class": "pythonjsonlogger.jsonlogger.JsonFormatter",
        "format": "%(asctime)s %(name)s %(levelname)s %(message)s"
      }
    },
    "handlers": {
      "console": {
        "class": "logging.StreamHandler",
        "formatter": "json",
        "stream": "ext://sys.stdout"
      }
    },
    "root": {
      "level": "INFO",
      "handlers": ["console"]
    }
  }
}
```

## Serve-Time CLI Overrides

`adapt serve` supports:

- `--host`
- `--port`
- `--tls-cert`
- `--tls-key`
- `--reload`
- `--readonly`
- `--debug`

TLS note:

- `--tls-cert` and `--tls-key` must be provided together.
- `--reload` starts Uvicorn file watching for Python files in the document root.
  Uvicorn restarts Adapt after a change.
- `adapt serve` sets `secure_cookies` to `true` only when it uses both TLS
  files. It sets the value to `false` without direct TLS. This serve-time value
  overrides `conf.json`.

## MCP Interface

`mcp_enabled` (default `true`) controls whether the MCP server is mounted at
`/mcp`. Set it to `false` in `conf.json` or via `ADAPT_MCP_ENABLED=false` to
remove the route entirely — useful for deployments that only want the REST
API surface. See the [MCP Guide](mcp_guide.md) for setup.

## Plugin Registry Notes

The default registry shown above matches `AdaptConfig.plugin_registry`. The
Excel plugin reads `.xlsx` and `.xls` files. Legacy `.xls` resources are
read-only. Unregistered extensions are not discovered or served.
See [Known Limitations](known_limitations.md#legacy-excel-files).

The generic `FilePlugin` serves these registered types directly:

- Text: `.txt`, `.pdf`, `.json`, `.xml`, `.svg`
- Images: `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`

`plugin_registry` values must use dotted class paths, for example:

```json
{
  "plugin_registry": {
    ".myext": "my_plugin.plugin.MyPlugin"
  }
}
```

## Validation and Diagnostics

Use `adapt check` to validate config and discovery:

```bash
adapt check /path/to/docroot
```

Typical checks:

- configuration loading and key validation
- creation or reuse of `.adapt/adapt.db`
- storage initialization
- resource discovery and a resource count
- TLS file warnings
- top-level route-collision warnings

The command does not migrate resource schemas or list each discovered
resource.

## Common Configuration Issues

1. Invalid JSON in `conf.json`
2. Unknown top-level key
3. Wrong type for `port`, `readonly`, or `debug`
4. Invalid plugin class path
5. TLS cert/key only partially set

Manual navigation: [Previous: MCP Guide](mcp_guide.md) | [Index](index.md) | [Next: Plugin Development](plugin_development.md)
