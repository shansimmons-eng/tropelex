"""
Tropelex Cost Ledger — data models, domain exceptions, and pure cost functions.

Tracks actual dollars/tokens spent per decision. Records cost events
(agent time, API calls, rework, token usage), rolls up into per-decision
reports, and computes ROI scores.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar, Union


# ---------------------------------------------------------------------------
# Result type (matches project convention from core/friction/miner.py)
# ---------------------------------------------------------------------------

T = TypeVar("T")


@dataclass(frozen=True)
class Ok(Generic[T]):
    """Success wrapper — carries the resulting value."""
    value: T


@dataclass(frozen=True)
class Err:
    """Error wrapper — carries an error message and code."""
    error: str
    code: str = "UNKNOWN"
    details: dict[str, Any] | None = None


Result = Union[Ok[T], Err]


# ---------------------------------------------------------------------------
# Domain exceptions (IO boundary only — business logic returns Result)
# ---------------------------------------------------------------------------

class TropelexError(Exception):
    """Base for all Tropelex errors."""

    def __init__(
        self,
        message: str,
        code: str = "UNKNOWN",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class CostError(TropelexError):
    """Base for all cost ledger errors."""

    def __init__(
        self,
        message: str,
        code: str = "COST_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code=code, details=details)


class ValidationError(TropelexError):
    """Invalid input passed to a cost function."""

    def __init__(
        self,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code="VALIDATION_ERROR", details=details)


# ---------------------------------------------------------------------------
# Data models (frozen dataclasses — immutable)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CostEvent:
    """A single cost event tied to a decision."""

    id: str
    decision_id: str
    event_type: str  # agent_time | api_call | rework | token_usage
    amount: float
    unit: str  # "usd" | "tokens" | "seconds"
    description: str
    timestamp: str  # ISO 8601 string
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DecisionCost:
    """Aggregated cost breakdown for a single decision."""

    decision_id: str
    decision_text: str
    total_cost_usd: float
    total_tokens: int
    event_count: int
    reversal_cost: float


@dataclass(frozen=True)
class ROIScore:
    """Return-on-investment score for a decision."""

    decision_id: str
    cost: float
    impact_score: float
    roi: float = 0.0  # impact / cost if cost > 0 else 0.0


@dataclass(frozen=True)
class CostReport:
    """Full cost report for a project."""

    project: str
    total_cost_usd: float
    total_tokens: int
    cost_per_decision: list[DecisionCost]
    rework_costs: float
    roi_scores: list[ROIScore]
    period: str


# ---------------------------------------------------------------------------
# Pure functions — cost computation
# ---------------------------------------------------------------------------

# Conversion rates: event_amount → USD equivalent
_RATES: dict[str, float] = {
    "agent_time": 0.002,      # rough $/second for LLM agent
    "api_call": 0.01,         # rough $/call
    "rework": 0.05,           # rough $/rework event
    "token_usage": 0.000002,  # rough $/token for GPT-4 class
}


def compute_event_cost(event: CostEvent) -> Result[float]:
    """Normalize any cost event to its USD equivalent.

    Returns:
        Ok(float) with the USD cost, or Err if event_type is unknown.
    """
    rate = _RATES.get(event.event_type)
    if rate is None:
        return Err(
            error=f"Unknown event_type: {event.event_type!r}",
            code="VALIDATION_ERROR",
            details={"valid_types": list(_RATES.keys())},
        )
    if event.amount < 0:
        return Err(
            error=f"Cost amount must be non-negative, got {event.amount}",
            code="VALIDATION_ERROR",
        )
    return Ok(value=event.amount * rate)


def _event_tokens(event: CostEvent) -> int:
    """Extract token count from a token_usage event, else 0."""
    if event.event_type == "token_usage" and event.unit == "tokens":
        return int(event.amount)
    return 0


def _is_reversal(event: CostEvent) -> bool:
    """Check if a cost event is a reversal/rework cost."""
    return event.event_type == "rework"


def rollup_costs(
    events: list[CostEvent],
    decisions: dict[str, str] | None = None,
) -> Result[dict[str, DecisionCost]]:
    """Group events by decision_id and sum costs into DecisionCost objects.

    Args:
        events: All cost events for the project.
        decisions: Optional mapping of decision_id → decision_text.

    Returns:
        Ok(dict) mapping decision_id → DecisionCost.
    """
    if not events:
        return Ok(value={})

    decisions = decisions or {}
    buckets: dict[str, list[CostEvent]] = {}
    for ev in events:
        buckets.setdefault(ev.decision_id, []).append(ev)

    result: dict[str, DecisionCost] = {}
    for did, evts in buckets.items():
        total_usd = 0.0
        total_tokens = 0
        rework_usd = 0.0

        for ev in evts:
            cost_result = compute_event_cost(ev)
            if isinstance(cost_result, Err):
                return cost_result
            total_usd += cost_result.value
            total_tokens += _event_tokens(ev)
            if _is_reversal(ev):
                rework_usd += cost_result.value

        result[did] = DecisionCost(
            decision_id=did,
            decision_text=decisions.get(did, ""),
            total_cost_usd=round(total_usd, 6),
            total_tokens=total_tokens,
            event_count=len(evts),
            reversal_cost=round(rework_usd, 6),
        )

    return Ok(value=result)


def compute_roi(
    decision_cost: DecisionCost,
    impact_score: float,
) -> Result[ROIScore]:
    """Compute ROI score for a single decision.

    ROI = impact_score / cost if cost > 0 else 0.0.

    Returns:
        Ok(ROIScore) or Err if cost is negative.
    """
    if decision_cost.total_cost_usd < 0:
        return Err(
            error="Decision cost must be non-negative",
            code="VALIDATION_ERROR",
            details={"cost": decision_cost.total_cost_usd},
        )
    if impact_score < 0:
        return Err(
            error="Impact score must be non-negative",
            code="VALIDATION_ERROR",
            details={"impact_score": impact_score},
        )

    roi = (
        impact_score / decision_cost.total_cost_usd
        if decision_cost.total_cost_usd > 0
        else 0.0
    )

    return Ok(value=ROIScore(
        decision_id=decision_cost.decision_id,
        cost=decision_cost.total_cost_usd,
        impact_score=impact_score,
        roi=round(roi, 6),
    ))
