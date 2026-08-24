"""
Session-Shape Baselining — FastAPI router (wishlist.md #45).

Read-side only: the write path lives in core/tropebook/web/server.py's
record_session(), which is where session_shape data actually gets
ingested (via POST /sessions/record, the single "end a session" endpoint).
This router just exposes the current baseline + latest-session deviation
for one (project, agent) pair.

Mount into the main app:
    from core.session_shape.router import session_shape_router
    app.include_router(session_shape_router)
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from core.agent_identity import normalize_agent_name
from core.memory.manager import MemoryManager
from core.session_shape.baseline import filter_records_for_agent, latest_deviation_for_agent
from core.session_shape.correlation import (
    DEFAULT_WINDOW_DAYS,
    correlate_deviations_with_outcomes,
    deviations_for_agent,
    outcome_events_for_agent,
)

logger = logging.getLogger("tropelex.session_shape")

session_shape_router = APIRouter(prefix="/api/memory", tags=["session-shape"])

_mm = MemoryManager()


def _load_memory(project: str) -> dict[str, Any]:
    """Load a project's memory, or raise 404 — same convention as every
    other router in this codebase (e.g. core/ghost/preventive_router.py)."""
    if project not in _mm.list_projects():
        raise HTTPException(status_code=404, detail=f"Project '{project}' not found")
    return _mm.get_project_memory(project)


@session_shape_router.get("/{project}/agents/{agent}/session-shape")
async def get_agent_session_shape(project: str, agent: str) -> dict[str, Any]:
    """Latest session-shape deviation for one agent on this project,
    baselined against their prior sessions (excluding the one being
    evaluated). Returns {"status": "insufficient_data", ...} until at
    least MIN_BASELINE_SESSIONS prior sessions exist for this agent.
    """
    try:
        memory = _load_memory(project)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("session-shape load failed for %s: %s", project, exc)
        raise HTTPException(status_code=500, detail=str(exc))

    try:
        agent_name = normalize_agent_name(agent)
        records = filter_records_for_agent(memory.get("session_shapes", []), agent_name)
        result = latest_deviation_for_agent(records)
    except Exception as exc:
        logger.error("session-shape computation failed for %s/%s: %s", project, agent, exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return {"project": project, "agent_name": agent_name, **result}


@session_shape_router.get("/{project}/agents/{agent}/session-shape/correlation")
async def get_session_shape_correlation(
    project: str, agent: str, window_days: float = DEFAULT_WINDOW_DAYS,
) -> dict[str, Any]:
    """Does a session-shape deviation for this agent actually predict a
    worse outcome (a gate override, or a later elevated-friction scan)
    within `window_days` afterward, or is it noise? (#73-3)

    Reuses #45's own baseline/classify functions, re-run per historical
    record with self-exclusion, rather than a new detection mechanism --
    this is a join over data both features already collect, not a new
    signal. See core/session_shape/correlation.py's module docstring for
    why Market outcomes aren't included.
    """
    try:
        memory = _load_memory(project)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("session-shape correlation load failed for %s: %s", project, exc)
        raise HTTPException(status_code=500, detail=str(exc))

    try:
        agent_name = normalize_agent_name(agent)
        records = filter_records_for_agent(memory.get("session_shapes", []), agent_name)
        deviations = deviations_for_agent(records)
        outcomes = outcome_events_for_agent(memory, agent_name)
        result = correlate_deviations_with_outcomes(deviations, outcomes, window_days=window_days)
    except Exception as exc:
        logger.error("session-shape correlation computation failed for %s/%s: %s", project, agent, exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return {"project": project, "agent_name": agent_name, **result}
