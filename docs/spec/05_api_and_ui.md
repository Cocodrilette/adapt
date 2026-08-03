# **Adapt Specification: API & UI**

> **Status:** This document is maintained as an implementation specification.
> The running code on `main` wins if they differ. This is not a roadmap or the
> authoritative user documentation. See the
> [documentation contract](../README.md) and [user manual](../manual/index.md).

## **1. Dynamic Route Generator**

### **Responsibilities**

* Generate CRUD routes for datasets
* Generate `/schema` route for datasets
* Generate HTML UI endpoints for datasets
* Generate direct content routes for HTML/Markdown files
* Mount Python handler routers
* Mount plugin-provided routers
* Build Admin UI routes
* Plugins may cache selected derived data. Generic file bodies and streamed
  media bodies are not cached, and GET responses are not cached uniformly.

The Dynamic Route Generator delegates the creation of specific routes to the plugins themselves via `get_route_configs`.

---

## **1.5. Landing Page**

### **Purpose**

Provide a user-friendly entry point for authenticated users with an overview of available resources.

### **Features**

* Welcome message and introduction to Adapt
* Quick start guide for new users
* Dynamic list of accessible resources (datasets, HTML, Markdown) filtered by user permissions
* Admin dashboard link for superusers
* Consistent navigation bar

### **Behavior**

* Accessible at root URL (`/`)
* Content adapts based on user authentication and permissions
* For unauthenticated users, shows public HTML/Markdown content
* For authenticated users, shows permission-filtered resources
* API clients receive JSON list of all resources

---

## **2. HTML UI Renderer (DataTables)**

### **Features**

* Sortable columns
* Global search
* Pagination
* Responsive layout
* Inline editing (PATCH)
* Row add (POST)
* Row delete (DELETE)
* Common navigation bar (with links to all resources, admin dashboard (for superusers), and logout)

### **Template System**

Dataset UIs use Jinja2 templates that extend `base.html` for consistent navigation. The default template (`datatable.html`) provides a full-featured DataTables interface with Bootstrap styling and modal forms for CRUD operations.

### **Customization**

`.adapt/*.index.html` companion files allow full UI replacement. During startup, Adapt generates these files with the default `datatable.html` template. Users can edit these files to customize the UI while retaining the base navigation and functionality. Rendering occurs during requests, not at startup, ensuring dynamic data is always fresh.

If no companion file exists, Adapt will create a new one from the original `datatable.html`.

---

## **2.5. Media Gallery UI**

### **Features**

* Card-based layout displaying media files with metadata and thumbnails
* Searchable by filename
* Responsive Bootstrap grid
* Direct links to individual player pages
* Common navigation bar

### **Individual Player Pages**

* Dedicated pages at `/ui/<filename>` for each media file
* HTML5 `<video>` or `<audio>` elements for playback
* Centered, responsive design
* Metadata display (duration, bitrate, artist, title, etc.)
* Streaming via `/media/<filename>` endpoints

### **Streaming Endpoints**

* HTTP range request support for efficient streaming
* Open-standard delivery for audio/video files
* No write operations supported

### **Metadata Extraction**

* Automatic extraction of duration, bitrate, sample rate, channels
* Tag extraction for title, artist, album, genre where available
* Metadata stored in companion files and displayed in UI

### **Thumbnail Generation**

* Automatic thumbnail generation for video files
* Base64-encoded JPEG thumbnails displayed in gallery cards
* Extracted from 1-second mark of video for preview

### **Template System**

Media UIs use Jinja2 templates extending `base.html`. The gallery uses `media_gallery.html` with Bootstrap cards and JavaScript search. Individual players use `media_player.html` with embedded media elements.

---

## **3. Python Handler Loader**

### **Behavior**

Any `*.py` file with:

```python
from fastapi import APIRouter
router = APIRouter()
```

…is mounted at `/api/<name>/*`.

### **Uses**

* Business logic
* API composition
* Computed endpoints
* Authentication layers
* User-defined microservices

---

## **4. Admin UI**

The Admin UI is backed by REST endpoints at `/admin/*`. All admin endpoints require superuser privileges.

### **Modules**

#### **Users**
* Create, update, delete
* Change password
* Assign to groups

#### **Groups**
* Create/delete groups
* Manage membership
* Assign permissions

#### **Permissions**
* Full permission matrix
* `GET/POST/DELETE /admin/permissions`

#### **System**
* Active locks (Force unlock)
* Cache viewer (Inspect and clear cache entries)
* Health check endpoint (`/health`)

#### **API Keys**
* Generate new keys
* Revoke keys
* View key metadata

#### **Audit Logs**
* View system activity
* Filter by user, action, or resource

---

## **5. Error Handling**

Adapt does not impose one uniform error envelope. FastAPI request validation
and most application `HTTPException` responses use a `detail` member:

```json
{
  "detail": "Not authenticated"
}
```

FastAPI validation failures return `422` and place structured error objects in
the `detail` list. Dataset values are not validated against inferred or
companion schemas. Some runtime write conflicts return `409`; an exhausted
lock retry currently can surface as a server error instead.

---

## **6. MCP Interface**

### **Purpose**

Expose the same permission-filtered discovery, read, write, and search
functionality the REST API and browser UI already provide, through the Model
Context Protocol so agentic tool-callers can talk to Adapt natively — without
standing up a second, parallel API surface.

### **Transport**

A [`FastMCP`](https://pypi.org/project/mcp/) streamable-HTTP server is mounted
at `/mcp` on the same FastAPI app `adapt serve` runs — one process, one port,
the same TLS/host configuration as the rest of Adapt. There is no separate
`stdio` transport or CLI subcommand.

### **Tools**

| Tool | Equivalent to | Description |
|---|---|---|
| `list_resources` | `GET /` (JSON) | Every resource namespace the caller may read, with its type. |
| `get_schema` | `GET /schema/<ns>` | Columns and types for a dataset resource. |
| `read_resource` | `GET /api/<ns>` | Read a resource's content, with `limit`/`offset`/`sort`/`order`/`filter` for datasets. |
| `write_resource` | `POST`/`PATCH`/`DELETE /api/<ns>` | Create, update, or delete rows in a writable (dataset) resource. |
| `search` | `GET /search` | Full-text search across every resource the caller may read. |

`read_resource` / `write_resource` call the same `Plugin.read()` /
`Plugin.write()` methods the REST routes call — every plugin's existing
behavior transfers with no duplication. Non-dataset plugins (`markdown`,
`html`, `media`, `python`) raise `NotImplementedError` from `write()`, which
tools report back as an error naming the resource type.

Media resources appear in `list_resources` / `search` results with their
existing `/media/<path>` and `/ui/<path>` URLs, but streaming the raw bytes
through a tool call is out of scope — that's left to an HTTP client, the same
way `FileResponse` and range requests already work for the REST API.

### **Authentication & Authorization**

Tools reuse `adapt.auth.dependencies.get_current_user()`,
`check_permission()`, and `PermissionChecker.readable_resources()` — the
identical mechanism and permission semantics the REST API and `/openapi.json`
use. The shared resolver accepts either the `adapt_session` cookie or the
`X-API-Key` header. API keys are the supported and recommended mechanism for
MCP clients. Authentication is enforced when a tool executes, rather than
during MCP initialization or tool discovery. A superuser bypasses permission
checks exactly as elsewhere.

Admin operations (users/groups/permissions/locks/cache/audit) are **not**
exposed as MCP tools. MCP is an agent-facing *document* interface; admin
stays REST-only, superuser-gated through the browser/API-key admin UI.

### **Read-only mode**

`write_resource` checks `AdaptConfig.readonly` before touching a plugin and
returns the same "Server is in read-only mode" message REST callers get for
a 405.

### **Configuration**

The `mcp_enabled` key in `.adapt/conf.json` (default `true`) controls whether
`/mcp` is mounted; it can also be set via the `ADAPT_MCP_ENABLED` environment
variable. Disabling it removes the route entirely rather than returning an
error for every call.
