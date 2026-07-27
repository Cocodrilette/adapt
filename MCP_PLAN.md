# Implementation Plan: MCP Interface

Status: proposed (not yet implemented)
Target release: `0.3.0` (new feature; depends on `0.2.4`'s permission-filtered
OpenAPI document and the `/search` endpoint)

Adapt already has everything an agent needs — permission-filtered discovery
(`/openapi.json`, fixed in `0.2.4`), cross-resource search (`/search`), and
per-resource read/write with the same permission model REST clients use. What
it lacks is a protocol agentic tool-callers speak natively. This plan adds a
Model Context Protocol server, mounted on the same FastAPI app `adapt serve`
already runs, exposing that existing functionality as MCP tools rather than
building a second, parallel API surface.

Decisions below were confirmed with the user before drafting: HTTP transport
mounted in-process (not a separate `stdio` subcommand), tools cover both read
and write, and authentication reuses the existing API-key mechanism rather
than standing up MCP's OAuth flow.

---

## Design decisions (settled)

**Dependency.** [`mcp`](https://pypi.org/project/mcp/) (the official Python
SDK), `>=1.28,<2`. Verified installable in this project's venv (1.28.1);
its own constraints (`starlette>=0.27`, `httpx`, `pydantic>=2.11`) don't
conflict with anything already pinned in `pyproject.toml`.

**Transport.** `mcp.server.fastmcp.FastMCP.streamable_http_app()`, mounted at
`/mcp` via `app.mount("/mcp", mcp_app)` inside `create_app()`. One process,
one port, same TLS/host config the rest of Adapt already has — no new CLI
subcommand, no second server to run and secure separately.

**The lifespan gotcha (verified).** Starlette's `Mount` only forwards `http`
and `websocket` scope types to a mounted sub-app —
`Mount.matches` checks `scope["type"] in ("http", "websocket")` — so a
mounted app's own `lifespan` context manager is *never* invoked by the ASGI
server. `FastMCP.streamable_http_app()` returns a `Starlette` instance whose
`lifespan` starts `self.session_manager.run()`; if that never runs, every
request to `/mcp` hangs or errors with no obvious cause. `create_app()`
already defines its own `lifespan()` for the session-cleanup task; the MCP
session manager's `run()` context must be entered from inside that same
function:

```python
mcp_app = mcp_server.streamable_http_app()   # creates session_manager as a side effect

@asynccontextmanager
async def lifespan(app: FastAPI):
    cleanup_task = asyncio.create_task(cleanup_expired_sessions(engine))
    async with mcp_server.session_manager.run():
        yield
    cleanup_task.cancel()
    ...
```

`FastMCP.session_manager` is a public property specifically documented for
"mounting multiple FastMCP servers in a single FastAPI application" — this
isn't reaching into a private API.

**The `request.app` gotcha (verified) — and the fix that sidesteps it.**
`Starlette.__call__` does `scope["app"] = self` unconditionally, including
inside a mounted sub-app's own `__call__`. So inside an MCP tool,
`ctx.request_context.request.app` is `mcp_app`, **not** the main `app` — any
existing helper that reads `request.app.state.db_engine` /
`.resources` / `.config` would silently break if called from a tool with the
main app's request.

Fix: after building `mcp_app`, mirror the relevant slice of app state onto
it:

```python
mcp_app.state.db_engine = engine
mcp_app.state.resources = resources
mcp_app.state.config = config
mcp_app.state.resource_registry = resource_registry   # see Phase 0
```

With that done, `ctx.request_context.request` behaves like any other
request for the purposes of every helper this plan reuses —
`get_current_user()`, `PermissionChecker`, `check_permission()`, and
`_run_search()` all key off `request.app.state.*` and need no modification.
Verified by grep: no plugin's `read()` or `write()` method touches
`request.app` at all (only their route-closure wrappers in
`get_route_configs()` do, which this plan bypasses by calling `plugin.read` /
`plugin.write` directly).

**Auth.** Reuse `adapt.auth.dependencies.get_current_user(request)` as-is —
it already checks the `X-API-Key` header after the session cookie, and MCP
clients only ever have the former. No new auth code. A tool with no
resolvable user raises `ToolError("Authentication required...")`; MCP has no
concept of an anonymous session the way an HTML page does, so every tool
requires auth (unlike `/openapi.json`'s anonymous-public-paths case).

**Authorization.** Reuse `adapt.auth.dependencies.check_permission(user, db,
action, resource)` per-resource, and `PermissionChecker.readable_resources()`
for the list/search tools — identical semantics to the REST API and to
`/openapi.json`'s filtering. A superuser bypasses checks exactly as
elsewhere.

**Readonly mode.** `write_resource` checks `config.readonly` before touching
a plugin, raising `ToolError("Server is in read-only mode")` — the same
message REST callers get for a 405.

**Tool scope.** `read_resource` / `write_resource` call `Plugin.read()` /
`Plugin.write()` directly — the same methods the REST routes call, so every
plugin's existing behavior transfers with no duplication. Non-dataset
plugins (`markdown`, `html`, `media`, `python`) already raise
`NotImplementedError` from `write()`; the tool catches that and turns it into
a `ToolError` naming the resource type. This needs no special-casing per
plugin.

**Out of scope for `0.3.0`** (flagged explicitly, not silently dropped):
- Admin operations (users/groups/permissions/locks/cache/audit). MCP is an
  agent-facing *document* interface; admin stays REST-only and superuser-gated
  through the browser/API-key admin UI, same as today.
- Streaming media bytes through a tool call. `media_plugin.read()` returns a
  file path meant for `FileResponse` + HTTP range requests, which doesn't map
  onto a single JSON-returning tool call. Media resources still appear in
  `list_resources` / `search` results with their existing `/media/<path>` and
  `/ui/<path>` URLs; fetching the bytes is left to an HTTP client, not a tool.
- MCP OAuth / dynamic client registration. Deferred; API keys are already
  provisioned through `/admin/api-keys` and `/api/apikeys`.
- `stdio` transport / a `adapt mcp` CLI subcommand. Can be added later behind
  the same tool implementations if a desktop-client use case shows up; nothing
  in this design blocks it.

---

## Phase 0 — Shared resource registry (`adapt/routes.py`)

Namespace computation (`relative_path` with/without extension, plus
`sub_namespace`) is already duplicated three times — `adapt/app.py`'s
`_resource_namespaces`, `adapt/utils/__init__.py`'s `build_ui_links` /
`build_accessible_ui_links`, and inline in `generate_routes`. MCP tools need
a namespace → `(Plugin, ResourceDescriptor)` lookup that doesn't exist yet in
any of them (route closures build a descriptor and immediately capture it in
a closure; nothing keeps a lookup table afterward). Rather than adding a
fourth ad hoc copy, extract one:

```python
@dataclass
class ResourceRegistryEntry:
    resource: DatasetResource
    plugin: Plugin
    descriptor: ResourceDescriptor
    namespaces: frozenset[str]


def resource_namespaces(resource: DatasetResource) -> frozenset[str]:
    """The permission namespace(s) a resource is addressable by: with and
    without its file extension, each with `/{sub_namespace}` appended if set.
    """
    no_ext = resource.relative_path.with_suffix("").as_posix()
    with_ext = resource.relative_path.as_posix()
    if "sub_namespace" in resource.metadata:
        suffix = f"/{resource.metadata['sub_namespace']}"
        no_ext += suffix
        with_ext += suffix
    return frozenset({no_ext, with_ext})


def build_resource_registry(
    resources: list[DatasetResource], config: AdaptConfig
) -> dict[str, ResourceRegistryEntry]:
    """Map every permission namespace to its plugin instance and descriptor.

    Shared by generate_routes() (route mounting) and the MCP tool layer, so
    descriptor construction and namespace computation can't drift between them.
    """
    registry: dict[str, ResourceRegistryEntry] = {}
    for resource in resources:
        plugin_cls = config.get_plugin_factory(resource.path.suffix)
        plugin = plugin_cls()
        descriptor = ResourceDescriptor(
            path=resource.path, resource_type=resource.resource_type,
            schema_path=resource.schema_path, ui_path=resource.ui_path,
            metadata=resource.metadata,
        )
        entry = ResourceRegistryEntry(resource, plugin, descriptor, resource_namespaces(resource))
        for ns in entry.namespaces:
            registry[ns] = entry
    return registry
```

`generate_routes` calls `build_resource_registry` once at the top and loops
over `registry.values()` instead of re-deriving plugin/descriptor/namespaces
inline — behavior-preserving (same plugin instantiation, same descriptor
fields, same namespace strings), covered by the full existing route-mounting
test suite. `adapt/app.py`'s `_resource_namespaces` /
`_all_resource_namespaces` become thin calls into
`adapt.routes.resource_namespaces` (or are removed in favor of it directly);
`_visible_resource_namespaces`'s per-resource loop is unaffected since it
only needs the namespace strings, not the registry.

`create_app()` stores the registry once: `app.state.resource_registry =
resource_registry`, and mirrors it onto `mcp_app.state` per the gotcha above.

---

## Phase 1 — Mount the MCP server (`adapt/mcp.py`, new)

```python
def build_mcp_server(resource_registry: dict[str, ResourceRegistryEntry], config: AdaptConfig) -> FastMCP:
    mcp = FastMCP(name="adapt", instructions=(
        "Adapt exposes file-backed datasets, documents, and media as "
        "permission-filtered tools. Call list_resources first to see what "
        "you can read; search works across everything you're permitted to see."
    ))

    @mcp.tool()
    async def list_resources(ctx: Context) -> dict:
        """List every resource namespace the caller may read, with its type."""
        ...

    @mcp.tool()
    async def get_schema(resource: str, ctx: Context) -> dict:
        """Return the schema for a dataset resource (columns and types)."""
        ...

    @mcp.tool()
    async def read_resource(
        resource: str, ctx: Context,
        limit: int | None = None, offset: int = 0,
        sort: str | None = None, order: str = "asc",
        filter: dict | None = None,
    ) -> Any:
        """Read a resource's content, permission-checked like the REST API."""
        ...

    @mcp.tool()
    async def write_resource(
        resource: str, action: Literal["create", "update", "delete"],
        data: Any, ctx: Context,
    ) -> dict:
        """Create, update, or delete rows in a writable (dataset) resource."""
        ...

    @mcp.tool()
    async def search(
        q: str, ctx: Context,
        limit: int = 20, offset: int = 0, resource_type: str | None = None,
    ) -> dict:
        """Full-text search across every resource the caller may read."""
        ...

    return mcp
```

`create_app()`:

```python
mcp_server = build_mcp_server(resource_registry, config)
mcp_app = mcp_server.streamable_http_app()
mcp_app.state.db_engine = engine
mcp_app.state.resources = resources
mcp_app.state.config = config
mcp_app.state.resource_registry = resource_registry
app.mount("/mcp", mcp_app)
```

and `lifespan()` gains the `async with mcp_server.session_manager.run():`
wrapper described above.

### Auth/authorization helper (shared by every tool)

```python
async def _authenticated_user(ctx: Context) -> User:
    request = ctx.request_context.request
    user = get_current_user(request)
    if user is None:
        raise ToolError("Authentication required: send a valid X-API-Key header.")
    return user


def _authorized_entry(request: Request, user: User, namespace: str, action: str) -> ResourceRegistryEntry:
    entry = request.app.state.resource_registry.get(namespace)
    if entry is None:
        raise ToolError(f"Unknown resource: {namespace!r}")
    with Session(request.app.state.db_engine) as db:
        if not check_permission(user, db, action, namespace):
            raise ToolError(f"Permission denied: {action} on {namespace!r}")
    return entry
```

`read_resource` builds a `QueryParams` (dataset plugins) or calls
`plugin.read(descriptor, request)` (everything else — detect via
`resource_type in DATASET_TYPES`, the constant already defined in
`adapt/routes_search.py`, imported rather than redefined).

`write_resource` checks `config.readonly` first, sets
`request.state.user = user` (mirroring what `auth_middleware` does on the
main app, since the MCP sub-app has no such middleware and
`dataset_plugin.write()` reads `request.state.user` for the lock owner
name), builds a `PluginContext` directly from the closed-over `engine` /
`config.root` / `config.readonly` / `lock_manager` (no `request.app.state`
round-trip needed here since these are already in scope), and calls
`plugin.write(descriptor, {"action": action, "data": data}, request,
context)`. `NotImplementedError` and the plugin's own `HTTPException`s (405
readonly races, 409 lock conflicts) are both caught and re-raised as
`ToolError` with the same message.

`search` calls `adapt.routes_search._run_search(request, q, limit, offset,
resource_type, user)` directly — this is the "MCP as a thin wrapper over the
already permission-filtered search" the `SEARCH_PLAN.md` follow-on called
for. No reimplementation.

---

## Phase 2 — Config and dependency wiring

- `pyproject.toml`: add `"mcp>=1.28,<2"` to `dependencies`.
- `AdaptConfig`: add `mcp_enabled: bool = True`, following the existing
  `search_on_startup` precedent — no new CLI flag, just `.adapt/conf.json`
  and an `ADAPT_MCP_ENABLED` env override in `_apply_env_overrides` (same
  pattern as `ADAPT_READONLY`). `create_app()` skips mounting `/mcp` and
  entering `session_manager.run()` when disabled.
- `docs/spec/05_api_and_ui.md`: new "MCP Interface" section documenting the
  five tools, their permission model, and the `mcp_enabled` toggle.

---

## Tests (`tests/test_mcp.py`, new)

MCP's streamable-HTTP transport needs a real ASGI event loop serving SSE;
`fastapi.testclient.TestClient` doesn't speak the protocol. Tests spin up
the app with `uvicorn.Server` on an ephemeral port in a background thread
(a session-scoped-per-test fixture) and drive it with
`mcp.client.streamable_http.streamablehttp_client` + `mcp.ClientSession` —
the SDK's own documented pattern for testing a streamable-HTTP server.

1. `list_tools()` returns exactly the five tools; each has a non-empty
   description and a JSON schema for its arguments.
2. A call with no `X-API-Key` header (i.e., no way to authenticate) returns
   an `isError` result for every tool, not a transport-level failure.
3. `list_resources` / `search` / `read_resource` respect the same
   permission boundaries as the equivalent REST/`/openapi.json` tests
   already in `tests/test_integration.py` and `tests/test_search.py` — reader
   permitted on `a.csv` but not `b.csv` sees `a` and not `b` through every
   tool that can see either.
4. `write_resource` on a dataset succeeds for a permitted, non-readonly
   server and is reflected in a subsequent `read_resource`; fails with
   `ToolError` for an unpermitted user, a readonly server, and a
   non-dataset resource (markdown/html/media), in each case without leaking
   whether the resource merely doesn't exist vs. isn't writable.
5. `get_schema` on a dataset matches `GET /schema/<ns>`'s JSON exactly.
6. Version-shape canary mirroring `tests/test_routes.py`: build the MCP app,
   assert `mcp_server.session_manager` is reachable and `/mcp` is mounted —
   catches a future `mcp` release changing `streamable_http_app()`'s shape
   the same way the FastAPI upgrade broke `_build_openapi_schema`.
7. `mcp_enabled=False` mounts no `/mcp` route and the app still starts.

---

## Sequencing

Phase 0 (registry extraction) is pure refactor, ~1 hour, land and run the
full suite before touching anything MCP-specific — it touches the same
namespace logic `0.2.4`'s OpenAPI fix already made a point of centralizing.
Phases 1–2 together are the bulk of the work, roughly 1–2 days including the
uvicorn-backed test harness (the least familiar part — the tool logic itself
is thin by design). Land as `0.3.0`.
