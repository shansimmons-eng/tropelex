"""
Research Feed Intelligence — FastAPI router.

Mount into the main app:
    from core.tropebook.feed_intelligence_router import feed_intel_router
    app.include_router(feed_intel_router)
"""

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from core.tropebook.feed_intelligence import compute_feed_intelligence

logger = logging.getLogger("tropelex.feed_intel")

feed_intel_router = APIRouter(prefix="/api/research-feeds", tags=["feed-intelligence"])

_CORE_DIR = Path(__file__).parent.parent.parent
BASE_DIR = _CORE_DIR.parent
FEEDS_DIR = BASE_DIR / "memory" / "feeds"


def _load_feed_runs(feed_id: str) -> list[dict[str, Any]]:
    """Load run history for a feed from disk."""
    runs_file = FEEDS_DIR / f"{feed_id}_runs.json"
    if not runs_file.exists():
        raise HTTPException(status_code=404, detail=f"Feed '{feed_id}' not found")
    return json.loads(runs_file.read_text())


@feed_intel_router.get("/{feed_id}/intelligence")
async def feed_intelligence(feed_id: str) -> dict[str, Any]:
    """Return trend detection and anomaly report for a feed."""
    try:
        runs = _load_feed_runs(feed_id)
        return compute_feed_intelligence(runs)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("feed intelligence failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
