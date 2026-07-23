"""
Decision Market — calibration scoring pure functions.

Pure, side-effect-free functions that compute accuracy, calibration,
and leaderboard rankings from a list of confidence bets.

All functions return Result[Ok, Err] and produce immutable outputs.
Same input → same output, always.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from core.market import (
    CalibrationScore,
    Err,
    LeaderboardEntry,
    Ok,
    Result,
)


def record_bet(bets: list[dict], bet: dict) -> Result[list[dict]]:
    """Append a bet to the list, returning a new list (immutable).

    Validates required fields before adding.
    """
    required = {"id", "decision_id", "agent_name", "confidence", "category"}
    missing = required - set(bet.keys())
    if missing:
        return Err(
            error=f"Bet missing fields: {', '.join(sorted(missing))}",
            code="VALIDATION_ERROR",
        )
    confidence = bet["confidence"]
    if not isinstance(confidence, (int, float)) or not 0.0 <= confidence <= 1.0:
        return Err(
            error=f"Confidence must be 0.0–1.0, got {confidence}",
            code="VALIDATION_ERROR",
        )
    enriched = {
        **bet,
        "placed_at": bet.get("placed_at", datetime.now(timezone.utc).isoformat()),
        "resolved": False,
        "outcome": None,
    }
    return Ok(value=[*bets, enriched])


def resolve_bet(bet: dict, outcome: str) -> Result[dict]:
    """Mark a single bet as resolved with the given outcome.

    Returns a new dict — never mutates the original.
    """
    if outcome not in ("correct", "incorrect"):
        return Err(
            error=f"Outcome must be 'correct' or 'incorrect', got '{outcome}'",
            code="VALIDATION_ERROR",
        )
    if bet.get("resolved"):
        return Err(
            error=f"Bet '{bet.get('id')}' is already resolved",
            code="VALIDATION_ERROR",
        )
    return Ok(value={**bet, "resolved": True, "outcome": outcome})


def compute_calibration(bets: list[dict], agent: str) -> Result[CalibrationScore]:
    """Compute calibration metrics for a single agent's resolved bets.

    Returns accuracy, per-category scores, and an overconfidence index.
    """
    agent_bets = [b for b in bets if b.get("agent_name") == agent and b.get("resolved")]
    if not agent_bets:
        return Err(
            error=f"No resolved bets found for agent '{agent}'",
            code="NOT_FOUND",
        )

    correct = sum(1 for b in agent_bets if b.get("outcome") == "correct")
    total = len(agent_bets)
    accuracy = round(correct / total, 3) if total else 0.0

    # Per-category accuracy
    cat_correct: dict[str, int] = defaultdict(int)
    cat_total: dict[str, int] = defaultdict(int)
    for b in agent_bets:
        cat = b.get("category", "uncategorized")
        cat_total[cat] += 1
        if b.get("outcome") == "correct":
            cat_correct[cat] += 1
    category_scores = {
        cat: round(cat_correct[cat] / cat_total[cat], 3)
        for cat in cat_total
    }

    # Overconfidence index: avg confidence on incorrect bets minus avg on correct
    correct_confs = [b["confidence"] for b in agent_bets if b["outcome"] == "correct"]
    incorrect_confs = [b["confidence"] for b in agent_bets if b["outcome"] == "incorrect"]
    avg_correct = sum(correct_confs) / len(correct_confs) if correct_confs else 0.0
    avg_incorrect = sum(incorrect_confs) / len(incorrect_confs) if incorrect_confs else 0.0
    overconfidence = round(avg_incorrect - avg_correct, 3)

    return Ok(value=CalibrationScore(
        agent_name=agent,
        total_bets=total,
        correct_bets=correct,
        accuracy=accuracy,
        category_scores=category_scores,
        overconfidence_index=overconfidence,
    ))


def compute_leaderboard(bets: list[dict]) -> Result[list[LeaderboardEntry]]:
    """Rank all agents by accuracy over their bets.

    Shows all agents who have placed bets. Accuracy is computed only
    from resolved bets; agents with only pending bets show accuracy=0.
    """
    agents: dict[str, list[dict]] = defaultdict(list)
    for b in bets:
        agents[b["agent_name"]].append(b)

    if not agents:
        return Ok(value=[])

    entries: list[LeaderboardEntry] = []
    for agent, agent_bets in agents.items():
        resolved = [b for b in agent_bets if b.get("resolved")]
        if resolved:
            correct = sum(1 for b in resolved if b.get("outcome") == "correct")
            total = len(resolved)
            accuracy = round(correct / total, 3) if total else 0.0
        else:
            accuracy = 0.0
        categories = sorted({b.get("category", "uncategorized") for b in agent_bets})
        entries.append(LeaderboardEntry(
            agent_name=agent,
            accuracy=accuracy,
            total_bets=len(agent_bets),
            categories=categories,
        ))

    entries.sort(key=lambda e: (-e.accuracy, -e.total_bets))
    return Ok(value=entries)
