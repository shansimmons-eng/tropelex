"""
PR Bot — FastAPI router for PR comment generation.

Mount into the main app:
    from core.prbot.router import prbot_router
    app.include_router(prbot_router)
"""

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.memory.manager import MemoryManager
from core.prbot import Err, Ok
from core.prbot.analyzer import analyze_pr_diff
from core.prbot.comment_builder import build_pr_comment

logger = logging.getLogger("tropelex.prbot")

prbot_router = APIRouter(prefix="/api/memory", tags=["prbot"])

_CORE_DIR = Path(__file__).parent.parent
BASE_DIR = _CORE_DIR.parent

_mm: MemoryManager | None = None


def _get_memory_manager() -> MemoryManager:
    """Lazy-initialized MemoryManager singleton."""
    global _mm
    if _mm is None:
        _mm = MemoryManager(str(BASE_DIR))
    return _mm


class PRCommentRequestBody(BaseModel):
    """Pydantic request model — validates at API boundary."""

    diff: str = Field(..., min_length=1, max_length=100_000)
    pr_title: str = Field("", max_length=500)
    pr_body: str = Field("", max_length=10_000)


def _require_project_exists(project: str) -> None:
    """Raise 404 if project doesn't exist."""
    mm = _get_memory_manager()
    if project not in mm.list_projects():
        raise HTTPException(
            status_code=404,
            detail=f"Project '{project}' not found",
        )


def _load_memory(project: str) -> dict[str, Any]:
    """Load project memory, translating errors to HTTP."""
    try:
        mm = _get_memory_manager()
        return mm.get_project_memory(project)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Failed to load memory for %s: %s", project, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load project memory: {exc}",
        )


def _result_to_http(result: Err) -> None:
    """Translate a Result Err into the appropriate HTTPException."""
    status = 422 if result.code == "VALIDATION_ERROR" else 500
    raise HTTPException(status_code=status, detail=result.error)


def _serialize_comment(comment: Any) -> dict[str, Any]:
    """Serialize PRComment dataclass (with nested dataclasses) to JSON-safe dict."""
    return {
        "body": comment.body,
        "decisions_mentioned": [
            {
                "decision_id": d.decision_id,
                "decision_text": d.decision_text,
                "confidence": d.confidence,
                "relevance_score": d.relevance_score,
                "impact_score": d.impact_score,
                "relationship": d.relationship,
            }
            for d in comment.decisions_mentioned
        ],
        "ghost_warnings": [
            {
                "decision_id": w.decision_id,
                "severity": w.severity,
                "matched_keywords": w.matched_keywords,
                "recommendation": w.recommendation,
            }
            for w in comment.ghost_warnings
        ],
        "relevance_score": comment.relevance_score,
        "decision_count": comment.decision_count,
        "warning_count": comment.warning_count,
    }


@prbot_router.post("/{project}/pr-comment")
async def generate_pr_comment(
    project: str,
    body: PRCommentRequestBody,
) -> dict[str, Any]:
    """Analyze a PR diff and generate a formatted comment with decision context."""
    _require_project_exists(project)
    try:
        memory = _load_memory(project)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to load memory for %s: %s", project, exc)
        raise HTTPException(status_code=500, detail=str(exc))

    analysis = analyze_pr_diff(memory, body.diff, body.pr_title, body.pr_body)
    if isinstance(analysis, Err):
        _result_to_http(analysis)

    comment = build_pr_comment(analysis.value, project)
    if isinstance(comment, Err):
        _result_to_http(comment)

    return _serialize_comment(comment.value)


@prbot_router.post("/{project}/pr-comment/preview")
async def preview_pr_comment(
    project: str,
    body: PRCommentRequestBody,
) -> dict[str, Any]:
    """Preview the markdown body of a PR comment (for testing)."""
    _require_project_exists(project)
    memory = _load_memory(project)

    analysis = analyze_pr_diff(memory, body.diff, body.pr_title, body.pr_body)
    if isinstance(analysis, Err):
        _result_to_http(analysis)

    comment = build_pr_comment(analysis.value, project)
    if isinstance(comment, Err):
        _result_to_http(comment)

    return {
        "markdown": comment.value.body,
        "relevance_score": comment.value.relevance_score,
    }
