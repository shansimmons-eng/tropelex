"""
Contradiction Detection — FastAPI router.

Mount into the main app:
    from core.contradictions.router import contradiction_router
    app.include_router(contradiction_router)
"""

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from core.contradictions import ContradictionError
from core.contradictions.detector import detect_contradictions

logger = logging.getLogger("tropelex.contradictions")

contradiction_router = APIRouter(prefix="/api/memory", tags=["contradictions"])

_CORE_DIR = Path(__file__).parent.parent
BASE_DIR = _CORE_DIR.parent


def _load_memory(project: str) -> dict[str, Any]:
    """Load a project's memory JSON, or raise 404."""
    path = BASE_DIR / "memory" / f"{project}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Project '{project}' not found")
    return json.loads(path.read_text())


@contradiction_router.get("/{project}/contradictions")
async def project_contradictions(project: str) -> dict[str, Any]:
    """Scan a project's decisions for contradictions.

    Returns a list of contradictions with type, severity, and resolution
    suggestions. Integrates with the Health Dashboard via the summary stats.
    """
    try:
        memory = _load_memory(project)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("contradictions load failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    decisions = memory.get("decisions", [])

    try:
        report = detect_contradictions(decisions)
    except ContradictionError as exc:
        logger.error("contradiction detection failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "contradictions": [
            {
                "id": c.id,
                "decision_a_id": c.decision_a_id,
                "decision_a_text": c.decision_a_text,
                "decision_b_id": c.decision_b_id,
                "decision_b_text": c.decision_b_text,
                "contradiction_type": c.contradiction_type,
                "severity": c.severity,
                "similarity_score": c.similarity_score,
                "resolution_suggestion": c.resolution_suggestion,
            }
            for c in report.contradictions
        ],
        "total_checked": report.total_checked,
        "unresolved_count": report.unresolved_count,
        # Health Dashboard integration hook
        "severity_distribution": {
            "high": sum(1 for c in report.contradictions if c.severity == "high"),
            "medium": sum(1 for c in report.contradictions if c.severity == "medium"),
            "low": sum(1 for c in report.contradictions if c.severity == "low"),
        },
    }
