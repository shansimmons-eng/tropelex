"""
Rationale Corroboration — FastAPI router.

Mount into the main app:
    from core.corroboration.router import corroboration_router
    app.include_router(corroboration_router)
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.corroboration import (
    CorroborationReport,
    Err,
)
from core.corroboration.corroborator import corroborate_decision
from core.memory.manager import MemoryManager
from core.tropebook.research import ResearchTool

logger = logging.getLogger("tropelex.corroboration")

corroboration_router = APIRouter(prefix="/api/memory", tags=["corroboration"])

_CORE_DIR = Path(__file__).parent.parent
BASE_DIR = _CORE_DIR.parent


# --- Pydantic request models ---


class CorroborateRequest(BaseModel):
    """Single-decision corroboration request."""

    decision_id: str = Field(..., min_length=1, max_length=200)
    force_refresh: bool = False


class CorroborateBatchRequest(BaseModel):
    """Batch corroboration request for multiple decisions."""

    decision_ids: list[str] = Field(..., min_length=1, max_length=50)
    force_refresh: bool = False


# --- Shared helpers (lazy singletons) ---


_state: dict[str, Any] = {"memory_manager": None, "research_tool": None}


def _get_memory_manager() -> MemoryManager:
    if _state["memory_manager"] is None:
        _state["memory_manager"] = MemoryManager(str(BASE_DIR))
    return _state["memory_manager"]


def _get_research_tool() -> ResearchTool:
    if _state["research_tool"] is None:
        _state["research_tool"] = ResearchTool()
    return _state["research_tool"]


def _verify_project_exists(project: str) -> None:
    """Raise 404 if project memory file doesn't exist."""
    path = BASE_DIR / "memory" / f"{Path(project).name}.json"
    if not path.exists():
        raise HTTPException(
            status_code=404, detail=f"Project '{project}' not found"
        )


def _report_to_dict(report: CorroborationReport) -> dict[str, Any]:
    """Convert a frozen CorroborationReport dataclass to a JSON-serialisable dict."""
    return {
        "decision_id": report.decision_id,
        "rationale": report.rationale,
        "research_findings": [
            {
                "title": f.title,
                "url": f.url,
                "description": f.description,
                "source": f.source,
                "relevance_score": f.relevance_score,
            }
            for f in report.research_findings
        ],
        "status": report.status.value,
        "confidence_adjustment": report.confidence_adjustment,
        "evidence_urls": list(report.evidence_urls),
        "checked_at": report.checked_at,
    }


# --- Routes ---


@corroboration_router.post("/{project}/corroborate")
async def corroborate_project_decision(
    project: str, body: CorroborateRequest
) -> dict[str, Any]:
    """Corroborate a single decision's rationale against live web research.

    Returns a CorroborationReport with status, evidence, and confidence adjustment.
    """
    _verify_project_exists(project)

    mm = _get_memory_manager()
    rt = _get_research_tool()

    result = corroborate_decision(
        project=project,
        decision_id=body.decision_id,
        research_tool=rt,
        memory_manager=mm,
        force_refresh=body.force_refresh,
    )

    if isinstance(result, Err):
        _err = result
        logger.error(
            "corroboration failed for %s/%s: [%s] %s",
            project, body.decision_id, _err.code, _err.error,
        )
        if _err.code == "NOT_FOUND":
            raise HTTPException(status_code=404, detail=_err.error)
        if _err.code == "MEMORY_ERROR":
            raise HTTPException(status_code=404, detail=_err.error)
        if _err.code == "VALIDATION_ERROR":
            raise HTTPException(status_code=422, detail=_err.error)
        if _err.code == "RESEARCH_ERROR":
            raise HTTPException(status_code=500, detail=_err.error)
        raise HTTPException(status_code=500, detail=_err.error)

    return _report_to_dict(result.value)


@corroboration_router.post("/{project}/corroborate/batch")
async def corroborate_batch(
    project: str, body: CorroborateBatchRequest
) -> dict[str, Any]:
    """Corroborate multiple decisions in one call.

    Returns per-decision results plus an aggregate summary.
    """
    _verify_project_exists(project)

    mm = _get_memory_manager()
    rt = _get_research_tool()

    results: list[dict[str, Any]] = []
    summary = {
        "supported": 0,
        "outdated": 0,
        "contradicted": 0,
        "unverifiable": 0,
    }

    for decision_id in body.decision_ids:
        result = corroborate_decision(
            project=project,
            decision_id=decision_id,
            research_tool=rt,
            memory_manager=mm,
            force_refresh=body.force_refresh,
        )

        if isinstance(result, Err):
            _err = result
            logger.warning(
                "batch corroboration: %s/%s failed: [%s] %s",
                project, decision_id, _err.code, _err.error,
            )
            results.append(
                {
                    "decision_id": decision_id,
                    "status": "unverifiable",
                    "error": _err.error,
                }
            )
            summary["unverifiable"] += 1
        else:
            report_dict = _report_to_dict(result.value)
            results.append(report_dict)
            status = report_dict["status"]
            if status in summary:
                summary[status] += 1
            else:
                summary["unverifiable"] += 1

    return {
        "results": results,
        "summary": summary,
        "total": len(results),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
