"""
Cost Tracker — tracks actual dollars/tokens spent per decision with
DecisionTree traversal and decay weighting.

Uses dependency injection for testability. IO isolated to
record_cost_event and generate_cost_report. Pure functions for
calculations (get_decision_cost, compute_rework_cost, compute_cost_trend).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from core.cost import (
    CostEvent,
    CostReport,
    CostError,
    DecisionCost,
    ROIScore,
    Ok,
    Err,
    Result,
    compute_event_cost,
    rollup_costs,
    compute_roi,
    _event_tokens,
)
from core.decision_tree import DecisionTree
from core.knowledge_decay import decay_score
from core.memory.manager import MemoryManager


def _now_iso() -> str:
    """Current UTC time as ISO string."""
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# CostTracker class
# ---------------------------------------------------------------------------

class CostTracker:
    """Tracks cost events per decision with tree traversal and decay weighting.

    Dependencies are injected for testability and composability.
    """

    def __init__(
        self,
        decision_tree: DecisionTree,
        decay_fn: Any | None = None,
        memory_manager: MemoryManager | None = None,
    ) -> None:
        self._tree = decision_tree
        self._decay_fn = decay_fn or decay_score
        self._mm = memory_manager or MemoryManager()

    def record_cost_event(self, project: str, event: CostEvent) -> CostEvent:
        """Record a cost event to project memory.

        Validates event, assigns ID if missing, saves to memory.
        Raises CostError on validation or IO failure.
        """
        validated = _validate_event(event)
        event_with_id = _ensure_id(validated)
        memory = self._mm.get_project_memory(project)
        memory.setdefault("cost_events", []).append(_event_to_dict(event_with_id))
        try:
            self._mm.save_project_memory(project, memory)
        except (OSError, ValueError) as exc:
            raise CostError(
                f"Failed to save cost event: {exc}",
                code="IO_ERROR",
                details={"project": project},
            ) from exc
        return event_with_id

    def generate_cost_report(self, project: str) -> CostReport:
        """Generate full cost report for a project.

        Loads events from memory, rolls up per-decision costs,
        computes impact scores and ROI. Raises CostError on failure.
        """
        try:
            memory = self._mm.get_project_memory(project)
        except (OSError, ValueError) as exc:
            raise CostError(
                f"Failed to load project memory: {exc}",
                code="IO_ERROR",
                details={"project": project},
            ) from exc
        events = _load_events(memory)
        decisions = _extract_decisions(memory)
        rolled = _rollup_or_raise(events, decisions)
        impact_map = _compute_impacts(decisions, self._tree, self._decay_fn)
        return _build_report(project, events, rolled, impact_map)

    def trace_decision_cost(self, project: str, decision_id: str) -> dict[str, Any]:
        """Trace cost impact through the decision tree.

        Returns dict with direct_cost, ancestor_costs, descendant_costs.
        Uses DecisionTree.get_ancestors/get_descendants for traversal.
        """
        memory = self._mm.get_project_memory(project)
        events = _load_events(memory)
        direct = get_decision_cost(decision_id, events)
        ancestors = self._tree.get_ancestors(decision_id)
        descendants = self._tree.get_descendants(decision_id)
        return {
            "decision_id": decision_id,
            "direct_cost": direct,
            "ancestor_costs": _sum_tree_costs(ancestors, events),
            "descendant_costs": _sum_tree_costs(descendants, events),
        }

    @staticmethod
    def apply_decay_weighting(
        costs: dict[str, float], decay_scores: dict[str, float],
    ) -> dict[str, float]:
        """Weight costs by decay confidence scores. Pure function."""
        return {
            did: round(cost * decay_scores.get(did, 1.0), 6)
            for did, cost in costs.items()
        }

    def aggregate_project_cost(
        self, project: str, decision_ids: list[str],
    ) -> CostReport:
        """Aggregate costs for specific decisions with rollup and trend."""
        memory = self._mm.get_project_memory(project)
        events = _load_events(memory)
        decisions = _extract_decisions(memory)
        ids_set = set(decision_ids)
        filtered = [e for e in events if e.decision_id in ids_set]
        rolled = _rollup_or_raise(filtered, decisions)
        impact_map = _compute_impacts(decisions, self._tree, self._decay_fn)
        return _build_report(project, filtered, rolled, impact_map)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _validate_event(event: CostEvent) -> CostEvent:
    """Validate event fields; raises CostError on invalid data."""
    if event.amount < 0:
        raise CostError(
            f"Cost amount must be non-negative, got {event.amount}",
            code="VALIDATION_ERROR",
        )
    if not event.event_type:
        raise CostError("event_type is required", code="VALIDATION_ERROR")
    if not event.decision_id:
        raise CostError("decision_id is required", code="VALIDATION_ERROR")
    return event


def _ensure_id(event: CostEvent) -> CostEvent:
    """Assign a generated ID if event.id is empty."""
    if event.id:
        return event
    import hashlib
    raw = f"{event.decision_id}{event.event_type}{event.timestamp}{event.amount}"
    gen_id = hashlib.sha256(raw.encode()).hexdigest()[:12]
    return CostEvent(
        id=gen_id,
        decision_id=event.decision_id,
        event_type=event.event_type,
        amount=event.amount,
        unit=event.unit,
        description=event.description,
        timestamp=event.timestamp,
        metadata=event.metadata,
    )


def _event_to_dict(event: CostEvent) -> dict[str, Any]:
    """Serialize CostEvent to dict for memory storage."""
    return {
        "id": event.id,
        "decision_id": event.decision_id,
        "event_type": event.event_type,
        "amount": event.amount,
        "unit": event.unit,
        "description": event.description,
        "timestamp": event.timestamp,
        "metadata": event.metadata,
    }


def _load_events(memory: dict[str, Any]) -> list[CostEvent]:
    """Deserialize cost events from memory dict."""
    return [CostEvent(**e) for e in memory.get("cost_events", [])]


def _extract_decisions(memory: dict[str, Any]) -> dict[str, str]:
    """Extract decision_id -> decision_text mapping."""
    return {
        d.get("id", ""): d.get("decision", "")
        for d in memory.get("decisions", [])
    }


def _rollup_or_raise(
    events: list[CostEvent], decisions: dict[str, str],
) -> dict[str, DecisionCost]:
    """Roll up costs or raise CostError on failure."""
    result = rollup_costs(events, decisions)
    if isinstance(result, Err):
        raise CostError(result.error, code=result.code)
    return result.value


def _compute_impacts(
    decisions: dict[str, str], tree: DecisionTree, decay_fn: Any,
) -> dict[str, float]:
    """Compute impact scores via decay confidence + descendant bonus."""
    impacts: dict[str, float] = {}
    for did in decisions:
        node = tree.get_decision(did)
        ts = node.get("timestamp", "") if node else ""
        result = decay_fn(ts, reference_count=0, contradiction_count=0)
        base = result.get("score", 0.5) if isinstance(result, dict) else 0.5
        desc_count = len(tree.get_descendants(did, max_depth=3))
        bonus = min(desc_count * 0.1, 0.5)
        impacts[did] = min(base + bonus, 1.0)
    return impacts


def _build_roi_scores(
    rolled: dict[str, DecisionCost], impact_map: dict[str, float],
) -> list[ROIScore]:
    """Compute ROI for each rolled-up decision cost."""
    scores = []
    for did, dc in rolled.items():
        roi = compute_roi(dc, impact_map.get(did, 0.5))
        if isinstance(roi, Ok):
            scores.append(roi.value)
    return scores


def _build_report(
    project: str,
    events: list[CostEvent],
    rolled: dict[str, DecisionCost],
    impact_map: dict[str, float],
) -> CostReport:
    """Assemble a CostReport from rolled-up data."""
    return CostReport(
        project=project,
        total_cost_usd=sum(dc.total_cost_usd for dc in rolled.values()),
        total_tokens=sum(dc.total_tokens for dc in rolled.values()),
        cost_per_decision=list(rolled.values()),
        rework_costs=compute_rework_cost(events),
        roi_scores=_build_roi_scores(rolled, impact_map),
        period=_compute_period(events),
    )


def _sum_tree_costs(
    entries: list[dict], events: list[CostEvent],
) -> dict[str, float]:
    """Sum costs for decisions found in tree traversal results."""
    result: dict[str, float] = {}
    for entry in entries:
        node = entry.get("decision", {})
        did = node.get("id", "")
        if did and did not in result:
            result[did] = get_decision_cost(did, events).total_cost_usd
    return result


def _compute_period(events: list[CostEvent]) -> str:
    """Compute the time period covered by cost events."""
    if not events:
        return "no events"
    timestamps = sorted(e.timestamp for e in events)
    return f"{timestamps[0]} to {timestamps[-1]}"


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------

def get_decision_cost(decision_id: str, events: list[CostEvent]) -> DecisionCost:
    """Filter events by decision_id and roll up costs. Pure function."""
    filtered = [e for e in events if e.decision_id == decision_id]
    total_usd = 0.0
    total_tokens = 0
    rework_usd = 0.0
    for ev in filtered:
        cost = compute_event_cost(ev)
        if isinstance(cost, Ok):
            total_usd += cost.value
            total_tokens += _event_tokens(ev)
            if ev.event_type == "rework":
                rework_usd += cost.value
    return DecisionCost(
        decision_id=decision_id,
        decision_text="",
        total_cost_usd=round(total_usd, 6),
        total_tokens=total_tokens,
        event_count=len(filtered),
        reversal_cost=round(rework_usd, 6),
    )


def compute_rework_cost(events: list[CostEvent]) -> float:
    """Sum costs of rework events. Pure function."""
    total = 0.0
    for ev in events:
        if ev.event_type == "rework":
            cost = compute_event_cost(ev)
            if isinstance(cost, Ok):
                total += cost.value
    return round(total, 6)


def compute_cost_trend(
    events: list[CostEvent], window_days: int = 30,
) -> list[dict[str, Any]]:
    """Group events by day, compute daily cost totals. Pure function."""
    daily: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"total_cost": 0.0, "event_count": 0}
    )
    for ev in events:
        day = ev.timestamp[:10]
        cost = compute_event_cost(ev)
        value = cost.value if isinstance(cost, Ok) else 0.0
        daily[day]["total_cost"] += value
        daily[day]["event_count"] += 1
    return [
        {
            "date": d,
            "total_cost": round(v["total_cost"], 6),
            "event_count": v["event_count"],
        }
        for d, v in sorted(daily.items())
    ]


# ---------------------------------------------------------------------------
# Real LLM usage -> cost event (feeds the ledger from actual API calls)
# ---------------------------------------------------------------------------

# $/token, split by input vs output where the provider prices them
# differently. Update these if OpenAI changes pricing.
_MODEL_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o-mini": {"input": 0.15e-6, "output": 0.60e-6},
    "text-embedding-3-small": {"input": 0.02e-6, "output": 0.0},
}


def record_llm_cost(
    project: str,
    prompt_tokens: int,
    completion_tokens: int,
    model: str,
    description: str = "",
    decision_id: str = "_general",
) -> Result[CostEvent]:
    """Record a real OpenAI usage event as accurately-priced cost.

    Computes actual USD from the model's real per-token pricing (not the
    flat generic token_usage rate), so this is real spend, not an estimate.
    decision_id defaults to "_general" for calls not tied to a specific
    decision (the common case: compression, embeddings) -- still rolls up
    into real project totals. Never raises; returns Err on failure so
    callers can no-op rather than letting cost tracking break a real LLM
    call.
    """
    pricing = _MODEL_PRICING.get(model)
    if pricing is None:
        return Err(
            error=f"No pricing known for model {model!r}",
            code="UNKNOWN_MODEL",
            details={"known_models": list(_MODEL_PRICING)},
        )
    total_tokens = prompt_tokens + completion_tokens
    amount_usd = (
        prompt_tokens * pricing["input"] + completion_tokens * pricing["output"]
    )
    event = CostEvent(
        id="",
        decision_id=decision_id,
        event_type="llm_usage",
        amount=round(amount_usd, 8),
        unit="usd",
        description=description,
        timestamp=_now_iso(),
        metadata={
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        },
    )
    tracker = CostTracker(DecisionTree())
    try:
        recorded = tracker.record_cost_event(project, event)
    except CostError as exc:
        return Err(error=str(exc), code=exc.code, details=exc.details)
    except ValueError as exc:
        # record_cost_event's call to get_project_memory() runs before its
        # own try/except (which only wraps the save), so an invalid project
        # name (or a corrupt memory file -- json.JSONDecodeError is a
        # ValueError subclass) surfaces here instead of as a CostError.
        return Err(error=str(exc), code="VALIDATION_ERROR", details={"project": project})
    except OSError as exc:
        return Err(error=str(exc), code="IO_ERROR", details={"project": project})
    return Ok(value=recorded)
