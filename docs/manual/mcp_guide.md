# MCP Interface Guide

[Previous](security) | [Next](configuration) | [Index](index)

This guide walks through everything needed to let an agentic tool (Claude
Code, Claude Desktop, or any other [MCP](https://modelcontextprotocol.io)
client) talk to an Adapt server: creating an account, granting it
permissions, minting an API key, and pointing the client at `/mcp`.

## What Is the MCP Interface?

Adapt mounts a [Model Context Protocol](https://modelcontextprotocol.io)
server at `/mcp` on the same FastAPI app `adapt serve` already runs. It
exposes five tools — `list_resources`, `get_schema`, `read_resource`,
`write_resource`, and `search` — that wrap the exact same permission checks
and plugin methods the REST API and browser UI use. There is no separate API
surface and no separate process to run: if a user can read or write a
resource over `/api/*`, the same user can do it through MCP, and nothing
more.

Because MCP has no concept of an anonymous browser session, every tool call
must authenticate with an `X-API-Key` header. Session cookies are not
accepted here.

## Prerequisites

- Adapt installed (`pip install adapt-server`) and a docroot with at least
  one resource (see the [Quick Start](quick_start)).
- An MCP-capable client. This guide shows examples for the Claude Code CLI
  and a generic JSON config that works with most desktop MCP clients.

## Step 1: Create a Superuser and Start the Server

```bash
adapt addsuperuser /path/to/docroot --username admin
adapt serve /path/to/docroot
```

## Step 2: Create Permissions for Your Resources

This generates one `read`-only group and one `all`-permissions (`read`+`write`)
group per discovered resource, so you can assign users to the right one
without hand-building permission rows:

```bash
adapt admin create-permissions /path/to/docroot __all__
adapt admin list-groups /path/to/docroot
```

Pass specific resource namespaces instead of `__all__` if you only want
permissions generated for some resources.

## Step 3: Create a User for the Agent and Grant Access

Give the agent its own account rather than reusing the superuser's — it
keeps audit logs meaningful and lets you revoke access without touching
anything else.

```bash
adapt admin create-user /path/to/docroot --username agent --password <a-strong-password>
adapt admin add-to-group /path/to/docroot --username agent --group <resource>_readonly
```

Use the `<resource>_all` group instead (or in addition) if the agent should
also be able to create/update/delete rows via `write_resource`. Repeat
`add-to-group` for every resource namespace the agent needs.

## Step 4: Create an API Key

MCP authenticates with an API key, not a session cookie. Any authenticated
user can self-issue their own key — no superuser involvement needed — via
the **Profile** page in the browser, or from the command line by logging in
as `agent` and calling `POST /api/apikeys`:

```bash
curl -c /tmp/adapt-cookies.txt -X POST http://localhost:8000/auth/login \
  -d "username=agent&password=<a-strong-password>"

curl -b /tmp/adapt-cookies.txt -X POST http://localhost:8000/api/apikeys \
  -H "Content-Type: application/json" \
  -d '{"description": "mcp-agent-key"}'
```

The response's `"key"` field is the raw API key — save it somewhere safe;
only its hash is stored server-side.

A superuser can also mint (or revoke) a key on another user's behalf from
the admin UI (`/admin/` → **API Keys** → **Create**, choosing the `agent`
user) — useful for provisioning an agent's key without sharing its password,
but it's an admin convenience, not a requirement.

## Step 5: Verify the MCP Endpoint Is Reachable

```bash
curl -i -H "X-API-Key: <key>" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -X POST http://localhost:8000/mcp \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'
```

A `200 OK` with a JSON-RPC response body means the server is up and the key
is valid. A `401`-shaped tool error instead means the key is wrong, inactive,
or expired; see [Troubleshooting](#troubleshooting) below.

## Step 6: Point an Agentic Tool at It

### Claude Code (CLI)

```bash
claude mcp add --transport http adapt http://localhost:8000/mcp \
  --header "X-API-Key: <key>"
```

### Generic MCP Client Config (Claude Desktop and similar)

Most desktop clients that support remote/HTTP MCP servers accept a config
block similar to this — check your client's docs for the exact key names:

```json
{
  "mcpServers": {
    "adapt": {
      "url": "http://localhost:8000/mcp",
      "headers": {
        "X-API-Key": "<key>"
      }
    }
  }
}
```

Use `https://` and a certificate the client trusts once you're off
`localhost` — see [Security](security) for TLS setup.

## Step 7: What the Agent Can Do

| Tool | Equivalent REST call | Notes |
|---|---|---|
| `list_resources` | `GET /` (JSON) | Every namespace the agent may read, with its type. |
| `get_schema` | `GET /schema/{resource}` | Columns and types for a dataset resource. |
| `read_resource` | `GET /api/{resource}` | Accepts `limit`, `offset`, `sort`, `order`, `filter` for datasets. |
| `write_resource` | `POST`/`PATCH`/`DELETE /api/{resource}` | `action` is `"create"`, `"update"`, or `"delete"`; see the [mutation envelope](../../README.md#dataset-mutation-envelope). |
| `search` | `GET /search` | Full-text search across every resource the agent may read. |

Once the client is connected, ask the agent something like "what data do you
have access to?" — it should call `list_resources` on its own — or "search
for parental leave policy" to exercise `search`.

## Troubleshooting

- **"Authentication required" from every tool call** — the `X-API-Key`
  header is missing, misspelled, or the client isn't forwarding custom
  headers for HTTP MCP servers. Re-check Step 6.
- **"Permission denied: read/write on `<namespace>`"** — the agent's user
  isn't in a group with that permission. Revisit Step 3 and
  `adapt admin list-groups`.
- **"Unknown resource"** — the namespace doesn't match what `list_resources`
  reports; namespaces are the file's relative path without its extension
  (e.g. `products`, not `products.csv`), unless a `sub_namespace` (Excel
  sheet name) applies.
- **"Server is in read-only mode"** — the server was started with
  `--readonly` or `readonly: true` in `conf.json`; `write_resource` is
  disabled entirely regardless of permissions.
- **No `/mcp` route at all** — the server has `mcp_enabled: false` in
  `.adapt/conf.json` or `ADAPT_MCP_ENABLED=false` set. See
  [Configuration](configuration).

[Previous](security) | [Next](configuration) | [Index](index)
