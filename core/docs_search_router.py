"""
Documentation Search API — GET /api/docs-search, the "Documentation"
category behind the dashboard sidebar search widget (core/docs_search.py
does the actual parsing/ranking; this is the thin HTTP wrapper, same
split as core/search_router.py's search_memory/memory_search).

Not project-scoped -- the GUIDE/FAQ/Getting Started/API Reference/README
are the same regardless of which project is active, unlike
core/search_router.py's decisions/sessions/patterns search.
"""

import logging
from typing import Any

from fastapi import APIRouter, Query

from core.docs_search import DocEntry, build_docs_index, search_docs

logger = logging.getLogger("tropelex.docs_search")

docs_search_router = APIRouter(prefix="/api", tags=["docs-search"])

# Built once and cached -- site/*.html and README.md only change on a
# deploy, which restarts this process anyway. Module-level rather than
# per-request re-parsing (255 entries across ~4 pages + README, cheap to
# hold, not cheap to re-parse on every keystroke of a live search box).
_index_cache: list[DocEntry] | None = None


def _get_index() -> list[DocEntry]:
    global _index_cache
    if _index_cache is None:
        try:
            _index_cache = build_docs_index()
        except Exception as exc:
            logger.error("docs index build failed: %s", exc)
            _index_cache = []
    return _index_cache


@docs_search_router.get("/docs-search")
async def docs_search(
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(default=10, ge=1, le=50),
) -> dict[str, Any]:
    """Keyword search across the GUIDE, FAQ, Getting Started, API
    Reference, and README."""
    results = search_docs(_get_index(), q, limit=limit)
    return {"query": q, "results": results, "count": len(results)}
