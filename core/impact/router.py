"""
Decision Impact Analysis — FastAPI router.

Mount into the main app:
    from core.impact.router import impact_router
    app.include_router(impact_router)
"""

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from core.impact.analysis import compute_impact_analysis

logger = logging.getLogger("tropelex.impact")

impact_router = APIRouter(prefix="/api/memory", tags=["impact"])

_CORE_DIR = Path(__file__).parent.parent
BASE_DIR = _CORE_DIR.parent


def _load_memory(project: str) -> dict[str, Any]:
    """Load a project's memory JSON, or raise 404."""
    path = BASE_DIR / "memory" / f"{project}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Project '{project}' not found")
    return json.loads(path.read_text())


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
