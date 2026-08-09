"""
Friction Mining — FastAPI router.

Implicit signal detection from session transcripts.
Mount into the main app:
    from core.friction.router import friction_router
    app.include_router(friction_router)
"""

import logging
import uuid as _uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.friction.miner import (
    FrictionSignal,
    FrictionZone,
    Ok,
    Err,
    compute_friction_score,
    detect_friction_signals,
    group_signals_by_zone,
    suggest_decision_from_zone,
)
from core.agent_identity import normalize_agent_name
from core.audit import append_audit_event
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


class DismissRequest(BaseModel):
    """Body for dismissing a friction zone (#62).

    agent_name + reason are only *required* when the zone being dismissed
    is high-severity — same accountability bar as #53's OverrideRequest,
    applied here to a signal being discarded rather than a gate being
    bypassed. Both stay optional at the schema level; severity-conditional
    enforcement happens in the handler so low/medium dismissal can stay a
    plain status flip with no modal.
    """

    agent_name: str | None = Field(None, max_length=100)
    reason: str | None = Field(None, max_length=1000)


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


def _signal_to_dict(sig: FrictionSignal) -> dict[str, Any]:
    """Convert a FrictionSignal to a plain dict — same field set as
    core/ghost/preventive_router.py's _warning_to_dict pattern."""
    return {
        "type": sig.type,
        "severity": sig.severity,
        "line_number": sig.line_number,
        "text_snippet": sig.text_snippet,
        "recommendation": sig.recommendation,
    }


def _zone_to_persisted_dict(
    zone: FrictionZone, zone_id: str, agent_name: str, suggested: dict[str, str] | None
) -> dict[str, Any]:
    """Build the full persisted record for a friction zone (#62) — unlike
    _zone_to_dict (the scan response's lightweight summary), this keeps the
    actual signal text, which friction_history's numeric aggregates never
    stored at all."""
    return {
        "id": zone_id,
        "start_line": zone.start_line,
        "end_line": zone.end_line,
        "zone_severity": zone.zone_severity,
        "description": zone.description,
        "signals": [_signal_to_dict(s) for s in zone.signals],
        "suggested_decision": suggested,
        "agent_name": agent_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "review_status": "pending",
    }


def _bound_friction_zones(zones: list[dict[str, Any]], max_reviewed: int = 200) -> list[dict[str, Any]]:
    """Cap stored friction_zones without ever silently dropping a pending
    one. friction_history's flat "most recent 50" cap is fine there because
    every entry is already-processed aggregate data; a pending zone is
    exactly the not-yet-reviewed data #62 exists to stop losing, so only
    already-reviewed (kept/dismissed) entries count against the cap."""
    pending = [z for z in zones if z.get("review_status") == "pending"]
    reviewed = [z for z in zones if z.get("review_status") != "pending"]
    return pending + reviewed[-max_reviewed:]


def _find_zone(memory: dict[str, Any], zone_id: str) -> dict[str, Any] | None:
    for z in memory.get("friction_zones", []):
        if z.get("id") == zone_id:
            return z
    return None


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

    agent_name = normalize_agent_name(body.agent_name)
    memory = _load_memory(project)

    # #56: high-severity zones get a suggested decision candidate — the same
    # "suggest, don't save" shape as detect_goals/preview-category, so a
    # repeated-correction cluster surfaces something actionable instead of
    # just a score. Computed once per zone here so both the flat
    # suggested_decisions list (unchanged response shape) and the persisted
    # zone record (#62, carries its own suggestion inline) share one call.
    suggested_decisions: list[dict[str, str]] = []
    persisted_zones: list[dict[str, Any]] = []
    for z in zones:
        suggestion = suggest_decision_from_zone(z)
        if suggestion is not None:
            suggested_decisions.append(suggestion)
        persisted_zones.append(_zone_to_persisted_dict(z, _uuid.uuid4().hex[:12], agent_name, suggestion))

    # Persist to friction_history so Safety scoring can see recent friction
    # trends, not just the single scan just run. Previously this only
    # returned results — friction_summary read from friction_history, but
    # nothing ever wrote to it.
    history = memory.setdefault("friction_history", [])
    history.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "friction_score": friction_score,
        "total_signals": len(signals),
        "severity_distribution": severity_distribution,
        "agent_name": agent_name,
    })
    memory["friction_history"] = history[-50:]  # bounded — most recent 50 scans

    # #62: persist the zones themselves (not just the numeric aggregate
    # above) so they can be kept/dismissed instead of only existing for the
    # lifetime of this response.
    existing_zones = memory.get("friction_zones", [])
    memory["friction_zones"] = _bound_friction_zones(existing_zones + persisted_zones)

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
        "suggested_decisions": suggested_decisions,
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


# ---------------------------------------------------------------------------
# #62: Friction zone persistence + generic review queue (keep/dismiss)
# ---------------------------------------------------------------------------

@friction_router.get("/{project}/friction/zones")
async def list_friction_zones(project: str, status: str | None = None) -> dict[str, Any]:
    """List persisted friction zones, optionally filtered by review_status
    (pending|kept|dismissed) — same query-param filter shape as Goals'
    list_goals category filter (#41/#51). Newest first."""
    try:
        memory = _load_memory(project)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("friction-zones list failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    zones = memory.get("friction_zones", [])
    if status:
        zones = [z for z in zones if z.get("review_status") == status]
    zones = sorted(zones, key=lambda z: z.get("timestamp", ""), reverse=True)

    return {"project": project, "total": len(zones), "zones": zones}


@friction_router.post("/{project}/friction/zones/{zone_id}/keep")
async def keep_friction_zone(project: str, zone_id: str) -> dict[str, Any]:
    """Mark a friction zone as kept — the signal was real and worth
    retaining. No accountability bar: keeping something is the safe
    default action, unlike dismissing a high-severity signal, so this
    needs no rationale. Kept zones are future input to #62's deferred
    "cycle back into the flow" pass — not built yet, this just marks them."""
    try:
        memory = _load_memory(project)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("friction-zone keep load failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    zone = _find_zone(memory, zone_id)
    if zone is None:
        raise HTTPException(status_code=404, detail=f"Friction zone '{zone_id}' not found in project '{project}'")

    zone["review_status"] = "kept"
    _mm.save_project_memory(project, memory)

    return {"updated": True, "zone": zone}


@friction_router.post("/{project}/friction/zones/{zone_id}/dismiss")
async def dismiss_friction_zone(project: str, zone_id: str, body: DismissRequest) -> dict[str, Any]:
    """Dismiss a friction zone.

    High-severity zones require agent_name + reason (422 without them) and
    get written into the append-only audit trail (core/audit.py, #52) as a
    friction_dismissed event — the same accountability bar #53's override
    applies to bypassing a gate, applied here to discarding a signal.
    Low/medium dismissal is a plain status flip, no justification needed —
    matching the gate's own block/warn/log_only severity split.
    """
    try:
        memory = _load_memory(project)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("friction-zone dismiss load failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    zone = _find_zone(memory, zone_id)
    if zone is None:
        raise HTTPException(status_code=404, detail=f"Friction zone '{zone_id}' not found in project '{project}'")

    if zone.get("zone_severity") == "high":
        if not body.agent_name or not body.reason:
            raise HTTPException(status_code=422, detail={
                "error": "dismiss_reason_required",
                "message": "Dismissing a high-severity friction zone requires agent_name and reason.",
                "zone_severity": "high",
            })
        zone["review_status"] = "dismissed"
        append_audit_event(
            memory,
            "friction_dismissed",
            zone_id=zone_id,
            zone_severity="high",
            agent_name=body.agent_name,
            reason=body.reason,
        )
    else:
        zone["review_status"] = "dismissed"

    _mm.save_project_memory(project, memory)

    return {"updated": True, "zone": zone}
