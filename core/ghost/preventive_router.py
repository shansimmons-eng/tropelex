"""
Preventive Ghost Checks — FastAPI router.

Pre-write guardrail: checks a proposed diff against active decisions
before code is written, surfacing warnings as a guardrail.

Mount into the main app:
    from core.ghost.preventive_router import preventive_router
    app.include_router(preventive_router)
"""

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.ghost.preventive import check_diff_for_warnings

logger = logging.getLogger("tropelex.ghost.preventive")

preventive_router = APIRouter(prefix="/api/memory", tags=["ghost-preventive"])

_CORE_DIR = Path(__file__).parent.parent
_BASE_DIR = _CORE_DIR.parent


def _load_memory(project: str) -> dict[str, Any]:
    """Load a project's memory JSON, or raise 404."""
    path = _BASE_DIR / "memory" / f"{project}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Project '{project}' not found")
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        logger.error("Corrupt memory for %s: %s", project, exc)
        raise HTTPException(status_code=500, detail="Corrupt memory file")


class GhostCheckRequest(BaseModel):
    """Request body for pre-write ghost diff checking."""
    diff: str = Field(..., min_length=1, max_length=100000,
                      description="Unified diff text to check against decisions")


@preventive_router.post("/{project}/ghost-check")
async def ghost_check(project: str, body: GhostCheckRequest) -> dict[str, Any]:
    """Check a proposed diff against active decisions before writing.

    Returns warnings for any decisions that may be contradicted by the diff.
    This is a pre-write hook — call before finalizing a diff.
    """
    try:
        memory = _load_memory(project)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("ghost-check load failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    result = check_diff_for_warnings(memory, body.diff)

    # Result type → HTTP translation
    if hasattr(result, "error"):
        # It's an Err
        code = getattr(result, "code", "UNKNOWN")
        if code == "NOT_FOUND":
            raise HTTPException(status_code=404, detail=result.error)
        raise HTTPException(status_code=500, detail=result.error)

    warnings = result.value
    severity_dist = {"high": 0, "medium": 0, "low": 0}
    for w in warnings:
        sev = w.get("severity", "low")
        if sev in severity_dist:
            severity_dist[sev] += 1

    recommendations = list({w["recommendation"] for w in warnings if w.get("recommendation")})

    return {
        "project": project,
        "warnings": warnings,
        "total_warnings": len(warnings),
        "severity_distribution": severity_dist,
        "recommendations": recommendations,
    }
