"""
Memory Analytics API — usage patterns, growth trends, quality metrics.

Mount into the main app:
    from core.analytics_router import analytics_router
    app.include_router(analytics_router)
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from core.analytics import compute_analytics
from core.memory.manager import MemoryManager

logger = logging.getLogger("tropelex.analytics")

analytics_router = APIRouter(prefix="/api/memory", tags=["analytics"])

_mm = MemoryManager()


def _load_memory(project: str) -> dict[str, Any]:
    if project not in _mm.list_projects():
        raise HTTPException(status_code=404, detail=f"Project '{project}' not found")
    return _mm.get_project_memory(project)


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
