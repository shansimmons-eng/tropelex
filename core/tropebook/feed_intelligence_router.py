"""
Research Feed Intelligence — FastAPI router.

Mount into the main app:
    from core.tropebook.feed_intelligence_router import feed_intel_router
    app.include_router(feed_intel_router)

Uses ResearchFeedManager for consistent data access (same storage as
the main feed CRUD endpoints).
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from core.tropebook.feed_intelligence import compute_feed_intelligence
from core.tropebook.research_feeds import ResearchFeedManager

logger = logging.getLogger("tropelex.feed_intel")

feed_intel_router = APIRouter(prefix="/api/research-feeds", tags=["feed-intelligence"])


def _get_fm() -> ResearchFeedManager:
    """Return a shared ResearchFeedManager instance."""
    from core.tropebook.web.server import BASE_DIR
    return ResearchFeedManager(storage_path=str(BASE_DIR / "memory" / "feeds"))


@feed_intel_router.get("/{feed_id}/intelligence")
async def feed_intelligence(feed_id: str) -> dict[str, Any]:
    """Return trend detection and anomaly report for a feed.

    Builds intelligence from the feed's run history stored by
    ResearchFeedManager. Returns a 404 if the feed doesn't exist.
    """
    fm = _get_fm()
    feed = fm.get(feed_id)
    if not feed:
        raise HTTPException(status_code=404, detail=f"Feed '{feed_id}' not found")

    try:
        runs = [r.to_dict() for r in fm.get_runs(feed_id=feed_id, limit=100)]
        return compute_feed_intelligence(runs)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("feed intelligence failed for %s: %s", feed_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))
