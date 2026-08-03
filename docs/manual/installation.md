# Installation

[Previous](overview) | [Next](quick_start) | [Index](index)

## System Requirements

- Python 3.11 or higher
- `pip`
- SQLite (bundled with Python)

## Install from PyPI

```bash
pip install adapt-server

# With development dependencies:
pip install adapt-server[dev]
```

## Install from Source

```bash
git clone https://github.com/McInci/adapt.git
cd adapt
pip install -e .
```

The source checkout can contain changes that are newer than the published
`adapt-server` release on PyPI. Identify which source or package version you use
when you compare behavior with this documentation.

## First Run

```bash
mkdir my-adapt-server
cd my-adapt-server
# Add some files here, e.g. data.csv, readme.md, etc.
adapt addsuperuser --username admin .
adapt serve .
```

Open `http://localhost:8000`.

## Core CLI Commands

```bash
adapt serve <directory> [options]
adapt check <directory>
adapt addsuperuser <directory> --username <username>
adapt list-endpoints <directory>
```

## Admin CLI Commands

```bash
adapt admin list-resources <directory>
adapt admin create-permissions <directory> <resource>...
adapt admin list-groups <directory>
adapt admin list-users <directory>
adapt admin create-user <directory> --username <username> [--password <password>] [--superuser]
adapt admin delete-user <directory> --username <username>
adapt admin create-group <directory> --name <group>
adapt admin delete-group <directory> --name <group>
adapt admin add-to-group <directory> --username <username> --group <group>
adapt admin remove-from-group <directory> --username <username> --group <group>
```

## `serve` Options

```bash
adapt serve <directory> [OPTIONS]

Options:
  --host TEXT        Host to bind to
  --port INTEGER     Port to bind to
  --tls-cert PATH    Path to TLS certificate file
  --tls-key PATH     Path to TLS private key file
  --reload           Enable auto-reload for development
  --readonly         Start server in read-only mode
  --debug            Enable debug logging
```

Notes:

- `--tls-cert` and `--tls-key` must be provided together.
- `--readonly` blocks write operations.
- `adapt serve` sets `secure_cookies` from its direct TLS configuration. It
  sets the value to `true` only when both TLS files are configured. This
  overrides the value in `conf.json`.

## Configuration File

Adapt uses `DOCROOT/.adapt/conf.json`. It is created automatically on first run.

Supported top-level keys:

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

Environment overrides:

- `ADAPT_HOST`
- `ADAPT_PORT`
- `ADAPT_READONLY`
- `ADAPT_DEBUG`
- `ADAPT_MCP_ENABLED`

`ADAPT_PORT` accepts an integer from 1 through 65535. The three Boolean
variables accept `1`, `true`, `yes`, or `on` for true. They accept `0`,
`false`, `no`, or `off` for false. Boolean values are case-insensitive and can
have surrounding spaces.

Effective precedence for serve behavior:

1. Defaults
2. `conf.json`
3. Environment variables
4. `adapt serve` CLI arguments

## TLS Setup

```bash
adapt serve . --tls-cert /path/to/cert.pem --tls-key /path/to/key.pem
```

## Created Directory Structure

Adapt creates a `.adapt/` directory in docroot:

```text
your-data-directory/
├── data.csv
└── .adapt/
    ├── conf.json
    ├── adapt.db
    ├── data.schema.json
    └── data.index.html
```

## Verify Installation

```bash
adapt check .
```

[Previous](overview) | [Next](quick_start) | [Index](index)
