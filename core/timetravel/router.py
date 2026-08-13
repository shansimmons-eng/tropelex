"""
Time-Travel Debugger — FastAPI router for querying past memory states.

Mount into the main app:
    from core.timetravel.router import timetravel_router
    app.include_router(timetravel_router)
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from core.memory.manager import MemoryManager
from core.session_replay import SessionReplay
from core.session_insights import generate_retrospective, summarize_session
from core.timetravel import (
    Err,
    MemoryError,
    MemorySnapshot,
    Ok,
    ValidationError,
)
from core.timetravel.snapshot import (
    diff_snapshots,
    find_nearest_snapshot,
    reconstruct_memory_at_date,
)

logger = logging.getLogger("tropelex.timetravel")

timetravel_router = APIRouter(prefix="/api/memory", tags=["timetravel"])


# ── Pydantic models (API boundary) ─────────────────────────────────────────


class TimeTravelResponse(BaseModel):
    """Response for GET /{project}/timetravel/{date}."""

    project: str
    date: str
    memory: dict[str, Any]
    decision_count: int
    session_count: int


class DiffRequest(BaseModel):
    """Request body for POST /{project}/timetravel/diff."""

    date_from: str = Field(
        ..., min_length=8, max_length=40, description="ISO date or YYYY-MM-DD"
    )
    date_to: str = Field(
        ..., min_length=8, max_length=40, description="ISO date or YYYY-MM-DD"
    )


class DiffResponse(BaseModel):
    """Response for POST /{project}/timetravel/diff."""

    date_from: str
    date_to: str
    decisions_added: list[str]
    decisions_removed: list[str]
    sessions_added: int
    changes_summary: str


class RetrospectiveResponse(BaseModel):
    """Response for GET /{project}/timetravel/retrospective."""

    project: str
    period_days: int
    session_count: int
    retrospective: str | None


# ── Helpers ─────────────────────────────────────────────────────────────────


def _validate_project(project: str) -> None:
    """Raise HTTP 422 if project name contains disallowed characters."""
    if not re.match(r"^[a-zA-Z0-9_\-]+$", project):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid project name: {project!r}",
        )


def _load_sessions(base_dir: Path, project: str) -> list[dict[str, Any]]:
    """Load all session records for a project via SessionReplay.

    Raises HTTP 404 if no sessions exist.
    """
    replay = SessionReplay(str(base_dir))
    index_entries = replay.get_sessions(project, limit=100)
    if not index_entries:
        raise HTTPException(
            status_code=404,
            detail=f"No session history found for project '{project}'",
        )

    # Load full session records (with snapshots)
    full_sessions: list[dict[str, Any]] = []
    for entry in index_entries:
        session = replay.get_session(project, entry["session_id"])
        if session:
            full_sessions.append(session)

    if not full_sessions:
        raise HTTPException(
            status_code=404,
            detail=f"No recoverable sessions for project '{project}'",
        )
    return full_sessions


def _snapshot_to_response(snapshot: MemorySnapshot) -> TimeTravelResponse:
    """Convert a MemorySnapshot to a Pydantic response model."""
    return TimeTravelResponse(
        project=snapshot.project_name,
        date=snapshot.snapshot_date,
        memory=snapshot.memory,
        decision_count=snapshot.decision_count,
        session_count=snapshot.session_count,
    )


# ── Endpoints ───────────────────────────────────────────────────────────────
# Literal sub-paths (retrospective) must be declared before /{date} below --
# FastAPI matches routes in registration order, so /{date} would otherwise
# greedily swallow "retrospective" as a literal date string (same gotcha
# core/goals/router.py's own routes are ordered to avoid).


@timetravel_router.get("/{project}/timetravel/retrospective")
async def retrospective_endpoint(
    project: str, days: int = Query(7, ge=1, le=90),
) -> RetrospectiveResponse:
    """Generate a narrative retrospective across recent sessions (#19).

    Descriptive only -- what the data shows, not process-improvement
    advice (see core/session_insights.py's module docstring for why that
    bullet was deliberately cut). Returns retrospective: null (not an
    error) when there's no session history yet or no LLM backend
    available.
    """
    _validate_project(project)
    base_dir = Path(MemoryManager().base_path)
    replay = SessionReplay(str(base_dir))

    from datetime import datetime, timedelta, timezone

    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    all_sessions = replay.get_sessions(project, limit=100)
    recent = [s for s in all_sessions if s.get("timestamp", "") >= since]

    try:
        retrospective = await generate_retrospective(recent, f"last {days} day(s)", project=project)
    except Exception as exc:
        logger.error("retrospective generation failed for %s: %s", project, exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return RetrospectiveResponse(
        project=project,
        period_days=days,
        session_count=len(recent),
        retrospective=retrospective,
    )


@timetravel_router.get("/{project}/timetravel/{date}")
async def get_memory_at_date(project: str, date: str) -> TimeTravelResponse:
    """Return the project memory as it was on the given date.

    Replays all recorded sessions up to ``date`` and returns the resulting
    memory snapshot.  Returns 404 if no sessions exist before that date.
    """
    _validate_project(project)

    # Resolve base dir from MemoryManager
    base_dir = Path(MemoryManager().base_path)

    try:
        sessions = _load_sessions(base_dir, project)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to load sessions for %s: %s", project, exc)
        raise HTTPException(status_code=500, detail=f"Internal error: {exc}")

    result = reconstruct_memory_at_date(sessions, date)

    if isinstance(result, Err):
        code = result.code
        if code == "NOT_FOUND":
            raise HTTPException(status_code=404, detail=result.error)
        if code == "VALIDATION_ERROR":
            raise HTTPException(status_code=422, detail=result.error)
        raise HTTPException(status_code=500, detail=result.error)

    return _snapshot_to_response(result.value)


@timetravel_router.post("/{project}/timetravel/diff")
async def diff_memory_dates(project: str, body: DiffRequest) -> DiffResponse:
    """Diff project memory between two dates.

    Reconstructs memory at each date and computes the difference.
    Returns 404 if no snapshot exists for either date; 422 for bad input.
    """
    _validate_project(project)

    base_dir = Path(MemoryManager().base_path)

    try:
        sessions = _load_sessions(base_dir, project)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to load sessions for %s: %s", project, exc)
        raise HTTPException(status_code=500, detail=f"Internal error: {exc}")

    # Reconstruct at both dates
    result_a = reconstruct_memory_at_date(sessions, body.date_from)
    if isinstance(result_a, Err):
        code = result_a.code
        if code == "NOT_FOUND":
            raise HTTPException(
                status_code=404,
                detail=f"No snapshot for date_from: {result_a.error}",
            )
        if code == "VALIDATION_ERROR":
            raise HTTPException(status_code=422, detail=result_a.error)
        raise HTTPException(status_code=500, detail=result_a.error)

    result_b = reconstruct_memory_at_date(sessions, body.date_to)
    if isinstance(result_b, Err):
        code = result_b.code
        if code == "NOT_FOUND":
            raise HTTPException(
                status_code=404,
                detail=f"No snapshot for date_to: {result_b.error}",
            )
        if code == "VALIDATION_ERROR":
            raise HTTPException(status_code=422, detail=result_b.error)
        raise HTTPException(status_code=500, detail=result_b.error)

    snapshot_diff = diff_snapshots(result_a.value, result_b.value)

    return DiffResponse(
        date_from=snapshot_diff.date_from,
        date_to=snapshot_diff.date_to,
        decisions_added=snapshot_diff.decisions_added,
        decisions_removed=snapshot_diff.decisions_removed,
        sessions_added=snapshot_diff.sessions_added,
        changes_summary=snapshot_diff.changes_summary,
    )


@timetravel_router.post("/{project}/timetravel/sessions/{session_id}/summarize")
async def summarize_session_endpoint(project: str, session_id: str) -> dict[str, Any]:
    """Generate and persist an AI summary of one session's changes (#19).

    Separate from the human-editable `summary` field set at record time --
    this never overwrites it, and generating a new one just replaces the
    previous ai_summary, not the human one. Returns ai_summary: null (not
    an error) when no LLM backend is configured -- matches core.llm's own
    "no backend, no result" convention rather than treating unavailability
    as a failure.
    """
    _validate_project(project)
    base_dir = Path(MemoryManager().base_path)
    replay = SessionReplay(str(base_dir))

    session = replay.get_session(project, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found for project '{project}'")

    try:
        ai_summary = await summarize_session(session, project=project)
    except Exception as exc:
        logger.error("session summarize failed for %s/%s: %s", project, session_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))

    if ai_summary:
        replay.set_ai_summary(project, session_id, ai_summary)

    return {"project": project, "session_id": session_id, "ai_summary": ai_summary}
