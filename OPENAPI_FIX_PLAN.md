# Implementation Plan: Repair the Filtered OpenAPI Document

Status: implemented
Target release: `0.2.4` (bugfix; independent of the search feature)

`/openapi.json` currently advertises only `/` and `/health`. Every auth, admin,
and resource route is missing. Serving is unaffected — the endpoints all respond
normally — but introspection is empty, which guts the permission-filtered
OpenAPI document that is Adapt's primary agent-facing interface.

The same root cause produces all four failing tests.

---

## Root cause (verified)

FastAPI 0.140 / Starlette 1.3 changed `include_router`. Included routers no
longer flatten into `app.routes`; each appears as a single `_IncludedRouter`
wrapper. On this version `app.routes` holds 10 entries — 7 inline `APIRoute`s,
1 `Mount`, and 2 `_IncludedRouter`s standing in for 34 real routes.

Two call sites walk `app.routes` filtering `isinstance(route, APIRoute)` at the
top level only, so both silently drop everything mounted via `include_router`:

- `_build_openapi_schema` — `adapt/app.py:168`
- `_route_signatures` — `tests/test_readonly.py:16`

`pyproject.toml` sets no version bounds on `fastapi`, so a fresh install picks
this up automatically.

### The important correction

**`get_openapi()` already handles `_IncludedRouter` correctly.** Verified:

```python
get_openapi(title="t", version="1", routes=app.routes)   # -> all 34 paths, correct
```

So this is not a FastAPI limitation to work around. The bug is entirely in our
*pre-filtering*: `_build_openapi_schema` builds a plain list of top-level
`APIRoute`s and hands that already-lossy list to `get_openapi`. The wrappers are
discarded before `get_openapi` can expand them.

This rules out the obvious fix. A naive recursive walk that collects nested
`APIRoute` objects and passes them to `get_openapi` would be **worse than the
bug**: nested routes carry only their sub-path relative to the mount prefix
(`/` for a dataset router whose prefix is `/ui/data`), so every resource route
would collapse onto a single `/` entry in the document.

### Not affected

`adapt list-endpoints` derives its output from `discover_resources`, never from
`app.routes`. It is correct as written. (An earlier assessment in this
repository's session notes claimed otherwise; that was wrong.)

---

## Fix 1 — Filter the document, not the route list

Rewrite `_build_openapi_schema` to generate the full document first, then prune
it. This reuses FastAPI's own expansion, uses only public API, and works whether
routes are flattened or nested — so it survives the version moving again.

```python
def _build_openapi_schema(app: FastAPI, request: Request, user: User | None) -> dict:
    schema = get_openapi(
        title=app.title, version=app.version,
        description=app.description, routes=app.routes,
    )
    all_namespaces = _all_resource_namespaces(request.app.state.resources)
    visible_namespaces = _visible_resource_namespaces(request, user)

    visible_paths = {}
    for path, operations in schema.get("paths", {}).items():
        kept = {
            method: operation
            for method, operation in operations.items()
            if _operation_is_visible(path, operation, request, user,
                                     all_namespaces, visible_namespaces)
        }
        if kept:
            visible_paths[path] = kept

    schema["paths"] = visible_paths
    _prune_unreferenced_components(schema)
    return schema
```

`_route_is_visible(route, ...)` becomes `_operation_is_visible(path, operation, ...)`.
The logic is otherwise unchanged — it was already almost entirely path-based.
Two adjustments:

- `route.tags` becomes `operation.get("tags")`. Verified that `get_openapi`
  preserves tags per operation (an admin op carries `["admin"]`).
- The `route.include_in_schema` check is dropped. `get_openapi` already excludes
  those routes, so `/docs`, `/docs/oauth2-redirect` and `/openapi.json` never
  reach the filter.

`_normalize_path` still applies: `get_openapi` emits `/api/data/` with a
trailing slash, which it strips before matching.

### Prune orphaned components

Removing paths leaves their request/response models behind in
`components.schemas`. That is a real if minor leak — a non-superuser would
otherwise receive the field-level shape of `UserPublic`, `Group`, `Permission`
and every admin model. A security-filtered document should not ship them.

Collect every `$ref` reachable from the kept operations, resolve transitively
(models reference other models), and drop unreachable entries. Roughly 20 lines;
delete `components` entirely if nothing survives.

---

## Fix 2 — A shared effective-route helper

The readonly failures are **test-side bugs, not application bugs**: the routes
really are mounted and reachable, and `test_readonly.py`'s private
`_route_signatures` helper simply cannot see them. Application behavior is
already correct.

Rather than duplicate route-walking logic in the test file, add a public helper
to `adapt/routes.py` and have the test use it:

```python
def iter_effective_routes(routes, prefix: str = ""):
    """Yield (full_path, APIRoute) for every route, descending into included routers.

    FastAPI >= 0.140 represents `include_router` results as a single
    `_IncludedRouter` wrapper rather than flattening into `app.routes`; nested
    routes carry only their sub-path, so the mount prefix must be reapplied.
    Works on both the flattened and nested representations.
    """
    for route in routes:
        if isinstance(route, APIRoute):
            yield prefix + route.path, route
            continue
        context = getattr(route, "include_context", None)
        if context is not None:
            yield from iter_effective_routes(
                context.included_router.routes, prefix + (context.prefix or "")
            )
```

Verified against a live app: recovers all 37 routes, missing none of the 34 that
`get_openapi` produces. The 3 extra are exactly the `include_in_schema=False`
routes, which is correct for a route-level walk.

`_IncludedRouter` and `include_context` are FastAPI internals. Guard with
`getattr` (as above) so an older or newer FastAPI degrades to the flattened
path rather than raising, and cover it with the version-shape test below.

Then in `tests/test_readonly.py`:

```python
def _route_signatures(app):
    return sorted(
        f"{method} {path}"
        for path, route in iter_effective_routes(app.routes)
        for method in sorted(route.methods)
    )
```

This helper is also what a future MCP server needs to enumerate callable
endpoints, so it is worth having as real API rather than test scaffolding.

---

## Fix 3 — Pin the blast radius

This version bump has now produced three distinct breakages: the two OpenAPI
failures, the two readonly failures, and the `admin/ui.py` `TemplateResponse`
crash. All were invisible until a user hit them.

- Add bounds in `pyproject.toml`: `fastapi>=0.115,<0.141`, and pin `starlette`
  if the `TemplateResponse` signature matters to any remaining call site.
- Add a CI job at the lower and upper bound. The current workflows only publish;
  there is no test workflow, so the matrix is worth adding regardless.

---

## Tests

In `tests/test_integration.py` (the two failing tests should pass unmodified —
do not edit them to fit):

1. `/openapi.json` for an anonymous user contains `/auth/login`, `/`, `/health`
   and no resource, admin, or `/search` paths.
2. A user with read on `a.csv` but not `b.csv` sees `/api/a` and `/ui/a`, and
   neither `/api/b` nor `/ui/b`. The leak analogue of the search test.
3. A superuser sees admin paths; a non-superuser sees none.
4. `/search` appears for authenticated users only — this un-skips
   `test_search_is_advertised_to_authenticated_users_only` in
   `tests/test_search.py`, which is written and waiting.
5. `components.schemas` contains no admin model after filtering for a
   non-superuser.

New, in `tests/test_routes.py`:

6. `iter_effective_routes` yields the same path set that
   `get_openapi(routes=app.routes)` produces, modulo `include_in_schema=False`.
   This is the version-shape canary: it fails loudly if FastAPI changes the
   representation again, instead of silently returning an empty document.

---

## Sequencing

Fixes 1 and 2 are roughly half a day together including tests; Fix 3 is an hour.
Land as `0.2.4` alongside the `Optional` fix in `adapt/utils/query.py:87` and the
`admin/ui.py` `TemplateResponse` fix — all four are version-drift bugs in the
same family.

Do this **before** any MCP work. An MCP server is a thin wrapper over the
permission-filtered document; built on today's output it would expose two
endpoints.
