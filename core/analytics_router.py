"""
Memory Analytics API — usage patterns, growth trends, quality metrics.

Mount into the main app:
    from core.analytics_router import analytics_router
    app.include_router(analytics_router)
"""

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from core.analytics import compute_analytics

logger = logging.getLogger("tropelex.analytics")

analytics_router = APIRouter(prefix="/api/memory", tags=["analytics"])

_CORE_DIR = Path(__file__).parent.parent
BASE_DIR = _CORE_DIR.parent


def _load_memory(project: str) -> dict[str, Any]:
    path = BASE_DIR / "memory" / f"{project}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Project '{project}' not found")
    return json.loads(path.read_text())


@analytics_router.get("/{project}/analytics")
async def project_analytics(project: str) -> dict[str, Any]:
    """Return usage, growth, and quality analytics for a project."""
    try:
        memory = _load_memory(project)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("analytics load failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
    return compute_analytics(memory)
