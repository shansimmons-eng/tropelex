"""
Ghost Decisions — FastAPI router.

Mount into the main app:
    from core.ghost.router import ghost_router
    app.include_router(ghost_router)
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from core.ghost.detector import GhostReport, detect_ghost_decisions
from core.decision_tree import DecisionTree
from core.memory.manager import MemoryManager

logger = logging.getLogger("tropelex.ghost")

ghost_router = APIRouter(prefix="/api/memory", tags=["ghost"])

_mm = MemoryManager()


def _load_memory(project: str) -> dict[str, Any]:
    """Load a project's memory, or raise 404."""
    if project not in _mm.list_projects():
        raise HTTPException(status_code=404, detail=f"Project '{project}' not found")
    return _mm.get_project_memory(project)


@ghost_router.get("/{project}/ghost-decisions")
async def project_ghost_decisions(project: str) -> dict[str, Any]:
    """Detect ghost decisions — code that contradicts documented decisions.

    This endpoint analyzes the project's decision corpus against recent
    git diffs to find silent drift between documentation and implementation.
    """
    try:
        memory = _load_memory(project)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("ghost-decisions load failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    # Build decision tree from memory
    decisions = memory.get("decisions", [])
    tree = DecisionTree.from_decisions(decisions) if decisions else DecisionTree()

    # For now, use an empty diff_data list — the endpoint is ready
    # for when git diff integration is wired in
    diff_data: list[dict[str, str]] = []

    report: GhostReport = detect_ghost_decisions(memory, diff_data, tree)

    return {
        "ghosts": [
            {
                "decision_id": g.decision_id,
                "decision_text": g.decision_text,
                "severity": g.severity,
                "evidence_count": len(g.evidence),
                "confidence_score": g.confidence_score,
                "confidence_tier": g.confidence_tier,
                "recommendation": g.recommendation,
            }
            for g in report.ghosts
        ],
        "total_decisions_checked": report.total_decisions_checked,
        "total_diffs_checked": report.total_diffs_checked,
        "total_ghosts": report.total_ghosts,
        "severity_distribution": report.severity_distribution,
        "recommendations": report.recommendations,
    }
