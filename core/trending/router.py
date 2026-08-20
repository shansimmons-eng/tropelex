"""
Trending — FastAPI router.

Mount into the main app:
    from core.trending.router import router as trending_router
    app.include_router(trending_router)
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from core.reposeek.github_client import search_github
from core.reposeek.models import SeekQuery
from core.reposeek.router import _extract_search_terms
from core.reposeek.scoring import score_results
from core.result import Err
from core.trending.github_client import search_trending
from core.trending.storage import TrendingStore, snapshot_key

logger = logging.getLogger("trending.router")

router = APIRouter(prefix="/api/trending", tags=["trending"])

_MAX_SCAN_RESULTS = 25
_MAX_RELATED_RESULTS = 10


class ExcludeRequest(BaseModel):
    url: str
    title: str = ""


class RelatedRequest(BaseModel):
    title: str
    url: str = ""
    description: str = ""
    language: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_topics(raw: str) -> list[str]:
    return [t.strip() for t in raw.split(",") if t.strip()]


@router.get("/scan")
async def scan(
    language: str | None = Query(None, description="Restrict to this language"),
    topics: str = Query("", description="Comma-separated GitHub topic tags"),
    window: str = Query("week", pattern="^(today|week|month)$"),
):
    """Pull a trending-proxy snapshot (recently-pushed repos sorted by
    stars) and diff it against the most recent stored snapshot for this
    exact (language, topics, window) combination.

    A repo's delta_stars/first_seen is None/None when this is the first
    scan ever run for this filter combo -- there's no baseline yet, and
    that's reported honestly rather than shown as a zero delta.
    """
    topics_list = _parse_topics(topics)

    result = await search_trending(language, topics_list, window, limit=_MAX_SCAN_RESULTS)
    if isinstance(result, Err):
        if result.code == "RATE_LIMITED":
            raise HTTPException(
                status_code=503,
                detail="GitHub API rate limit exceeded",
                headers={"Retry-After": "60"},
            )
        raise HTTPException(status_code=500, detail=result.error)

    store = TrendingStore()
    excluded = store.excluded_urls()
    filtered = [r for r in result.value if r.url not in excluded][:_MAX_SCAN_RESULTS]

    key = snapshot_key(language, topics_list, window)
    previous = store.last_snapshot(key)
    previous_stars = {r["url"]: r["stars"] for r in previous["repos"]} if previous else {}

    repos = []
    for r in filtered:
        entry = r.to_dict()
        if previous is None:
            entry["delta_stars"] = None
            entry["first_seen"] = None
        elif r.url in previous_stars:
            entry["delta_stars"] = r.stars - previous_stars[r.url]
            entry["first_seen"] = False
        else:
            entry["delta_stars"] = None
            entry["first_seen"] = True
        repos.append(entry)

    snapshot = {
        "id": store.new_snapshot_id(),
        "created_at": _now_iso(),
        "repos": [r.to_dict() for r in filtered],
    }
    store.add_snapshot(key, snapshot)

    return {
        "snapshot_id": snapshot["id"],
        "window": window,
        "language": language,
        "topics": topics_list,
        "previous_snapshot_at": previous["created_at"] if previous else None,
        "repos": repos,
    }


@router.post("/related")
async def related(body: RelatedRequest):
    """One-shot 'show similar' lookup for a single trending result --
    profiles it the same way RepoSeek profiles an item, searches, scores,
    but persists nothing and doesn't turn into a new snapshot/batch."""
    profile = {
        "tech_stack": [body.language] if body.language else [],
        "description": body.description or "",
        "patterns": [],
    }
    search_terms = _extract_search_terms(profile["description"])
    query_text = search_terms or (body.language or body.title)

    query = SeekQuery(query=query_text, language=body.language, topics=profile["tech_stack"])
    result = await search_github(query)
    if isinstance(result, Err):
        if result.code == "RATE_LIMITED":
            raise HTTPException(
                status_code=503,
                detail="GitHub API rate limit exceeded",
                headers={"Retry-After": "60"},
            )
        raise HTTPException(status_code=500, detail=result.error)

    scored = score_results(result.value, profile)

    store = TrendingStore()
    excluded = store.excluded_urls()
    filtered = [r for r in scored if r.url not in excluded and r.url != body.url][:_MAX_RELATED_RESULTS]

    return {"repos": [r.to_dict() for r in filtered]}


@router.post("/exclude")
async def add_exclude(body: ExcludeRequest):
    """Permanently exclude a repo from future trending scans."""
    store = TrendingStore()
    store.exclude_add(body.url, body.title)
    items = store.exclude_list()
    return {"excluded_count": len(items)}


@router.delete("/exclude")
async def remove_exclude(url: str = Query(..., description="URL to remove from the exclude list")):
    """Undo an exclude -- the repo can appear in scans again."""
    store = TrendingStore()
    if not store.exclude_remove(url):
        raise HTTPException(status_code=404, detail=f"'{url}' was not on the exclude list")
    items = store.exclude_list()
    return {"excluded_count": len(items)}


@router.get("/exclude")
async def list_exclude():
    """The current global trending exclude list."""
    store = TrendingStore()
    items = store.exclude_list()
    return {"excluded": items, "count": len(items)}


@router.get("/history")
async def history(
    language: str | None = Query(None),
    topics: str = Query(""),
    window: str = Query("week", pattern="^(today|week|month)$"),
):
    """Past snapshot dates + result counts for this filter combination --
    full repo lists aren't included here, fetch a /scan to get those."""
    topics_list = _parse_topics(topics)
    key = snapshot_key(language, topics_list, window)
    store = TrendingStore()
    snapshots = store.list_snapshots(key)
    summary = [
        {
            "id": s.get("id"),
            "created_at": s.get("created_at"),
            "result_count": len(s.get("repos", [])),
        }
        for s in snapshots
    ]
    return {"window": window, "language": language, "topics": topics_list, "history": summary, "count": len(summary)}
