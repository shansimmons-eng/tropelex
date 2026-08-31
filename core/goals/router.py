"""
Goals — FastAPI router.

Endpoints for proposing, listing, updating, and transitioning goals — the
prospective counterpart to Decisions. Goal-drift and goal-alignment
endpoints live here too (see core/goals/drift.py for the pure scoring
functions this router composes).

Mount into the main app:
    from core.goals.router import goals_router
    app.include_router(goals_router)
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from core.audit import append_audit_event
from core.friction.miner import compute_friction_penalty
from core.goals import Err, Ok
from core.goals.detector import detect_goals
from core.goals.drift import score_goal_drift, score_trend_drift, suggest_drift_review
from core.goals.logic import create_goal, list_goals, transition_status, update_goal
from core.market.calibration import compute_calibration
from core.memory.manager import MemoryManager
from core.triggers.goal_gate import GoalEvidenceRequiredError, require_goal_evidence

logger = logging.getLogger("tropelex.goals")

goals_router = APIRouter(prefix="/api/memory", tags=["goals"])

_mm = MemoryManager()


# ---------------------------------------------------------------------------
# Pydantic request models (API boundary only)
# ---------------------------------------------------------------------------


class GoalCreateRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)
    priority: str = Field("medium")
    category: str | None = Field(None, max_length=64)
    tags: list[str] = Field(default_factory=list)


class GoalUpdateRequest(BaseModel):
    text: str | None = Field(None, min_length=1, max_length=500)
    priority: str | None = None
    category: str | None = None
    tags: list[str] | None = None


class GoalStatusRequest(BaseModel):
    status: str = Field(..., pattern="^(proposed|active|achieved|abandoned)$")


class GoalDetectRequest(BaseModel):
    text: str = Field(..., max_length=20000)


# ---------------------------------------------------------------------------
# Helpers — same shape as core/market/router.py's _load_memory/_save_memory
# ---------------------------------------------------------------------------


def _load_memory(project: str) -> dict[str, Any]:
    if project not in _mm.list_projects():
        raise HTTPException(status_code=404, detail=f"Project '{project}' not found")
    try:
        return _mm.get_project_memory(project)
    except Exception as exc:
        logger.error("goals load failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


def _save_memory(project: str, memory: dict[str, Any]) -> None:
    try:
        _mm.save_project_memory(project, memory)
    except Exception as exc:
        logger.error("goals save failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


def _err_to_http(result: Err) -> HTTPException:
    status = 404 if result.code == "NOT_FOUND" else 422
    return HTTPException(status_code=status, detail=result.error)


# ---------------------------------------------------------------------------
# Routes — literal sub-paths (stats) must precede /{goal_id} routes
# ---------------------------------------------------------------------------


@goals_router.post("/{project}/goals")
async def create_goal_endpoint(project: str, req: GoalCreateRequest) -> dict[str, Any]:
    """Propose a new goal — the prospective counterpart to add_decision."""
    memory = _load_memory(project)
    goals = memory.get("goals", [])

    result = create_goal(goals, req.model_dump())
    if isinstance(result, Err):
        raise _err_to_http(result)

    memory["goals"] = result.value
    _save_memory(project, memory)
    return {"created": True, "goal": result.value[-1]}


@goals_router.get("/{project}/goals")
async def list_goals_endpoint(
    project: str, status: str | None = None, category: str | None = None
) -> dict[str, Any]:
    memory = _load_memory(project)
    goals = list_goals(memory.get("goals", []), status=status, category=category)
    return {"goals": goals, "count": len(goals)}


@goals_router.get("/{project}/goals/stats")
async def goal_stats(project: str) -> dict[str, Any]:
    """Literal route — must be declared before /{goal_id} below."""
    memory = _load_memory(project)
    goals = memory.get("goals", [])
    by_status: dict[str, int] = {}
    by_priority: dict[str, int] = {}
    for g in goals:
        by_status[g.get("status", "unknown")] = by_status.get(g.get("status", "unknown"), 0) + 1
        by_priority[g.get("priority", "unknown")] = by_priority.get(g.get("priority", "unknown"), 0) + 1
    return {"total": len(goals), "by_status": by_status, "by_priority": by_priority}


@goals_router.post("/{project}/goals/detect")
async def detect_goals_endpoint(project: str, req: GoalDetectRequest) -> dict[str, Any]:
    """Suggest goal candidates from pasted text — nothing persisted, same
    shape as POST /{project}/decisions/preview-category. Literal route,
    must stay declared before /{goal_id} below.
    """
    if project not in _mm.list_projects():
        raise HTTPException(status_code=404, detail=f"Project '{project}' not found")
    return {"candidates": detect_goals(req.text)}


@goals_router.get("/{project}/goals/{goal_id}")
async def get_goal(project: str, goal_id: str) -> dict[str, Any]:
    memory = _load_memory(project)
    for g in memory.get("goals", []):
        if g.get("id") == goal_id:
            return g
    raise HTTPException(status_code=404, detail=f"Goal '{goal_id}' not found")


@goals_router.patch("/{project}/goals/{goal_id}")
async def update_goal_endpoint(project: str, goal_id: str, req: GoalUpdateRequest) -> dict[str, Any]:
    memory = _load_memory(project)
    goals = memory.get("goals", [])
    target = next((g for g in goals if g.get("id") == goal_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail=f"Goal '{goal_id}' not found")

    updates = req.model_dump(exclude_none=True)
    result = update_goal(target, updates)
    if isinstance(result, Err):
        raise _err_to_http(result)

    memory["goals"] = [result.value if g.get("id") == goal_id else g for g in goals]
    _save_memory(project, memory)
    return {"updated": True, "goal": result.value}


@goals_router.patch("/{project}/goals/{goal_id}/status")
async def transition_goal_status(project: str, goal_id: str, req: GoalStatusRequest) -> dict[str, Any]:
    memory = _load_memory(project)
    goals = memory.get("goals", [])
    target = next((g for g in goals if g.get("id") == goal_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail=f"Goal '{goal_id}' not found")

    if req.status == "achieved":
        try:
            require_goal_evidence(goal_id, memory.get("decisions", []))
        except GoalEvidenceRequiredError as exc:
            raise HTTPException(status_code=422, detail=exc.to_dict())

    result = transition_status(target, req.status)
    if isinstance(result, Err):
        raise _err_to_http(result)

    memory["goals"] = [result.value if g.get("id") == goal_id else g for g in goals]
    _save_memory(project, memory)
    return {"transitioned": True, "goal": result.value}


class GoalAchieveOverrideRequest(BaseModel):
    rationale: str = Field(..., min_length=1, max_length=1000)
    agent_name: str = Field("unspecified", max_length=100)


@goals_router.post("/{project}/goals/{goal_id}/achieve-override")
async def override_goal_evidence(project: str, goal_id: str, req: GoalAchieveOverrideRequest) -> dict[str, Any]:
    """Force a goal to 'achieved' despite no decision referencing it via
    goal_id -- the explicit-override escape hatch for require_goal_evidence
    (core/triggers/goal_gate.py). Same shape as
    core/ghost/preventive_router.py's decision override: written into the
    append-only audit trail, not silently applied. The state-machine
    legality check in transition_status still applies underneath this --
    the override bypasses the evidence requirement, not the achieved
    transition having to come from 'active'.
    """
    memory = _load_memory(project)
    goals = memory.get("goals", [])
    target = next((g for g in goals if g.get("id") == goal_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail=f"Goal '{goal_id}' not found")

    result = transition_status(target, "achieved")
    if isinstance(result, Err):
        raise _err_to_http(result)

    memory["goals"] = [result.value if g.get("id") == goal_id else g for g in goals]

    override_id = uuid.uuid4().hex[:12]
    override_entry = {
        "id": override_id,
        "kind": "goal_achieved",
        "goal_id": goal_id,
        "rationale": req.rationale,
        "agent_name": req.agent_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    memory.setdefault("overrides", []).append(override_entry)
    append_audit_event(
        memory, "goal_achieved_without_evidence",
        override_id=override_id, goal_id=goal_id,
        rationale=req.rationale, agent_name=req.agent_name,
    )

    _save_memory(project, memory)
    return {"transitioned": True, "goal": result.value, "override": override_entry}


@goals_router.delete("/{project}/goals/{goal_id}")
async def delete_goal(project: str, goal_id: str) -> dict[str, Any]:
    memory = _load_memory(project)
    goals = memory.get("goals", [])
    remaining = [g for g in goals if g.get("id") != goal_id]
    if len(remaining) == len(goals):
        raise HTTPException(status_code=404, detail=f"Goal '{goal_id}' not found")
    memory["goals"] = remaining

    # Unlink rather than silently orphan — visible, not hidden, matching
    # this project's established pattern of surfacing state changes.
    decisions = memory.get("decisions", [])
    unlinked = 0
    for d in decisions:
        if d.get("goal_id") == goal_id:
            d["goal_id"] = None
            unlinked += 1

    _save_memory(project, memory)
    return {"deleted": True, "decisions_unlinked": unlinked}


@goals_router.get("/{project}/goals/{goal_id}/alignment")
async def get_goal_alignment(
    project: str, goal_id: str, window: int = Query(3, ge=2, le=25)
) -> dict[str, Any]:
    """Thin aggregator — composes existing/extracted pure functions, no new
    scoring math. Answers the three alignment-layer questions for one goal:
    is its linked work still tracking its stated text (semantic_drift), is
    risk/review behavior trending badly within that work (trend_drift), and
    how calibrated were the agents who bet on it (market_calibration).

    friction_penalty_project_wide is exactly that — project-wide, not
    goal-scoped. friction_history entries carry no decision_id/goal_id
    today, so a goal-scoped slice would be fabricated; labeling it
    honestly as project-wide context is the correct call, not a silent
    approximation.
    """
    memory = _load_memory(project)
    goal = next((g for g in memory.get("goals", []) if g.get("id") == goal_id), None)
    if goal is None:
        raise HTTPException(status_code=404, detail=f"Goal '{goal_id}' not found")

    linked = [d for d in memory.get("decisions", []) if d.get("goal_id") == goal_id]
    linked_ids = {d["id"] for d in linked if d.get("id")}

    semantic_drift = score_goal_drift(goal["text"], linked)
    trend_drift = score_trend_drift(linked, window=window)

    bets = [b for b in memory.get("market", {}).get("bets", []) if b.get("decision_id") in linked_ids]
    agents = sorted({b.get("agent_name") for b in bets if b.get("agent_name")})
    calibration_results = [compute_calibration(bets, agent) for agent in agents]
    market_calibration = [
        {
            "agent_name": r.value.agent_name,
            "accuracy": r.value.accuracy,
            "total_bets": r.value.total_bets,
            "overconfidence_index": r.value.overconfidence_index,
        }
        for r in calibration_results
        if isinstance(r, Ok)
    ]

    return {
        "goal_id": goal_id,
        "linked_decisions": len(linked),
        "semantic_drift": semantic_drift,
        "trend_drift": trend_drift,
        "market_calibration": market_calibration,
        "friction_penalty_project_wide": compute_friction_penalty(memory.get("friction_history", [])),
        # #44: suggest, don't save -- a real proposal on high semantic
        # drift, not another number to read past.
        "suggested_action": suggest_drift_review(goal, semantic_drift),
    }
