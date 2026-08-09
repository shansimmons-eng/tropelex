"""
Preventive Ghost Checks — FastAPI router.

Pre-write guardrail: checks a proposed diff against active decisions
before code is written, surfacing warnings as a guardrail.

Mount into the main app:
    from core.ghost.preventive_router import preventive_router
    app.include_router(preventive_router)
"""

import logging
import uuid as _uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.audit import append_audit_event
from core.ghost.preventive import check_diff_for_warnings
from core.memory.manager import MemoryManager
from core.prevention_report import build_prevention_report
from core.telemetry import _emit_telemetry

logger = logging.getLogger("tropelex.ghost.preventive")

preventive_router = APIRouter(prefix="/api/memory", tags=["ghost-preventive"])

_mm = MemoryManager()

# Default enforcement policy per ghost-warning severity tier. "block" means
# ghost_check raises instead of returning 200 — see #53 (wishlist.md): the
# point is that a non-2xx response is what actually stops an MCP tool call
# (mcp_server/server.py's _request raises on any status >= 400), where a
# warning buried in a 200 body is easy for an agent to skip past. A project
# can loosen/tighten this via memory["gate_policy"]; unset tiers fall back
# to this default.
_DEFAULT_GATE_POLICY: dict[str, str] = {"high": "block", "medium": "warn", "low": "log_only"}


def _load_memory(project: str) -> dict[str, Any]:
    """Load a project's memory, or raise 404."""
    if project not in _mm.list_projects():
        raise HTTPException(status_code=404, detail=f"Project '{project}' not found")
    return _mm.get_project_memory(project)


def _save_memory(project: str, memory: dict[str, Any]) -> None:
    try:
        _mm.save_project_memory(project, memory)
    except Exception as exc:
        logger.error("ghost-preventive save failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


def _policy_for(memory: dict[str, Any], severity: str) -> str:
    """Resolve the enforcement action for a severity tier: project override
    (memory["gate_policy"]) if set, else the module default."""
    overrides = memory.get("gate_policy") or {}
    return overrides.get(severity, _DEFAULT_GATE_POLICY.get(severity, "log_only"))


def _severity_counts(warnings: list[dict[str, Any]]) -> dict[str, int]:
    """Tally warnings by severity tier, for a single gate_blocked/gate_warned
    audit event covering a whole ghost-check call (not one event per
    warning — see #61)."""
    counts = {"high": 0, "medium": 0, "low": 0}
    for w in warnings:
        sev = w.get("severity", "low")
        if sev in counts:
            counts[sev] += 1
    return counts


def _overridden_decision_ids(memory: dict[str, Any]) -> set[str]:
    """Decision IDs with at least one recorded override — suppresses
    blocking for that decision going forward. The override stays visible
    in the response (severity/warning untouched); it just stops forcing a
    non-2xx result once a human/agent has explicitly accepted the risk."""
    return {o["decision_id"] for o in memory.get("overrides", []) if o.get("decision_id")}


class GhostCheckRequest(BaseModel):
    """Request body for pre-write ghost diff checking."""
    diff: str = Field(..., min_length=1, max_length=100000,
                      description="Unified diff text to check against decisions")


class OverrideRequest(BaseModel):
    """Request body for overriding a blocked ghost warning on a decision."""
    rationale: str = Field(..., min_length=1, max_length=1000,
                           description="Why this warning is being overridden")
    agent_name: str = Field(..., min_length=1, max_length=100)


@preventive_router.post("/{project}/ghost-check")
async def ghost_check(project: str, body: GhostCheckRequest) -> dict[str, Any]:
    """Check a proposed diff against active decisions before writing.

    Returns warnings for any decisions that may be contradicted by the diff.
    This is a pre-write hook — call before finalizing a diff.

    Enforcement (#53): each warning's severity maps to a policy action
    (block/warn/log_only — see _policy_for). If any warning resolves to
    "block" and its decision has no recorded override, this raises 409
    instead of returning 200 — a real gate, not just data an agent can
    skip past. mcp_server/server.py's MCP wrapper raises on any non-2xx
    status, so a blocked ghost-check surfaces as a tool failure the
    calling agent has to actually handle: fix the diff, or call
    POST /{project}/decisions/{decision_id}/override with a rationale.
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

    overridden = _overridden_decision_ids(memory)
    blocking: list[dict[str, Any]] = []
    warn_tier: list[dict[str, Any]] = []
    for w in warnings:
        policy = _policy_for(memory, w.get("severity", "low"))
        w["policy"] = policy
        w["overridden"] = w.get("decision_id") in overridden
        if w["overridden"]:
            continue
        if policy == "block":
            blocking.append(w)
        elif policy == "warn":
            warn_tier.append(w)

    _emit_telemetry("GHOST", f"Drift check run for {project} ({len(warnings)} warning(s))")

    # #61 (wishlist.md): log_only-tier warnings never got an audit trace
    # before this, and block/warn tiers only ever wrote an "override" event
    # if an agent later bypassed them — a warning that was correctly
    # obeyed left zero trace. This is what the Prevention Report reads.
    mutated = False
    if blocking:
        append_audit_event(
            memory,
            "gate_blocked",
            decision_ids=list({w["decision_id"] for w in blocking if w.get("decision_id")}),
            severity_counts=_severity_counts(blocking),
        )
        mutated = True
    if warn_tier:
        append_audit_event(
            memory,
            "gate_warned",
            decision_ids=list({w["decision_id"] for w in warn_tier if w.get("decision_id")}),
            severity_counts=_severity_counts(warn_tier),
        )
        mutated = True
    if mutated:
        _save_memory(project, memory)

    if blocking:
        raise HTTPException(status_code=409, detail={
            "message": (
                f"{len(blocking)} warning(s) blocked by gate policy — fix the diff or call "
                f"POST /api/memory/{project}/decisions/{{decision_id}}/override with a rationale to proceed."
            ),
            "project": project,
            "blocking_warnings": blocking,
            "total_warnings": len(warnings),
            "severity_distribution": severity_dist,
        })

    return {
        "project": project,
        "warnings": warnings,
        "total_warnings": len(warnings),
        "severity_distribution": severity_dist,
        "recommendations": recommendations,
    }


@preventive_router.post("/{project}/decisions/{decision_id}/override")
async def override_ghost_warning(project: str, decision_id: str, body: OverrideRequest) -> dict[str, Any]:
    """Record an explicit override for ghost/contradiction warnings against
    one decision, so future ghost-check calls stop blocking on it.

    The override itself is written into the append-only audit trail
    (core/audit.py, #52) as an "override" event — it becomes part of the
    same tamper-evident record as decision creation and review, not a
    parallel, unaudited mechanism. Warnings against the decision keep
    showing up (marked "overridden": true) — this suppresses the block,
    it doesn't hide the underlying signal.
    """
    try:
        memory = _load_memory(project)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("override load failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    if not any(d.get("id") == decision_id for d in memory.get("decisions", [])):
        raise HTTPException(status_code=404, detail=f"Decision '{decision_id}' not found in project '{project}'")

    override_id = _uuid.uuid4().hex[:12]
    override_entry = {
        "id": override_id,
        "decision_id": decision_id,
        "rationale": body.rationale,
        "agent_name": body.agent_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    memory.setdefault("overrides", []).append(override_entry)
    append_audit_event(
        memory,
        "override",
        override_id=override_id,
        decision_id=decision_id,
        rationale=body.rationale,
        agent_name=body.agent_name,
    )
    _save_memory(project, memory)
    _emit_telemetry("GHOST", f"Warning override recorded for decision {decision_id} in {project}")

    return {"created": True, "override": override_entry}


@preventive_router.get("/{project}/prevention-report")
async def prevention_report(project: str) -> dict[str, Any]:
    """"What have we prevented so far?" (#61) — aggregates the append-only
    audit trail (core/audit.py, #52) into historical counts of gate blocks,
    gate warnings, contradiction escalations, and overrides.

    Pure read over audit_log; see core/prevention_report.py for the
    aggregation itself. Historical only: events from before this feature
    shipped were never logged (gate_blocked/gate_warned/
    contradiction_escalated didn't exist as event types yet), so a project
    with a long history but no report activity isn't evidence nothing was
    ever prevented — the same honestly-disclosed backfill limitation #52
    already carries for its own audit log.
    """
    memory = _load_memory(project)
    report = build_prevention_report(memory.get("audit_log", []))
    return {"project": project, **report}
