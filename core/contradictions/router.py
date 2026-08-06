"""
Contradiction Detection — FastAPI router.

Mount into the main app:
    from core.contradictions.router import contradiction_router
    app.include_router(contradiction_router)
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from core.contradictions import ContradictionError
from core.contradictions.detector import detect_contradictions
from core.memory.manager import MemoryManager

logger = logging.getLogger("tropelex.contradictions")

contradiction_router = APIRouter(prefix="/api/memory", tags=["contradictions"])

_mm = MemoryManager()


def _load_memory(project: str) -> dict[str, Any]:
    """Load a project's memory, or raise 404."""
    if project not in _mm.list_projects():
        raise HTTPException(status_code=404, detail=f"Project '{project}' not found")
    return _mm.get_project_memory(project)


def _escalate_to_review(memory: dict[str, Any], decision_ids: set[str]) -> int:
    """Flip requires_review=True on decisions referenced by a high-severity
    finding, if not already flagged — an unresolved contradiction in a
    decision that was never marked for review is exactly the kind of thing
    the Safety Review queue exists to catch, so it shouldn't have to wait
    for someone to separately notice it in the Contradictions tab.

    Mutates memory in place. Returns how many decisions were newly escalated.
    """
    escalated = 0
    for d in memory.get("decisions", []):
        if d.get("id") not in decision_ids:
            continue
        safety = d.setdefault("safety_metadata", {})
        if safety.get("requires_review"):
            continue
        # A human already reviewed this decision at least once — respect
        # that resolution rather than re-flagging it every time contradictions
        # are re-scanned. A contradiction doesn't structurally "resolve" just
        # because someone approved one side of it, so without this check,
        # approving (which sets requires_review=False) gets undone on the
        # very next /contradictions call as long as the pair stays
        # unresolved -- the same bug already fixed once for the persona/
        # market escalation path (_apply_persona_market_escalation), just
        # never applied here too.
        if d.get("safety_reviews"):
            continue
        safety["requires_review"] = True
        if safety.get("risk_level", "low") == "low":
            safety["risk_level"] = "medium"
        escalated += 1
    return escalated


@contradiction_router.get("/{project}/contradictions")
async def project_contradictions(project: str) -> dict[str, Any]:
    """Scan a project's decisions for contradictions.

    Returns a list of contradictions with type, severity, and resolution
    suggestions. Integrates with the Health Dashboard via the summary stats.
    High-severity contradictions auto-escalate their decisions into the
    Safety Review queue (requires_review=True) rather than only surfacing
    here.
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

    high_severity_ids = {
        did
        for c in report.contradictions if c.severity == "high"
        for did in (c.decision_a_id, c.decision_b_id)
    }
    escalated_count = 0
    if high_severity_ids:
        escalated_count = _escalate_to_review(memory, high_severity_ids)
        if escalated_count:
            _mm.save_project_memory(project, memory)

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
        # Safety Review integration: high-severity contradictions auto-flag
        # their decisions for review rather than waiting to be noticed here.
        "escalated_to_review": escalated_count,
    }
