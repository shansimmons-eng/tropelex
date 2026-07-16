"""
Cross-Project Learning Automation — FastAPI router.

Mount into the main app:
    from core.rag_router import rag_router
    app.include_router(rag_router)
"""

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from core.rag import auto_detect_similar_projects, generate_auto_suggestions

logger = logging.getLogger("tropelex.rag_router")

rag_router = APIRouter(prefix="/api/memory", tags=["rag-automation"])

_CORE_DIR = Path(__file__).parent.parent
BASE_DIR = _CORE_DIR.parent


def _get_memory_manager():
    """Lazy-init MemoryManager."""
    from core.memory.manager import MemoryManager
    return MemoryManager(str(BASE_DIR))


@rag_router.get("/{project}/auto-suggestions")
async def auto_suggestions(
    project: str,
    limit: int = Query(default=5, ge=1, le=20),
) -> dict[str, Any]:
    """Auto-generated cross-project suggestions without a query."""
    try:
        mm = _get_memory_manager()
        suggestions = generate_auto_suggestions(mm, project, limit=limit)
        similar = auto_detect_similar_projects(mm, project)
        return {
            "project": project,
            "similar_projects": similar,
            "suggestions": suggestions,
            "count": len(suggestions),
        }
    except Exception as exc:
        logger.error("auto-suggestions failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
