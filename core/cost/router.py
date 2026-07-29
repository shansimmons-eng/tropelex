"""
Cost Ledger — FastAPI router.

Mount into the main app:
    from core.cost.router import cost_router
    app.include_router(cost_router)
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.cost import CostEvent, CostError
from core.cost.tracker import CostTracker
from core.decision_tree import DecisionTree
from core.memory.manager import MemoryManager

logger = logging.getLogger("tropelex.cost")

cost_router = APIRouter(prefix="/api/memory", tags=["cost"])

_mm = MemoryManager()
BASE_DIR = Path(_mm.memory_dir).parent  # Kept for test compatibility; not used by _load_memory


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class CostEventRequest(BaseModel):
    """Request body for recording a cost event."""

    decision_id: str = Field(..., min_length=1)
    event_type: str = Field(..., min_length=1)
    amount: float = Field(..., ge=0)
    unit: str = Field(..., min_length=1)
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_memory(project: str) -> dict[str, Any]:
    """Load a project's memory, or raise 404."""
    if project not in _mm.list_projects():
        raise HTTPException(status_code=404, detail=f"Project '{project}' not found")
    return _mm.get_project_memory(project)


def _build_tracker(memory: dict[str, Any]) -> CostTracker:
    """Build a CostTracker from loaded memory.

    Creates a MemoryManager stub that returns the pre-loaded memory,
    so the tracker doesn't re-read from disk.
    """
    decisions = memory.get("decisions", [])
    tree = DecisionTree.from_decisions(decisions) if decisions else DecisionTree()

    # Stub MemoryManager that returns pre-loaded memory
    class _StubMM:
        def get_project_memory(self, _project: str) -> dict[str, Any]:
            return memory
        def save_project_memory(self, _project: str, _data: dict[str, Any]) -> None:
            pass  # no-op for report-only endpoints

    return CostTracker(decision_tree=tree, memory_manager=_StubMM())


def _now_iso() -> str:
    """Current UTC time as ISO string."""
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@cost_router.post("/{project}/cost/record")
async def record_cost(project: str, request: CostEventRequest) -> dict[str, Any]:
    """Record a cost event for a decision."""
    memory = _load_memory(project)
    tracker = _build_tracker(memory)

    event = CostEvent(
        id="",
        decision_id=request.decision_id,
        event_type=request.event_type,
        amount=request.amount,
        unit=request.unit,
        description=request.description,
        timestamp=_now_iso(),
        metadata=request.metadata,
    )

    try:
        recorded = tracker.record_cost_event(project, event)
    except CostError as exc:
        if exc.code == "VALIDATION_ERROR":
            logger.warning("cost validation error: %s", exc)
            raise HTTPException(status_code=422, detail=str(exc))
        logger.error("cost error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "id": recorded.id,
        "decision_id": recorded.decision_id,
        "event_type": recorded.event_type,
        "amount": recorded.amount,
        "unit": recorded.unit,
        "description": recorded.description,
        "timestamp": recorded.timestamp,
        "metadata": recorded.metadata,
    }


@cost_router.get("/{project}/cost/report")
async def cost_report(project: str) -> dict[str, Any]:
    """Return full cost report for a project."""
    memory = _load_memory(project)
    tracker = _build_tracker(memory)

    try:
        report = tracker.generate_cost_report(project)
    except CostError as exc:
        logger.error("cost report failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "project": report.project,
        "total_cost_usd": report.total_cost_usd,
        "total_tokens": report.total_tokens,
        "cost_per_decision": [
            {
                "decision_id": dc.decision_id,
                "decision_text": dc.decision_text,
                "total_cost_usd": dc.total_cost_usd,
                "total_tokens": dc.total_tokens,
                "event_count": dc.event_count,
                "reversal_cost": dc.reversal_cost,
            }
            for dc in report.cost_per_decision
        ],
        "rework_costs": report.rework_costs,
        "roi_scores": [
            {
                "decision_id": rs.decision_id,
                "cost": rs.cost,
                "impact_score": rs.impact_score,
                "roi": rs.roi,
            }
            for rs in report.roi_scores
        ],
        "period": report.period,
    }


@cost_router.get("/{project}/cost/compounding-risk")
async def compounding_risk(project: str) -> dict[str, Any]:
    """Decisions with real rework cost *and* poor Decision Market
    calibration in their category — the Cost Ledger + Decision Market
    compounding signal.

    High rework cost alone is common (rework happens). Poor calibration
    alone is common (every category has some bad bets). Both together on
    the same decision is the pattern worth surfacing: this category is
    expensive to get wrong AND the team has a track record of getting it
    wrong. Previously these lived in separate tabs with no link between them.
    """
    memory = _load_memory(project)
    tracker = _build_tracker(memory)

    try:
        report = tracker.generate_cost_report(project)
    except CostError as exc:
        logger.error("cost report failed for compounding-risk: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    from core.market import Err as MarketErr
    from core.market.calibration import compute_calibration

    bets = memory.get("market", {}).get("bets", [])
    calibration_result = compute_calibration(bets, project)
    category_scores = (
        {} if isinstance(calibration_result, MarketErr)
        else calibration_result.value.category_scores
    )

    decisions_by_id = {d.get("id"): d for d in memory.get("decisions", [])}
    compounding: list[dict[str, Any]] = []
    for dc in report.cost_per_decision:
        if dc.reversal_cost <= 0:
            continue
        decision = decisions_by_id.get(dc.decision_id, {})
        safety = decision.get("safety_metadata", {})
        categories = {safety.get("safety_category", "general"), *safety.get("affected_systems", [])}
        low_calibration = {
            cat: category_scores[cat] for cat in categories
            if category_scores.get(cat, 1.0) < 0.5
        }
        if low_calibration:
            compounding.append({
                "decision_id": dc.decision_id,
                "decision_text": dc.decision_text,
                "rework_cost_usd": dc.reversal_cost,
                "total_cost_usd": dc.total_cost_usd,
                "low_calibration_categories": low_calibration,
            })

    compounding.sort(key=lambda x: x["rework_cost_usd"], reverse=True)
    return {
        "project": project,
        "compounding_risk": compounding,
        "count": len(compounding),
    }


@cost_router.get("/{project}/cost/decision/{decision_id}")
async def decision_cost(project: str, decision_id: str) -> dict[str, Any]:
    """Return per-decision cost breakdown."""
    memory = _load_memory(project)

    # Verify decision exists in project
    decisions = memory.get("decisions", [])
    known_ids = {d.get("id") for d in decisions if d.get("id")}
    if decision_id not in known_ids:
        raise HTTPException(
            status_code=404,
            detail=f"Decision '{decision_id}' not found in project '{project}'",
        )

    tracker = _build_tracker(memory)

    try:
        breakdown = tracker.trace_decision_cost(project, decision_id)
    except Exception as exc:
        logger.error("decision cost trace failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    direct = breakdown["direct_cost"]
    return {
        "decision_id": breakdown["decision_id"],
        "direct_cost": {
            "decision_id": direct.decision_id,
            "decision_text": direct.decision_text,
            "total_cost_usd": direct.total_cost_usd,
            "total_tokens": direct.total_tokens,
            "event_count": direct.event_count,
            "reversal_cost": direct.reversal_cost,
        },
        "ancestor_costs": breakdown["ancestor_costs"],
        "descendant_costs": breakdown["descendant_costs"],
    }
