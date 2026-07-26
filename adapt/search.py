"""
adapt.search
SQLite FTS5-backed full-text index over discovered resources.

The index is user-agnostic: every document a plugin yields is stored once,
regardless of who may read it. Permission filtering happens at query time in
the search route, never here. See SEARCH_PLAN.md.
"""
from __future__ import annotations

import logging
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, TYPE_CHECKING

if TYPE_CHECKING:
    from .config import AdaptConfig
    from .discovery import DatasetResource
    from .plugins.base import Plugin, ResourceDescriptor

logger = logging.getLogger(__name__)

DOCS_TABLE = "search_docs"
STATE_TABLE = "search_index_state"

_lock = threading.Lock()
_db_path: str | None = None
_available: bool = False

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
MAX_QUERY_TOKENS = 16
MAX_CANDIDATES = 500


def configure(db_path: str) -> None:
    """Configure the search index database path and create its tables.

    Args:
        db_path: SQLite file path, normally the same file the cache uses.
    """
    global _db_path
    _db_path = db_path
    init_tables()
    logger.debug("Search index configured with DB path: %s", _db_path)


def is_available() -> bool:
    """Return True if the index is configured and this SQLite build has FTS5."""
    return _available


def _get_conn() -> sqlite3.Connection:
    """Open a connection to the search index database.

    Raises:
        RuntimeError: If ``configure`` has not been called.
    """
    if _db_path is None:
        raise RuntimeError("adapt.search.configure() must be called before use")
    conn = sqlite3.connect(_db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_tables() -> None:
    """Create the FTS5 document table and index-state table if missing.

    If this SQLite build lacks FTS5, the module degrades to a no-op rather than
    taking the server down: indexing becomes a no-op and queries return nothing.
    """
    global _available
    with _lock:
        conn = _get_conn()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS {DOCS_TABLE} USING fts5(
                    title,
                    body,
                    namespace     UNINDEXED,
                    resource_type UNINDEXED,
                    doc_ref       UNINDEXED,
                    url           UNINDEXED,
                    source_path   UNINDEXED,
                    tokenize = "unicode61 remove_diacritics 2"
                )
            """)
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {STATE_TABLE} (
                    source_path   TEXT NOT NULL,
                    sub_namespace TEXT NOT NULL DEFAULT '',
                    namespace     TEXT NOT NULL,
                    mtime         REAL,
                    size          INTEGER,
                    indexed_at    TEXT,
                    PRIMARY KEY (source_path, sub_namespace)
                )
            """)
            conn.commit()
            _available = True
        except sqlite3.OperationalError as exc:
            _available = False
            logger.warning("Search index unavailable (FTS5 missing?): %s", exc)
        finally:
            conn.close()


def build_match_query(q: str, prefix: bool = True) -> str | None:
    """Convert free text into a safe FTS5 MATCH expression.

    Raw user input cannot be passed to MATCH: strings like ``C++``, ``foo"bar``,
    ``AND`` or a bare ``*`` are valid searches but invalid FTS5 syntax, and
    raise OperationalError. Tokens are extracted and re-quoted so any input is
    accepted, with an implicit AND between terms.

    Args:
        q: The raw user query.
        prefix: Whether to make the final token a prefix match (type-ahead).

    Returns:
        A MATCH expression, or None if the query has no usable tokens.
    """
    tokens = _TOKEN_RE.findall(q)[:MAX_QUERY_TOKENS]
    if not tokens:
        return None
    parts = [f'"{token}"' for token in tokens]
    if prefix:
        parts[-1] = f'"{tokens[-1]}"*'
    return " ".join(parts)


def namespace_for(resource: "DatasetResource | ResourceDescriptor", root: Path | None = None) -> str:
    """Return the no-extension permission namespace for a resource.

    This must match the form used by ``adapt admin create-permissions`` and
    ``build_accessible_ui_links``; the with-extension namespace that routes.py
    also mounts has no permissions created for it.

    Args:
        resource: A DatasetResource, or a ResourceDescriptor plus ``root``.
        root: Document root, required when passing a ResourceDescriptor.

    Returns:
        The namespace, e.g. ``hr/contacts`` or ``workbook/Sheet1``.
    """
    relative = getattr(resource, "relative_path", None)
    if relative is None:
        if root is None:
            raise ValueError("root is required when resolving a ResourceDescriptor")
        relative = resource.path.relative_to(root)
    namespace = relative.with_suffix("").as_posix()
    sub_namespace = resource.metadata.get("sub_namespace", "")
    if sub_namespace:
        namespace += f"/{sub_namespace}"
    return namespace


def resource_url(resource_type: str, namespace: str) -> str:
    """Return the browsable URL for a resource, matching build_ui_links."""
    if resource_type in ("html", "markdown"):
        return f"/{namespace}"
    return f"/ui/{namespace}"


def index_resource(plugin: "Plugin", descriptor: "ResourceDescriptor", namespace: str) -> int:
    """Replace all indexed documents for one resource namespace.

    Deletes and inserts are keyed on (source_path, namespace) rather than
    source_path alone, because one workbook yields a separate namespace per
    sheet and they must not clobber each other.

    Args:
        plugin: The plugin owning the resource.
        descriptor: The resource descriptor.
        namespace: The no-extension namespace for this resource.

    Returns:
        The number of documents indexed.
    """
    if not _available:
        return 0

    try:
        docs = list(plugin.index(descriptor))
    except Exception as exc:
        logger.warning("Indexing failed for %s (%s): %s", descriptor.path, namespace, exc)
        return 0

    source_path = str(descriptor.path)
    sub_namespace = descriptor.metadata.get("sub_namespace", "")
    base_url = resource_url(descriptor.resource_type, namespace)

    rows = [
        (
            doc.title or namespace,
            doc.body or "",
            namespace,
            descriptor.resource_type,
            doc.doc_ref,
            base_url + (doc.url_suffix or ""),
            source_path,
        )
        for doc in docs
    ]

    try:
        stat = descriptor.path.stat()
    except OSError as exc:
        logger.warning("Cannot stat %s: %s", descriptor.path, exc)
        return 0

    with _lock:
        conn = _get_conn()
        try:
            conn.execute(
                f"DELETE FROM {DOCS_TABLE} WHERE source_path = ? AND namespace = ?",
                (source_path, namespace),
            )
            if rows:
                conn.executemany(
                    f"""INSERT INTO {DOCS_TABLE}
                        (title, body, namespace, resource_type, doc_ref, url, source_path)
                        VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    rows,
                )
            conn.execute(
                f"""INSERT OR REPLACE INTO {STATE_TABLE}
                    (source_path, sub_namespace, namespace, mtime, size, indexed_at)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    source_path,
                    sub_namespace,
                    namespace,
                    stat.st_mtime,
                    stat.st_size,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    logger.debug("Indexed %d documents for %s", len(rows), namespace)
    return len(rows)


def drop_resource(source_path: str, namespace: str | None = None) -> None:
    """Remove indexed documents for a source file, or one namespace within it."""
    if not _available:
        return
    with _lock:
        conn = _get_conn()
        try:
            if namespace:
                conn.execute(
                    f"DELETE FROM {DOCS_TABLE} WHERE source_path = ? AND namespace = ?",
                    (source_path, namespace),
                )
                conn.execute(
                    f"DELETE FROM {STATE_TABLE} WHERE source_path = ? AND namespace = ?",
                    (source_path, namespace),
                )
            else:
                conn.execute(f"DELETE FROM {DOCS_TABLE} WHERE source_path = ?", (source_path,))
                conn.execute(f"DELETE FROM {STATE_TABLE} WHERE source_path = ?", (source_path,))
            conn.commit()
        finally:
            conn.close()
    logger.debug("Dropped index entries for %s (%s)", source_path, namespace or "all namespaces")


def _indexed_state() -> dict[tuple[str, str], tuple[float, int]]:
    """Return {(source_path, namespace): (mtime, size)} for everything indexed."""
    with _lock:
        conn = _get_conn()
        try:
            rows = conn.execute(
                f"SELECT source_path, namespace, mtime, size FROM {STATE_TABLE}"
            ).fetchall()
        finally:
            conn.close()
    return {(r["source_path"], r["namespace"]): (r["mtime"], r["size"]) for r in rows}


def reindex_all(resources: list["DatasetResource"], config: "AdaptConfig", force: bool = False) -> dict[str, int]:
    """Bring the index in line with the discovered resources.

    Incremental by (mtime, size): unchanged files are skipped, so restarts are
    cheap. Resources that have disappeared from the docroot are pruned.

    Args:
        resources: Discovered resources, from ``discover_resources``.
        config: The application config, used to resolve plugin factories.
        force: Reindex even when mtime and size are unchanged.

    Returns:
        Counts keyed ``indexed``, ``skipped``, ``pruned``, ``documents``.
    """
    from .plugins.base import ResourceDescriptor

    if not _available:
        logger.info("Search index unavailable; skipping reindex")
        return {"indexed": 0, "skipped": 0, "pruned": 0, "documents": 0}

    previous = _indexed_state()
    seen: set[tuple[str, str]] = set()
    indexed = skipped = documents = 0

    for resource in resources:
        namespace = namespace_for(resource)
        key = (str(resource.path), namespace)
        seen.add(key)

        try:
            stat = resource.path.stat()
        except OSError:
            continue

        if not force and previous.get(key) == (stat.st_mtime, stat.st_size):
            skipped += 1
            continue

        plugin = config.get_plugin_factory(resource.path.suffix)()
        descriptor = ResourceDescriptor(
            path=resource.path,
            resource_type=resource.resource_type,
            schema_path=resource.schema_path,
            ui_path=resource.ui_path,
            metadata=resource.metadata,
        )
        documents += index_resource(plugin, descriptor, namespace)
        indexed += 1

    pruned = 0
    for source_path, namespace in previous.keys() - seen:
        drop_resource(source_path, namespace)
        pruned += 1

    logger.info(
        "Reindex complete: %d indexed (%d docs), %d skipped, %d pruned",
        indexed, documents, skipped, pruned,
    )
    return {"indexed": indexed, "skipped": skipped, "pruned": pruned, "documents": documents}


def query(
    match_expr: str,
    limit: int = 100,
    types: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Run a MATCH query and return scored candidate hits.

    Results are NOT permission-filtered. Callers must filter by namespace
    against the requesting user's readable set before returning anything.

    Args:
        match_expr: A sanitized expression from ``build_match_query``.
        limit: Maximum candidate rows to fetch, capped at MAX_CANDIDATES.
        types: Optional resource_type whitelist.

    Returns:
        Hit dicts ordered by descending score.
    """
    if not _available:
        return []

    sql = f"""
        SELECT title, namespace, resource_type, doc_ref, url,
               snippet({DOCS_TABLE}, 1, '<mark>', '</mark>', '…', 24) AS snippet,
               -bm25({DOCS_TABLE}, 10.0, 1.0) AS score
        FROM {DOCS_TABLE}
        WHERE {DOCS_TABLE} MATCH ?
    """
    params: list[Any] = [match_expr]

    type_list = [t for t in (types or []) if t]
    if type_list:
        placeholders = ",".join("?" for _ in type_list)
        sql += f" AND resource_type IN ({placeholders})"
        params.extend(type_list)

    sql += " ORDER BY score DESC LIMIT ?"
    params.append(min(limit, MAX_CANDIDATES))

    with _lock:
        conn = _get_conn()
        try:
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError as exc:
            # Should be unreachable via build_match_query, but never 500 on search.
            logger.warning("Search query failed for %r: %s", match_expr, exc)
            return []
        finally:
            conn.close()

    return [dict(row) for row in rows]
