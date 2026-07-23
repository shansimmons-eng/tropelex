"""
Decision Impact Analysis — FastAPI router.

Mount into the main app:
    from core.impact.router import impact_router
    app.include_router(impact_router)
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from core.impact.analysis import compute_impact_analysis
from core.memory.manager import MemoryManager

logger = logging.getLogger("tropelex.impact")

impact_router = APIRouter(prefix="/api/memory", tags=["impact"])

_mm = MemoryManager()


def _load_memory(project: str) -> dict[str, Any]:
    """Load a project's memory, or raise 404."""
    if project not in _mm.list_projects():
        raise HTTPException(status_code=404, detail=f"Project '{project}' not found")
    return _mm.get_project_memory(project)


@impact_router.get("/{project}/impact")
async def project_impact(project: str) -> dict[str, Any]:
    """Return decision impact analysis for a project."""
    try:
        memory = _load_memory(project)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("impact load failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
    return compute_impact_analysis(memory)
