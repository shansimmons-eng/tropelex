"""
Memory Health Dashboard — FastAPI router.

Mount into the main app:
    from core.health.router import health_router
    app.include_router(health_router)
"""

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from core.health.dashboard import aggregate_health_metrics

logger = logging.getLogger("tropelex.health")

health_router = APIRouter(prefix="/api/memory", tags=["health"])

_CORE_DIR = Path(__file__).parent.parent
BASE_DIR = _CORE_DIR.parent


def _load_memory(project: str) -> dict[str, Any]:
    """Load a project's memory JSON, or raise 404."""
    path = BASE_DIR / "memory" / f"{project}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Project '{project}' not found")
    import json
    return json.loads(path.read_text())


@health_router.get("/{project}/health")
async def project_health(project: str) -> dict[str, Any]:
    """Return health metrics for a project."""
    try:
        memory = _load_memory(project)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("health load failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
    return aggregate_health_metrics(memory)
