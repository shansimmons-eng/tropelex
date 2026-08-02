"""
Friction Mining — FastAPI router.

Implicit signal detection from session transcripts.
Mount into the main app:
    from core.friction.router import friction_router
    app.include_router(friction_router)
"""

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.friction.miner import (
    FrictionZone,
    Ok,
    Err,
    compute_friction_score,
    detect_friction_signals,
    group_signals_by_zone,
)
from core.memory.manager import MemoryManager

logger = logging.getLogger("tropelex.friction")

friction_router = APIRouter(prefix="/api/memory", tags=["friction"])

_mm = MemoryManager()


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class FrictionScanRequest(BaseModel):
    """Body for the friction/scan endpoint."""

    transcript: str = Field(..., min_length=1, max_length=50000, description="Session transcript text")
    agent_name: str = Field("unspecified", max_length=100, description="Which AI agent produced this transcript")


def _load_memory(project: str) -> dict[str, Any]:
    """Load a project's memory, or raise 404."""
    if project not in _mm.list_projects():
        raise HTTPException(status_code=404, detail=f"Project '{project}' not found")
    return _mm.get_project_memory(project)


def _zone_to_dict(zone: FrictionZone) -> dict[str, Any]:
    """Convert a FrictionZone to a plain dict for JSON serialisation."""
    return {
        "start_line": zone.start_line,
        "end_line": zone.end_line,
        "zone_severity": zone.zone_severity,
        "description": zone.description,
        "signal_count": len(zone.signals),
    }


# ---------------------------------------------------------------------------
# POST /api/memory/{project}/friction/scan
# ---------------------------------------------------------------------------

@friction_router.post("/{project}/friction/scan")
async def friction_scan(project: str, body: FrictionScanRequest) -> dict[str, Any]:
    """Scan a session transcript for implicit friction signals.

    Detects rephrasing, retries, rapid edits, and escalation markers,
    then groups them into friction zones with an aggregate score.

    Returns 404 if project not found, 422 for invalid input, 500 on errors.
    """
    # Validate project exists
    try:
        _load_memory(project)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("friction-scan load failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    # Run friction detection (returns Result)
    result = detect_friction_signals(body.transcript)
    if isinstance(result, Err):
        if result.code == "TYPE_ERROR":
            raise HTTPException(status_code=422, detail=result.error)
        logger.error("friction detection failed: %s (%s)", result.error, result.code)
        raise HTTPException(status_code=500, detail=result.error)

    signals = result.value
    friction_score = compute_friction_score(signals)
    zones = group_signals_by_zone(signals)

    # Severity distribution
    severity_distribution: dict[str, int] = {}
    for sig in signals:
        severity_distribution[sig.severity] = severity_distribution.get(sig.severity, 0) + 1

    # Persist to friction_history so Safety scoring can see recent friction
    # trends, not just the single scan just run. Previously this only
    # returned results — friction_summary read from friction_history, but
    # nothing ever wrote to it.
    agent_name = (body.agent_name or "").strip() or "unspecified"
    memory = _load_memory(project)
    history = memory.setdefault("friction_history", [])
    history.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "friction_score": friction_score,
        "total_signals": len(signals),
        "severity_distribution": severity_distribution,
        "agent_name": agent_name,
    })
    memory["friction_history"] = history[-50:]  # bounded — most recent 50 scans
    _mm.save_project_memory(project, memory)

    return {
        "signals": [
            {
                "type": s.type,
                "severity": s.severity,
                "line_number": s.line_number,
                "text_snippet": s.text_snippet,
                "recommendation": s.recommendation,
            }
            for s in signals
        ],
        "friction_score": friction_score,
        "zones": [_zone_to_dict(z) for z in zones],
        "total_signals": len(signals),
        "severity_distribution": severity_distribution,
    }


# ---------------------------------------------------------------------------
# GET /api/memory/{project}/friction/summary
# ---------------------------------------------------------------------------

@friction_router.get("/{project}/friction/summary")
async def friction_summary(project: str) -> dict[str, Any]:
    """Return historical friction summary for a project.

    Reads stored friction history from memory if present.
    Returns 404 if project not found.
    """
    try:
        memory = _load_memory(project)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("friction-summary load failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    friction_history: list[dict[str, Any]] = memory.get("friction_history", [])

    return {
        "project": project,
        "total_scans": len(friction_history),
        "history": friction_history,
    }


# ---------------------------------------------------------------------------
# GET /api/memory/{project}/friction/summary/{agent}
# ---------------------------------------------------------------------------

@friction_router.get("/{project}/friction/summary/{agent}")
async def friction_summary_by_agent(project: str, agent: str) -> dict[str, Any]:
    """Return friction history filtered down to a single agent."""
    try:
        memory = _load_memory(project)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("friction-summary-by-agent load failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    from core.friction.miner import compute_friction_by_agent

    return compute_friction_by_agent(memory.get("friction_history", []), agent)
