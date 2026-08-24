"""
Per-agent cumulative safety budget (wishlist #73-4).

A running risk-score total across an agent's actions in a project --
overrides used, gate blocks/warnings hit, high-risk decisions captured --
that can itself trigger a review once it crosses a threshold. Same
"make the invisible cumulative thing visible" instinct behind Session-Shape
Baselining (#45) and Decay (#58), applied to risk exposure instead of
behavioral drift or staleness.

Scope, deliberately limited to what's genuinely agent-attributed: overrides
(core/gate.py's mechanism) always carried agent_name. gate_blocked/
gate_warned (core/ghost/preventive_router.py, add_decision's contradiction
gate) and decision capture (DecisionCreate) did NOT carry agent_name at all
until this feature added it as an additive optional field -- so a budget
computed today only reflects gate/decision activity from this point
forward, same disclosed-gap precedent core/prevention_report.py already
set for its own historical read. contradiction_escalated is excluded
entirely: it fires from a project-wide GET /contradictions scan, not an
agent action, so there is no agent to attribute it to.

Pure functions, no I/O -- same shape as core/prevention_report.py.
"""

from __future__ import annotations

from typing import Any

# Weights are simple, documented starting points, not a learned/tuned
# model -- same stance #67's own negative result argues for (an untuned
# signal presented as authoritative is worse than an honestly-approximate
# one). "block" outweighs "warn" since a block is what an agent actually
# had to act on (fix the diff or explicitly override); "warn" alone means
# the agent proceeded without the gate stopping them at all.
OVERRIDE_WEIGHT = 2.0
_GATE_BLOCKED_SEVERITY_WEIGHTS = {"high": 3.0, "medium": 2.0, "low": 1.0}
_GATE_WARNED_SEVERITY_WEIGHTS = {"high": 1.5, "medium": 1.0, "low": 0.5}
_HIGH_RISK_DECISION_WEIGHT = 2.0
_MEDIUM_RISK_DECISION_WEIGHT = 0.5

DEFAULT_THRESHOLD = 10.0


def _severity_score(severity_counts: Any, weights: dict[str, float]) -> float:
    if not isinstance(severity_counts, dict):
        return 0.0
    return sum(weights.get(sev, 0.0) * _safe_int(n) for sev, n in severity_counts.items())


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def compute_safety_budget(memory: dict[str, Any], agent: str, threshold: float = DEFAULT_THRESHOLD) -> dict[str, Any]:
    """Sum weighted risk-relevant events attributed to `agent` in this
    project's memory. Events without agent attribution (historical gate
    events, decisions captured before this feature) are simply invisible
    to this per-agent view -- they don't count toward anyone specifically,
    which is honest rather than silently miscounted toward the wrong agent.
    """
    audit_log = memory.get("audit_log", []) or []
    decisions = memory.get("decisions", []) or []

    override_count = sum(
        1 for e in audit_log
        if isinstance(e, dict) and e.get("event_type") == "override" and e.get("agent_name") == agent
    )
    override_score = override_count * OVERRIDE_WEIGHT

    gate_blocked_events = [
        e for e in audit_log
        if isinstance(e, dict) and e.get("event_type") == "gate_blocked" and e.get("agent_name") == agent
    ]
    gate_blocked_score = sum(
        _severity_score(e.get("severity_counts"), _GATE_BLOCKED_SEVERITY_WEIGHTS) for e in gate_blocked_events
    )

    gate_warned_events = [
        e for e in audit_log
        if isinstance(e, dict) and e.get("event_type") == "gate_warned" and e.get("agent_name") == agent
    ]
    gate_warned_score = sum(
        _severity_score(e.get("severity_counts"), _GATE_WARNED_SEVERITY_WEIGHTS) for e in gate_warned_events
    )

    high_risk_count = 0
    medium_risk_count = 0
    for d in decisions:
        if not isinstance(d, dict) or d.get("agent_name") != agent:
            continue
        risk_level = (d.get("safety_metadata") or {}).get("risk_level", "low")
        if risk_level == "high":
            high_risk_count += 1
        elif risk_level == "medium":
            medium_risk_count += 1
    decision_score = high_risk_count * _HIGH_RISK_DECISION_WEIGHT + medium_risk_count * _MEDIUM_RISK_DECISION_WEIGHT

    total = round(override_score + gate_blocked_score + gate_warned_score + decision_score, 3)

    return {
        "agent_name": agent,
        "score": total,
        "threshold": threshold,
        "over_threshold": total >= threshold,
        "breakdown": {
            "overrides": {"count": override_count, "score": override_score},
            "gate_blocked": {"count": len(gate_blocked_events), "score": round(gate_blocked_score, 3)},
            "gate_warned": {"count": len(gate_warned_events), "score": round(gate_warned_score, 3)},
            "high_risk_decisions": {"count": high_risk_count, "score": high_risk_count * _HIGH_RISK_DECISION_WEIGHT},
            "medium_risk_decisions": {
                "count": medium_risk_count, "score": medium_risk_count * _MEDIUM_RISK_DECISION_WEIGHT,
            },
        },
    }


def most_recent_eligible_decision(decisions: list[dict[str, Any]], agent: str) -> dict[str, Any] | None:
    """The agent's most recent decision that isn't already flagged for
    review and hasn't already been through a review -- the escalation
    target when a safety budget crosses its threshold. Same "respect an
    existing human resolution" rule core/tropebook/web/server.py's
    _apply_persona_market_escalation and core/contradictions/router.py's
    _escalate_to_review both already apply, so this doesn't undo an
    approval just because the cumulative score is still high.
    """
    eligible = [
        d for d in decisions
        if isinstance(d, dict)
        and d.get("agent_name") == agent
        and not (d.get("safety_metadata") or {}).get("requires_review")
        and not d.get("safety_reviews")
    ]
    if not eligible:
        return None
    return max(eligible, key=lambda d: d.get("timestamp", ""))
