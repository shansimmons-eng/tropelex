"""
Decision Market — FastAPI router.

Endpoints for placing confidence bets, viewing calibration scores,
and checking the agent leaderboard.

Mount into the main app:
    from core.market.router import market_router
    app.include_router(market_router)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from core.agent_identity import normalize_agent_name
from core.market import CalibrationScore, Err, LeaderboardEntry, Ok, Result
from core.market.calibration import (
    compute_calibration,
    compute_leaderboard,
    record_bet,
    resolve_bet,
)
from core.memory.manager import MemoryManager

logger = logging.getLogger("tropelex.market")

market_router = APIRouter(prefix="/api/memory", tags=["market"])

_mm = MemoryManager()


# ---------------------------------------------------------------------------
# Pydantic request/response models (API boundary only)
# ---------------------------------------------------------------------------


class BetPlaceRequest(BaseModel):
    """Inbound request to place a new confidence bet."""

    decision_id: str = Field(..., min_length=1, max_length=128)
    agent_name: str = Field(..., min_length=1, max_length=100)
    confidence: float = Field(..., ge=0.0, le=1.0)
    category: str = Field(..., min_length=1, max_length=64)


class BetResolveRequest(BaseModel):
    """Inbound request to resolve an existing bet."""

    bet_id: str = Field(..., min_length=1, max_length=128)
    outcome: str = Field(..., pattern=r"^(correct|incorrect)$")


class CalibrationResponse(BaseModel):
    """Calibration metrics for an agent."""

    agent_name: str
    total_bets: int
    correct_bets: int
    accuracy: float
    category_scores: dict[str, float]
    overconfidence_index: float


class LeaderboardResponse(BaseModel):
    """A single leaderboard row."""

    agent_name: str
    accuracy: float
    total_bets: int
    categories: list[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_memory(project: str) -> dict[str, Any]:
    """Load a project's memory JSON, or raise 404."""
    if project not in _mm.list_projects():
        raise HTTPException(status_code=404, detail=f"Project '{project}' not found")
    try:
        return _mm.get_project_memory(project)
    except Exception as exc:
        logger.error("market load failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


def _save_memory(project: str, memory: dict[str, Any]) -> None:
    """Persist project memory to disk via MemoryManager (with flock)."""
    try:
        _mm.save_project_memory(project, memory)
    except Exception as exc:
        logger.error("market save failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


def _get_bets(memory: dict[str, Any]) -> list[dict]:
    """Extract the bets list from project memory."""
    return memory.get("market", {}).get("bets", [])


def _set_bets(memory: dict[str, Any], bets: list[dict]) -> None:
    """Store the bets list back into project memory."""
    memory.setdefault("market", {})["bets"] = bets
    memory["last_updated"] = datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@market_router.post("/{project}/market/bet")
async def place_bet(project: str, req: BetPlaceRequest) -> dict[str, Any]:
    """Place a confidence bet on a decision."""
    try:
        memory = _load_memory(project)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("market bet load failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    known_ids = {d.get("id") for d in memory.get("decisions", []) if d.get("id")}
    if req.decision_id not in known_ids:
        raise HTTPException(
            status_code=404,
            detail=f"Decision '{req.decision_id}' not found in project '{project}'",
        )

    bets = _get_bets(memory)
    agent_name = normalize_agent_name(req.agent_name)
    bet_dict = {
        "id": f"bet-{project}-{req.decision_id}-{agent_name}-{len(bets)}",
        "decision_id": req.decision_id,
        "agent_name": agent_name,
        "confidence": req.confidence,
        "category": req.category,
    }

    result = record_bet(bets, bet_dict)
    if isinstance(result, Err):
        raise HTTPException(status_code=422, detail=result.error)

    _set_bets(memory, result.value)
    try:
        _save_memory(project, memory)
    except Exception as exc:
        logger.error("market bet save failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return {"placed": True, "bet": result.value[-1]}


@market_router.post("/{project}/market/resolve")
async def resolve_bet_endpoint(project: str, req: BetResolveRequest) -> dict[str, Any]:
    """Resolve an existing bet with an outcome."""
    try:
        memory = _load_memory(project)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("market resolve load failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    bets = _get_bets(memory)
    target = next((b for b in bets if b.get("id") == req.bet_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail=f"Bet '{req.bet_id}' not found")

    result = resolve_bet(target, req.outcome)
    if isinstance(result, Err):
        raise HTTPException(status_code=422, detail=result.error)

    # Replace the bet in the list (immutable update)
    updated_bets = [result.value if b.get("id") == req.bet_id else b for b in bets]
    _set_bets(memory, updated_bets)
    try:
        _save_memory(project, memory)
    except Exception as exc:
        logger.error("market resolve save failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return {"resolved": True, "bet": result.value}


@market_router.get("/{project}/market/calibration/{agent}")
async def get_calibration(project: str, agent: str) -> CalibrationResponse:
    """Get calibration metrics for a specific agent."""
    agent = normalize_agent_name(agent)
    try:
        memory = _load_memory(project)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("market calibration load failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    bets = _get_bets(memory)
    result = compute_calibration(bets, agent)
    if isinstance(result, Err):
        if result.code == "NOT_FOUND":
            raise HTTPException(status_code=404, detail=result.error)
        raise HTTPException(status_code=422, detail=result.error)

    score: CalibrationScore = result.value
    return CalibrationResponse(
        agent_name=score.agent_name,
        total_bets=score.total_bets,
        correct_bets=score.correct_bets,
        accuracy=score.accuracy,
        category_scores=score.category_scores,
        overconfidence_index=score.overconfidence_index,
    )


@market_router.delete("/{project}/market/clear")
async def clear_market(project: str) -> dict[str, Any]:
    """Clear all decision-market bets for a project. Irreversible."""
    try:
        memory = _load_memory(project)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("market clear load failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    bets_removed = len(_get_bets(memory))
    _set_bets(memory, [])
    try:
        _save_memory(project, memory)
    except Exception as exc:
        logger.error("market clear save failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return {"cleared": True, "bets_removed": bets_removed}


@market_router.get("/{project}/market/leaderboard")
async def get_leaderboard(
    project: str, goal_id: str | None = Query(None, max_length=64),
) -> dict[str, Any]:
    """Get the calibration leaderboard ranked by accuracy.

    goal_id (#44) slices the leaderboard to only bets on decisions linked
    to that goal -- compute_calibration/compute_leaderboard were always
    generic pure functions over whatever bets they're handed (get_goal_
    alignment's own market_calibration already filters this way inline);
    this exposes the same slice as a real, directly-queryable market
    endpoint rather than something only reachable via the goals router's
    own aggregator. Validated at the router boundary (goal must exist),
    matching #41's Decision.goal_id FK check precedent.
    """
    try:
        memory = _load_memory(project)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("market leaderboard load failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    bets = _get_bets(memory)
    if goal_id is not None:
        goal_exists = any(g.get("id") == goal_id for g in memory.get("goals", []))
        if not goal_exists:
            raise HTTPException(status_code=404, detail=f"Goal '{goal_id}' not found")
        linked_ids = {
            d["id"] for d in memory.get("decisions", [])
            if d.get("goal_id") == goal_id and d.get("id")
        }
        bets = [b for b in bets if b.get("decision_id") in linked_ids]

    result = compute_leaderboard(bets)
    if isinstance(result, Err):
        raise HTTPException(status_code=500, detail=result.error)

    entries: list[LeaderboardEntry] = result.value
    return {
        "leaderboard": [
            LeaderboardResponse(
                agent_name=e.agent_name,
                accuracy=e.accuracy,
                total_bets=e.total_bets,
                categories=e.categories,
            )
            for e in entries
        ],
        "count": len(entries),
        "goal_id": goal_id,
    }
