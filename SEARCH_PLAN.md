# Implementation Plan: Unified, Permission-Aware Search

Status: Phases 1–2 implemented and tested; Phases 3–4 not started
Target release: `0.3.0`

Adapt can expose and serve every resource in a docroot, but it has no way to
*find* anything. The only search that exists today is client-side: DataTables'
per-table filter and a JS `filter()` over the media gallery
(`adapt/templates/media_gallery.html:36`). Markdown, HTML, and media have no
query interface at all, and the landing page is a flat list of links.

This plan adds a single cross-resource retrieval primitive — `GET /search` —
that both a new employee and an agentic client can use.

---

## Design decisions (settled)

**Namespace form.** Index and filter on the **no-extension** namespace —
`relative_path.with_suffix("").as_posix()` plus `/{sub_namespace}` when present.
This is what `adapt/admin/resources.py:25`, `adapt/utils/__init__.py:51`, and
`create-permissions` all use. `adapt/routes.py:57` also mounts a
*with-extension* namespace, but `create-permissions` never creates permissions
for that form, so filtering on it would deny everything. Use no-ext,
consistently.

**Storage.** A new FTS5 virtual table in the existing `.adapt/adapt.db`,
accessed with raw `sqlite3` — same pattern as `adapt/cache.py`. Verified
available: sqlite3 3.50.4 with FTS5 and `snippet()`/`bm25()` compiled in. No new
dependency.

**Filtering.** Post-query, against a permission set computed **once per
request**. Never pre-filter the FTS query, and never index per-user.

---

## Phase 1 — Index core (`adapt/search.py`, new, ~200 lines)

Mirror the `cache.py` module shape: module-level `_db_path`, `configure()`,
`_get_conn()`, a `threading.Lock`.

### Schema

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS search_docs USING fts5(
    title,
    body,
    namespace     UNINDEXED,
    resource_type UNINDEXED,
    doc_ref       UNINDEXED,   -- row id / anchor / NULL
    url           UNINDEXED,
    source_path   UNINDEXED,
    tokenize = "unicode61 remove_diacritics 2"
);
CREATE TABLE IF NOT EXISTS search_index_state (
    source_path   TEXT NOT NULL,
    sub_namespace TEXT NOT NULL DEFAULT '',
    namespace     TEXT NOT NULL,
    mtime REAL, size INTEGER, indexed_at TEXT,
    PRIMARY KEY (source_path, sub_namespace)
);
```

**Composite key, not `source_path` alone.** One `.xlsx` yields one descriptor
*per sheet*, each with its own namespace. A single-column primary key would
collapse them, and `DELETE ... WHERE source_path = ?` on reindex would wipe
Sheet2 while refreshing Sheet1. All index writes and deletes key on
`(source_path, namespace)`. There is a regression test for this.

Set `PRAGMA journal_mode=WAL` on first connect. Note this is a persistent
property of the whole database file, so it affects the SQLModel engine too —
a net win for concurrent reads, but a real change; land it deliberately rather
than as a side effect.

### Query sanitization — do not skip this

Raw user input hits FTS5's `MATCH` grammar and raises
`sqlite3.OperationalError` on ordinary strings like `C++`, `foo"bar`, `AND`, or
a bare `*`:

```python
import re
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

def build_match_query(q: str, prefix: bool = True) -> str | None:
    """Convert free text into a safe FTS5 MATCH expression (implicit AND)."""
    tokens = _TOKEN_RE.findall(q)[:16]          # cap to bound query cost
    if not tokens:
        return None                              # caller returns empty results
    parts = [f'"{t}"' for t in tokens]
    if prefix:
        parts[-1] = f'"{tokens[-1]}"*'           # type-ahead on final token
    return " ".join(parts)
```

### Public functions

| Function | Purpose |
|---|---|
| `configure(db_path)` | Called from `_init_infrastructure`, alongside `cache.configure` |
| `index_resource(plugin, descriptor, namespace, url)` | Delete-then-insert all docs for one resource, in a single transaction |
| `reindex_all(resources, config, force=False)` | Skip resources whose `(mtime, size)` match `search_index_state` |
| `drop_resource(source_path, sub_namespace)` | Remove stale docs |
| `query(match_expr, limit, offset, types=None)` | Returns candidate rows with `snippet()` + `-bm25()` |

The query, with title weighted 10x:

```sql
SELECT title, namespace, resource_type, doc_ref, url,
       snippet(search_docs, 1, '<mark>', '</mark>', '…', 24) AS snippet,
       -bm25(search_docs, 10.0, 1.0) AS score
FROM search_docs
WHERE search_docs MATCH ? {and_type_filter}
ORDER BY score DESC LIMIT ?
```

`DELETE FROM search_docs WHERE source_path = ?` is a full table scan (UNINDEXED
columns aren't queryable via MATCH). Fine at this scale; if the docroot grows
past ~10^5 docs, switch to an external-content table keyed on a rowid map.

---

## Phase 2 — Plugin hook

### `adapt/plugins/base.py`

Add a dataclass and a default-empty method next to `read`/`write`/`schema`:

```python
@dataclass
class SearchDocument:
    title: str
    body: str
    doc_ref: str | None = None   # row id, heading anchor
    url_suffix: str = ""         # appended to the resource's base URL

class Plugin(ABC):
    def index(self, resource: ResourceDescriptor) -> Iterable[SearchDocument]:
        """Yield documents for the search index. Default: not indexable."""
        return []
```

Non-abstract, so no existing plugin breaks. `PythonHandlerPlugin` inherits the
empty default — arbitrary user routers can't be indexed generically.

### Per-plugin implementations

- **`DatasetPlugin`** (`adapt/plugins/dataset_plugin.py`) — covers CSV, Excel,
  and Parquet in one place. Reuse `_read_raw_rows` + `metadata["header"]`. One
  doc per row: `title` = first non-empty cell, `body` = all cells joined,
  `doc_ref` = the same 1-based `_row_id` that `read()` assigns at
  `dataset_plugin.py:115`, `url_suffix` = `""`. Critically, **bypass
  `filter_for_user`** here — the index is user-agnostic; RLS is applied when the
  hit is followed. Flag this in the docstring, because a plugin author
  overriding `filter_for_user` for RLS will reasonably expect search to honor
  it. If you want index-time RLS, that's a separate design.
- **`MarkdownPlugin`** — index the **raw** `.md` source, not
  `markdown.markdown()` output. Split on `^#{1,6} ` headings into one doc per
  section with a slug `doc_ref`, so hits deep-link.
- **`HtmlPlugin`** — strip tags with `html.parser` (stdlib) before indexing;
  `.txt` files index as-is.
- **`MediaPlugin`** — one doc from `path.name` + the mutagen
  `title`/`artist`/`album`/`genre` already extracted at `media_plugin.py:71`.
  Cheap, and it makes the training-video library findable today; transcripts
  slot in later as a richer `index()`.

### Invalidation

`DatasetPlugin.write()` already calls `invalidate_cache(str(resource.path))` via
`_write_rows`. Add a `search.index_resource(...)` call in
`DatasetPlugin.write()` (one site, covers all three dataset plugins) —
`PluginContext.root` is in scope there, so the namespace is computable.

---

## Phase 3 — Endpoint

### Permission set, computed once

Add to `adapt/permissions.py`:

```python
def readable_resources(self, user: User) -> set[str]:
    """All resource namespaces this user may read. One query."""
    if getattr(user, "is_superuser", False):
        return set()   # sentinel: caller treats superuser as unrestricted
    return {p.resource for p in self.get_user_permissions(user)
            if p.action.value == "read"}
```

This replaces the per-namespace loop in `adapt/app.py:104`, which issues one
query *per resource*. Worth reusing there too, but keep that refactor separate.

### Route

New `adapt/routes_search.py`, mounted in `create_app` before `generate_routes`:

```python
@router.get("/search", tags=["search"])
def search(request: Request, q: str, limit: int = 20, offset: int = 0,
           type: str | None = None, user: User = Depends(require_auth)):
```

Behavior:

1. `build_match_query(q)` → if `None`, return empty results.
2. Fetch `min(limit * 5 + offset, 500)` candidates from `search.query()`.
3. Compute the readable set once; keep hits whose `namespace` is in it (or all,
   for superusers).
4. Truncate to `limit`; return
   `{"query": q, "count": len(results), "has_more": bool, "results": [...]}`.

Each result carries `resource`, `type`, `title`, `snippet`, `score`, `ui_url`,
and for dataset hits `api_url` = `/api/{ns}?filter={"_row_id": N}` — that filter
shape works against `apply_filter` as written, since `_row_id` is present on
every row.

### Three security rules, non-negotiable

- **`count` must be post-filter.** Returning a pre-filter total leaks the
  existence and volume of resources the user can't read. Same reason `has_more`
  is a boolean, not a number.
- **Over-fetching is required.** If you fetch exactly `limit` and then filter, a
  user with narrow permissions gets a near-empty page while `has_more` says
  there's more. Fetch wide, filter, then truncate.
- **Unauthenticated → 401**, via `require_auth`. Matches `/ui/media`
  (`app.py:376`) and the anon-sees-nothing rule at `utils/__init__.py:73`.

### Two integration details that are easy to miss

1. **Add `/search` to `_AUTHENTICATED_OPENAPI_PATHS`** at `adapt/app.py:48`.
   `_route_is_visible` falls through to `return False` for any unrecognized
   path, so without this the endpoint is invisible in `/openapi.json` — and
   invisible to exactly the agents this is built for.

   **Necessary but possibly not sufficient — check the FastAPI version first.**
   `pyproject.toml` sets no FastAPI bound. As of 0.140.0, `include_router` no
   longer flattens routes into `app.routes`; they appear as a single
   `_IncludedRouter` wrapper. `_build_openapi_schema` (`adapt/app.py:167`)
   filters `isinstance(route, APIRoute)` over the top level only, so on that
   version every auth, admin, and resource route drops out of the document and
   `/openapi.json` advertises just `/` and `/health`. Serving is unaffected —
   the endpoints all respond normally — but introspection is empty.

   Verify before building Phase 3:

   ```bash
   python -c "import tempfile; from pathlib import Path; from fastapi.testclient import TestClient; from adapt.app import create_app; from adapt.config import AdaptConfig; print(sorted(TestClient(create_app(AdaptConfig(root=Path(tempfile.mkdtemp())))).get('/openapi.json').json()['paths']))"
   ```

   If that prints `['/', '/health']`, the filter needs to walk routes
   recursively (descend into anything exposing a `.routes` attribute) before
   `/search` registration means anything. That fix belongs in its own change
   with its own tests — it touches a permission filter, not search. On older
   FastAPI the document is built correctly and only the one-line registration
   is needed.
2. **`/search` is now a reserved name.** A `search.md` or `search.html` in the
   docroot mounts at `/search` (`utils/__init__.py:23`) and collides. Add a
   reserved-namespace warning to `adapt check` (`adapt/commands/check.py`).

---

## Phase 4 — UI and CLI

- **Navbar search box** in `adapt/templates/base.html` and `admin_base.html` — a
  `GET` form to `/search`, so no CSRF token needed. Add it inside the existing
  `.navbar-collapse` div.
- **Results page**: have `/search` content-negotiate on `Accept: text/html`
  exactly as `/` does at `app.py:424`, rendering a new `search_results.html`
  that extends `base.html`. One route, two representations, consistent with the
  existing convention.
- **`adapt reindex <root> [--force]`** — new subparser in `adapt/cli.py:89` +
  `adapt/commands/reindex.py`. Necessary because `discover_resources` is also
  called by `list_resources` and `check`, where indexing must *not* happen; put
  the `reindex_all` call only in `_init_infrastructure` (`app.py:214`) and in
  this command.
- **Startup cost**: incremental by `(mtime, size)`, so restarts are nearly free.
  Add a `search_on_startup: bool = True` config field (with validation in
  `_validate_config`, which rejects unknown keys at `config.py:164`) for large
  docroots.

---

## Tests (`tests/test_search.py`)

The existing `tmp_path`-based fixtures in `tests/conftest.py` work as-is; write
CSV/MD fixtures into `tmp_path` before `create_app`.

Items 1, 2, 5 and 7 are written and passing. Items 3, 4 and 6 need the Phase 3
endpoint and are still outstanding — item 3 in particular must not be skipped.

1. `build_match_query` survives `C++`, `foo"bar`, `AND`, `*`, `""`, and CJK
   input without raising.
2. Superuser search finds a known CSV row and a known markdown heading.
3. **The leak test**: a normal user with read on `a.csv` but not `b.csv`
   searches for a term present in *both* — assert zero hits from `b`, and that
   `count` reflects only `a`'s hits.
4. Anonymous `GET /search?q=x` → 401.
5. Reindex is incremental: second `reindex_all` with no file changes inserts
   nothing; after a `write()`, the changed row is findable and the old value is
   not.
6. `/search` appears in `/openapi.json` for an authenticated user, absent for
   anonymous.
7. Excel sub-namespace hits carry `namespace == "workbook/Sheet1"`, not
   `"workbook"`.

---

## Sequencing

Phase 3 is about a day including the security tests; Phase 4 is half a day.
Ship Phase 1+2+3 as `0.3.0` — that's the point at which an agent can do
retrieval. The navbar box can follow.

Do the one-line `Optional` fix from `adapt/utils/query.py:87` as a `0.2.4` patch
first, independently — it's unrelated and currently breaks installs on
3.11–3.13.

### Status

**Phases 1–2 are implemented** (`adapt/search.py`, `Plugin.index()` and the four
plugin implementations, `tests/test_search.py` with 29 passing tests). Two
things changed relative to the original draft:

- The `search_index_state` primary key is composite; see the schema note above.
- `MarkdownPlugin.read()` now renders with the `toc` extension so headings carry
  `id` attributes for deep links. This alters rendered HTML, and one assertion
  in `tests/test_markdown_plugin.py` was updated to match.

**Phases 3–4 are not started.** Phase 3 should begin by running the FastAPI
version check described above.

---

## Follow-on work this unblocks

- **MCP server.** Once `/search` exists it becomes the one tool worth exposing,
  and MCP turns into a thin wrapper over the already permission-filtered
  OpenAPI document.
- **Live reload** (roadmap item in `docs/spec/01_overview.md:55`). Shares the
  same invalidation seam as the index, so reload gets index-refresh nearly free.
- **Video transcripts.** A richer `MediaPlugin.index()` once there's somewhere
  to put the output.
- **Raw-text retrieval.** `MarkdownPlugin.read()`
  (`adapt/plugins/markdown_plugin.py:92`) only returns rendered HTML wrapped in
  the Jinja shell. Content negotiation on `Accept: text/plain` gives clean text
  to both the indexer and any agent.
