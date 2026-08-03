# **Adapt Specification: CLI & Configuration**

> **Status:** This document is maintained as an implementation specification.
> The running code on `main` wins if they differ. This is not a roadmap or the
> authoritative user documentation. See the
> [documentation contract](../README.md) and [user manual](../manual/index.md).

## **1. CLI**

### **`adapt serve <path> [options]`**

Options include:

* `--host`
* `--port`
* `--tls-cert`
* `--tls-key`
* `--read-only`
* `--admin`
* `--log-level`

### **Operational Commands**

* `adapt check <root>` — initialize `.adapt.db`, migrate schemas, and list discovered datasets.
* `adapt addsuperuser <root> --username <name>` — create or warn if a superuser already exists in the configured SQLite store.
* `adapt list-endpoints <root>` — print every `/api/*`, `/schema/*`, and `/ui/*` path registered during discovery.

### **Administrative Commands**

* `adapt admin list-resources <root>` — list all discovered resources in the document root, including sub-namespaces for multi-resource files (e.g., Excel sheets).
* `adapt admin create-permissions <root> <resources>...` — create permissions and groups for specified resources (use `__all__` for all resources, including sub-namespaces). Supports `--all-group` and `--read-group` options to customize group naming.
* `adapt admin list-groups <root>` — display all groups with their associated permissions and assigned users.

---

## **2. Configuration**

### **Sources**

* `DOCROOT/.adapt/conf.json` (auto-created with defaults if missing)
* Environment variables
* CLI args
* Defaults

Precedence: CLI args > environment variables > `conf.json` > defaults.

### **Key Settings**

* `plugin_registry`: Dict mapping file extensions to plugin class paths (e.g., `".csv": "adapt.plugins.csv_plugin.CsvPlugin"`). Allows adding custom handlers.
* `host`: Host address for the server.
* `port`: Port for the server, from 1 through 65535.
* `tls_cert`: Path to TLS certificate file.
* `tls_key`: Path to TLS key file.
* `secure_cookies`: Boolean for setting secure flags on cookies.
* `search_on_startup`: Boolean that controls the startup refresh of the search index.
* `readonly`: Boolean that disables write routes.
* `debug`: Boolean that enables debug logging.
* `mcp_enabled`: Boolean that controls whether Adapt mounts `/mcp`.
* `logging`: Dict for Python logging configuration (dictConfig format), allowing customization of log levels, formatters, and handlers.

The environment can override `host`, `port`, `readonly`, `debug`, and
`mcp_enabled` through `ADAPT_HOST`, `ADAPT_PORT`, `ADAPT_READONLY`,
`ADAPT_DEBUG`, and `ADAPT_MCP_ENABLED`. Boolean environment variables accept
`1`, `true`, `yes`, or `on` for true. They accept `0`, `false`, `no`, or `off`
for false. These values are case-insensitive and can have surrounding spaces.

When `adapt serve` starts, it derives `secure_cookies` from direct TLS. Both
TLS files set secure cookies. Without both files, the command clears this
setting even if `conf.json` enables it. A TLS-terminating reverse proxy does
not change this calculation.

The default registry contains these extension groups:

* Datasets: `.csv`, `.xlsx`, `.xls`, `.parquet`
* Handlers and rendered content: `.py`, `.html`, `.md`
* Generic files: `.txt`, `.pdf`, `.json`, `.xml`, `.svg`, `.png`, `.jpg`,
  `.jpeg`, `.gif`, `.webp`
* Media: `.mp4`, `.mp3`, `.avi`, `.mkv`, `.webm`, `.ogg`, `.wav`

The Excel plugin rejects `.xls`, so this format is not currently readable.
The generic file mappings use `FilePlugin`, including the `.txt` mapping.
Discovery ignores unregistered extensions.

Invalid `conf.json` causes the server to exit with an error.

---

## **3. Logging and Metrics**

### **Logging**

* JSON structured logs (configurable via `logging` in `conf.json`)
* Write operations
* Lock events
* Admin actions

### **Metrics**

Optional Prometheus-like metrics at `/metrics`.
