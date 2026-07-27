"""adapt.routes_search — Permission-filtered full-text search across all resources."""
from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request
from markupsafe import Markup, escape
from sqlmodel import Session

from . import search as search_index
from .auth.dependencies import require_auth
from .permissions import PermissionChecker
from .storage import User
from .utils import build_accessible_ui_links

logger = logging.getLogger(__name__)

router = APIRouter()

_MARK_OPEN = "<mark>"
_MARK_CLOSE = "</mark>"

# Resource types whose hits address an individual row, and so can carry a
# deep-linked API URL back to that row.
DATASET_TYPES = frozenset({"csv", "excel", "parquet"})

# Hits are filtered by permission *after* the index returns them, so the index
# must be over-fetched: asking for exactly `limit` would hand a user with narrow
# permissions a near-empty page while claiming more results exist.
CANDIDATE_MULTIPLIER = 5


def safe_snippet(snippet: str) -> Markup:
    """Escape a snippet for HTML, restoring only its highlight tags.

    Snippets are raw text from the docroot with `<mark>` pairs inserted by
    SQLite; a spreadsheet cell or Markdown file could just as easily contain
    `<script>`. Everything is escaped first, then only the highlight pair is
    re-enabled, so untrusted content can at worst produce a stray highlight —
    never executable markup.
    """
    escaped = str(escape(snippet))
    escaped = escaped.replace(str(escape(_MARK_OPEN)), _MARK_OPEN)
    escaped = escaped.replace(str(escape(_MARK_CLOSE)), _MARK_CLOSE)
    return Markup(escaped)


def _row_api_url(namespace: str, doc_ref: str) -> str | None:
    """Build an API URL addressing a single dataset row, or None if not a row."""
    try:
        row_id = int(doc_ref)
    except (TypeError, ValueError):
        return None
    filter_json = json.dumps({"_row_id": row_id}, separators=(",", ":"))
    return f"/api/{namespace}/?filter={quote(filter_json)}"


def _to_result(hit: dict[str, Any]) -> dict[str, Any]:
    """Shape one index hit into the public result form."""
    result: dict[str, Any] = {
        "resource": hit["namespace"],
        "type": hit["resource_type"],
        "title": hit["title"],
        "snippet": hit["snippet"],
        "score": round(hit["score"], 4),
        "ui_url": hit["url"],
    }
    if hit["resource_type"] in DATASET_TYPES and hit["doc_ref"]:
        api_url = _row_api_url(hit["namespace"], hit["doc_ref"])
        if api_url:
            result["api_url"] = api_url
            result["row_id"] = int(hit["doc_ref"])
    return result


@router.get("/search", tags=["search"])
def search_resources(
    request: Request,
    # Optional so the navbar's empty submission and a bare /search both render
    # the search page rather than a 422.
    q: str = Query("", description="Free-text query; any input is accepted."),
    limit: int = Query(20, ge=1, le=100, description="Results per page."),
    offset: int = Query(0, ge=0, description="Results to skip."),
    resource_type: str | None = Query(
        None,
        alias="type",
        description="Comma-separated resource types to restrict to, e.g. 'csv,markdown'.",
    ),
    user: User = Depends(require_auth),
) -> dict[str, Any]:
    """Search across every resource the current user is permitted to read.

    Results span datasets, documents and media in one ranked list, each with a
    snippet and a URL to follow. Only resources the caller has read permission
    on are returned, and `count` reflects the filtered page only — reporting a
    pre-filter total would leak the existence and volume of resources the caller
    cannot see.

    Returns JSON, or an HTML results page when the client asks for `text/html`.
    """
    payload = _run_search(request, q, limit, offset, resource_type, user)

    if "text/html" in request.headers.get("accept", ""):
        context = {
            "query": q,
            "results": payload["results"],
            "count": payload["count"],
            "has_more": payload["has_more"],
            "limit": limit,
            "offset": offset,
            "user": user,
            "ui_links": build_accessible_ui_links(request, user),
            "is_superuser": getattr(user, "is_superuser", False),
        }
        return request.app.state.templates.TemplateResponse(
            request, "search_results.html", context
        )

    return payload


def _run_search(
    request: Request,
    q: str,
    limit: int,
    offset: int,
    resource_type: str | None,
    user: User,
) -> dict[str, Any]:
    """Execute the query and filter hits down to what `user` may read."""
    empty = {"query": q, "count": 0, "has_more": False, "results": []}

    match_expr = search_index.build_match_query(q)
    if match_expr is None:
        logger.debug("Search query %r has no usable tokens", q)
        return empty

    types = None
    if resource_type:
        types = [part.strip() for part in resource_type.split(",") if part.strip()]

    candidates = search_index.query(
        match_expr,
        limit=(offset + limit) * CANDIDATE_MULTIPLIER,
        types=types,
    )
    if not candidates:
        return empty

    with Session(request.app.state.db_engine) as db:
        readable = PermissionChecker(db).readable_resources(user)

    permitted = [
        hit for hit in candidates
        if readable is None or hit["namespace"] in readable
    ]

    page = permitted[offset:offset + limit]
    logger.debug(
        "Search %r by %s: %d candidates, %d permitted, %d returned",
        q, user.username, len(candidates), len(permitted), len(page),
    )

    return {
        "query": q,
        "count": len(page),
        # May under-report when the candidate cap is hit; never over-reports.
        "has_more": len(permitted) > offset + limit,
        "results": [_to_result(hit) for hit in page],
    }
