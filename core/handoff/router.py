"""
Agent Handoff Packets — FastAPI router.

Mount into the main app:
    from core.handoff.router import handoff_router
    app.include_router(handoff_router)
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.handoff.packet_builder import (
    HandoffPacket,
    ContextSlice,
    build_handoff_packet,
    ROLE_PROFILES,
)
from core.memory.manager import MemoryManager
from core.audit import append_audit_event, compute_hash
from core.agent_identity import normalize_agent_name

logger = logging.getLogger("tropelex.handoff")

handoff_router = APIRouter(prefix="/api/memory", tags=["handoff"])

_mm = MemoryManager()


def _load_memory(project: str) -> dict[str, Any]:
    """Load a project's memory, or raise 404."""
    if project not in _mm.list_projects():
        raise HTTPException(status_code=404, detail=f"Project '{project}' not found")
    return _mm.get_project_memory(project)


class HandoffRequest(BaseModel):
    role: str
    token_budget: int = 4000
    agent_name: str = "unspecified"


@handoff_router.post("/{project}/handoff")
async def generate_handoff(project: str, req: HandoffRequest) -> dict[str, Any]:
    """Generate a role-aware context packet for agent handoff.

    #59: the packet is hashed and logged into the append-only audit trail
    (core/audit.py, #52) at the moment it's generated -- tamper-evident,
    and gives the receiving agent something real to reference in a later
    POST /{project}/handoff/acknowledge call. Voluntary, not gating: no
    subsequent write is blocked on acknowledgment (see wishlist.md #59's
    deferred section for why a hard gate isn't built here).
    """
    try:
        memory = _load_memory(project)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("handoff load failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    packet: HandoffPacket = build_handoff_packet(
        project=project,
        role=req.role,
        memory=memory,
        token_budget=req.token_budget,
    )

    # Convert dataclasses to dicts for JSON serialization
    completeness_findings = [
        {
            "id": f.id, "severity": f.severity, "decision_id": f.decision_id,
            "decision_text": f.decision_text, "category": f.category,
            "description": f.description, "recommendation": f.recommendation,
        }
        for f in packet.completeness_findings
    ]
    response = {
        "role": packet.role,
        "project": packet.project,
        "context_slices": [
            {
                "category": s.category,
                "content": s.content,
                "priority": s.priority,
                "token_estimate": s.token_estimate,
            }
            for s in packet.context_slices
        ],
        "active_decisions": packet.active_decisions,
        "recent_sessions": packet.recent_sessions,
        "token_count": packet.token_count,
        "token_budget": packet.token_budget,
        "skills_summary": packet.skills_summary,
        "generated_at": packet.generated_at,
        "completeness_findings": completeness_findings,
    }

    agent_name = normalize_agent_name(req.agent_name)
    packet_hash = compute_hash(response)
    try:
        append_audit_event(
            memory, "handoff_created",
            role=req.role, agent_name=agent_name, packet_hash=packet_hash,
        )
        # #69: a must-survive decision dropped despite protection should
        # never happen through the real pipeline (see _check_completeness'
        # own docstring) -- if it ever does, it's audited, not silently
        # swallowed. Flag, don't block: generate_handoff still returns 200.
        for finding in completeness_findings:
            append_audit_event(
                memory, "handoff_completeness_violation",
                packet_hash=packet_hash, role=req.role, agent_name=agent_name,
                decision_id=finding["decision_id"], description=finding["description"],
            )
        _mm.save_project_memory(project, memory)
    except Exception as exc:
        # Audit logging must never break the actual handoff generation that
        # already succeeded above -- same "instrumentation can't break the
        # thing it's observing" stance as #45's session-shape capture.
        logger.error("handoff audit logging failed for %s: %s", project, exc)

    response["packet_hash"] = packet_hash
    return response


class HandoffAcknowledgeRequest(BaseModel):
    packet_hash: str
    agent_name: str = "unspecified"
    acknowledged_constraints: list[str] = []


@handoff_router.post("/{project}/handoff/acknowledge")
async def acknowledge_handoff(project: str, req: HandoffAcknowledgeRequest) -> dict[str, Any]:
    """Record that a receiving agent acknowledged a previously-generated
    handoff packet. 404s if packet_hash doesn't match a real
    handoff_created audit entry -- rejects acking a packet that was never
    actually generated, same "validate the reference is real" discipline
    as #53's override endpoint validating decision_id.
    """
    try:
        memory = _load_memory(project)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("handoff-acknowledge load failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    audit_log = memory.get("audit_log", [])
    known = any(
        isinstance(e, dict) and e.get("event_type") == "handoff_created"
        and e.get("packet_hash") == req.packet_hash
        for e in audit_log
    )
    if not known:
        raise HTTPException(
            status_code=404,
            detail=f"No handoff packet with hash '{req.packet_hash}' was generated for project '{project}'",
        )

    agent_name = normalize_agent_name(req.agent_name)
    try:
        append_audit_event(
            memory, "handoff_acknowledged",
            packet_hash=req.packet_hash, agent_name=agent_name,
            acknowledged_constraints=req.acknowledged_constraints,
        )
        _mm.save_project_memory(project, memory)
    except Exception as exc:
        logger.error("handoff-acknowledge save failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return {"acknowledged": True, "packet_hash": req.packet_hash, "agent_name": agent_name}


def _unacknowledged_handoffs(memory: dict[str, Any]) -> list[dict[str, Any]]:
    """Pure helper: handoff_created audit entries with no later matching
    handoff_acknowledged entry (same packet_hash). Defensive against
    malformed audit_log entries -- persisted, agent-supplied-adjacent
    data, same posture as #58's scheduler work."""
    audit_log = memory.get("audit_log", [])
    if not isinstance(audit_log, list):
        return []

    acknowledged_hashes = {
        e.get("packet_hash") for e in audit_log
        if isinstance(e, dict) and e.get("event_type") == "handoff_acknowledged"
    }
    return [
        {
            "packet_hash": e.get("packet_hash"),
            "role": e.get("role"),
            "agent_name": e.get("agent_name"),
            "created_at": e.get("timestamp"),
        }
        for e in audit_log
        if isinstance(e, dict)
        and e.get("event_type") == "handoff_created"
        and e.get("packet_hash") not in acknowledged_hashes
    ]


@handoff_router.get("/{project}/handoff/unacknowledged")
async def list_unacknowledged_handoffs(project: str) -> dict[str, Any]:
    """List handoff packets that were generated but never acknowledged --
    the triage queue behind Needs Attention's unacknowledged_handoff
    source (#59).

    Deliberately uses get_project_memory directly rather than
    _load_memory: get_needs_attention calls this unconditionally for
    every project it aggregates, including ones that have never had
    memory written to disk yet, the same way its other sources
    (list_flagged_decisions, list_decay_reviews, etc.) already treat a
    nonexistent project as an empty one rather than 404ing. _load_memory's
    strict existence check stays on generate_handoff/acknowledge_handoff,
    where it's the correct behavior for a direct call.
    """
    memory = _mm.get_project_memory(project)
    handoffs = _unacknowledged_handoffs(memory)
    return {"handoffs": handoffs, "count": len(handoffs)}


def _completeness_violations(memory: dict[str, Any]) -> list[dict[str, Any]]:
    """Pure helper: handoff_completeness_violation audit entries (#69).
    Same defensive posture as _unacknowledged_handoffs -- persisted,
    agent-supplied-adjacent data."""
    audit_log = memory.get("audit_log", [])
    if not isinstance(audit_log, list):
        return []
    return [
        {
            "decision_id": e.get("decision_id"),
            "packet_hash": e.get("packet_hash"),
            "role": e.get("role"),
            "agent_name": e.get("agent_name"),
            "description": e.get("description"),
            "flagged_at": e.get("timestamp"),
        }
        for e in audit_log
        if isinstance(e, dict) and e.get("event_type") == "handoff_completeness_violation"
    ]


@handoff_router.get("/{project}/handoff/completeness-violations")
async def list_completeness_violations(project: str) -> dict[str, Any]:
    """List recorded handoff-completeness violations (#69) -- the triage
    queue behind Needs Attention's handoff_completeness_violation source.

    Same lenient get_project_memory read as list_unacknowledged_handoffs,
    for the same reason: get_needs_attention calls this for every project,
    including ones with no memory file on disk yet.
    """
    memory = _mm.get_project_memory(project)
    violations = _completeness_violations(memory)
    return {"violations": violations, "count": len(violations)}


@handoff_router.get("/{project}/handoff/roles")
async def list_roles(project: str) -> dict[str, Any]:
    """List available handoff roles and their descriptions."""
    return {
        "roles": {
            name: profile["description"]
            for name, profile in ROLE_PROFILES.items()
        }
    }
