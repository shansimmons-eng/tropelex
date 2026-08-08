"""
Goal drift detection — two independent, pure-function signals.

1. Semantic drift: does a decision's text still overlap with the goal it's
   linked to? Reuses the Jaccard keyword-overlap technique core/ghost/
   pattern_matcher.py already uses for decision-vs-diff-hunk matching,
   applied here to goal-text-vs-decision-text instead. The sense is
   inverted from Ghost Decisions: there, high overlap is the bad case
   (code silently contradicts a decision); here, LOW overlap is the bad
   case (a decision has drifted away from the goal it's supposed to serve).

2. Trend drift: baseline-vs-recent comparison of risk_level and review
   rate across a set of decisions. Extracted from what was previously
   inline logic in core/tropebook/web/server.py's get_alignment_drift
   endpoint (behavior-preserving — same inputs, same outputs), so it can
   be reused both for the whole project (as before) and scoped to a
   single goal's linked decisions (new).

No ML/embeddings — stdlib-only, matching this project's PEP 668
dependency-averse constraint and Ghost Decisions' own approach.
"""

from __future__ import annotations

from core.ghost.pattern_matcher import extract_keywords

# ---------------------------------------------------------------------------
# Semantic drift — goal text vs. linked decision text
# ---------------------------------------------------------------------------

# Below this overlap, a decision has drifted badly from its goal's text.
_DRIFT_HIGH = 0.15
# At or above this overlap, a decision is considered well-aligned.
_DRIFT_LOW = 0.35


def score_goal_decision_overlap(goal_text: str, decision_text: str) -> float:
    """Jaccard keyword overlap between a goal's text and one decision's text."""
    goal_kw = extract_keywords(goal_text)
    decision_kw = extract_keywords(decision_text)
    if not goal_kw or not decision_kw:
        return 0.0
    union = goal_kw | decision_kw
    if not union:
        return 0.0
    return round(len(goal_kw & decision_kw) / len(union), 4)


def _classify_drift_severity(overlap_score: float) -> str:
    if overlap_score < _DRIFT_HIGH:
        return "high"
    if overlap_score >= _DRIFT_LOW:
        return "low"
    return "medium"


def _drift_recommendation(severity: str) -> str:
    if severity == "high":
        return (
            "Linked decisions barely reference this goal's stated text — "
            "reconsider whether the goal is still the right target, or "
            "whether these decisions actually serve it."
        )
    if severity == "medium":
        return (
            "Some overlap with the goal's stated text, but it's thin — "
            "worth a check that decisions are still tracking the goal."
        )
    return "Linked decisions' language still tracks the goal's stated text."


def score_goal_drift(goal_text: str, linked_decisions: list[dict]) -> dict:
    """Aggregate semantic drift across a goal's linked decisions.

    Aggregated via worst-case (min), not mean — a single badly-drifted
    decision surfaces immediately rather than being diluted by several
    aligned ones, matching this project's "surface friction, don't smooth
    it over" pattern (the tag-required gate, the always-visible Needs
    Attention panel).
    """
    if not linked_decisions:
        return {
            "drift_detected": False,
            "message": "No decisions linked to this goal yet",
            "overlap_score": None,
            "severity": None,
            "recommendation": None,
            "per_decision": [],
        }

    per_decision = [
        {"decision_id": d.get("id"), "overlap_score": score_goal_decision_overlap(goal_text, d.get("decision", ""))}
        for d in linked_decisions
    ]
    worst = min(p["overlap_score"] for p in per_decision)
    severity = _classify_drift_severity(worst)

    return {
        "drift_detected": severity in ("medium", "high"),
        "overlap_score": worst,
        "severity": severity,
        "recommendation": _drift_recommendation(severity),
        "per_decision": per_decision,
    }


# ---------------------------------------------------------------------------
# Trend drift — baseline-vs-recent risk/review-rate comparison
# ---------------------------------------------------------------------------

_RISK_WEIGHTS = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_RISK_DRIFT_THRESHOLD = 0.5
_REVIEW_DRIFT_THRESHOLD = 0.3


def score_trend_drift(decisions: list[dict], window: int = 10) -> dict:
    """Compare a baseline of older decisions against the most recent
    `window` decisions on two metrics: average risk level, and review
    rate. Extracted, behavior-preserving, from what was previously inline
    in get_alignment_drift (core/tropebook/web/server.py) — same
    computation, same output shape, minus the "project" key, which is
    router-level context, not something a pure function should carry.
    """
    if len(decisions) < window * 2:
        return {
            "drift_detected": False,
            "message": "Not enough decisions for drift detection",
            "total_decisions": len(decisions),
        }

    baseline = decisions[: len(decisions) - window]
    recent = decisions[-window:]

    baseline_risk = sum(_RISK_WEIGHTS.get(d.get("safety_metadata", {}).get("risk_level", "low"), 0) for d in baseline) / len(baseline)
    recent_risk = sum(_RISK_WEIGHTS.get(d.get("safety_metadata", {}).get("risk_level", "low"), 0) for d in recent) / len(recent)

    baseline_reviewed = sum(1 for d in baseline if d.get("safety_reviews")) / len(baseline)
    recent_reviewed = sum(1 for d in recent if d.get("safety_reviews")) / len(recent)

    risk_drift = recent_risk - baseline_risk
    review_drift = recent_reviewed - baseline_reviewed

    drift_detected = abs(risk_drift) > _RISK_DRIFT_THRESHOLD or abs(review_drift) > _REVIEW_DRIFT_THRESHOLD

    drift_indicators = []
    if risk_drift > _RISK_DRIFT_THRESHOLD:
        drift_indicators.append({"metric": "risk_level", "direction": "increasing", "change": round(risk_drift, 3)})
    elif risk_drift < -_RISK_DRIFT_THRESHOLD:
        drift_indicators.append({"metric": "risk_level", "direction": "decreasing", "change": round(risk_drift, 3)})

    if review_drift > _REVIEW_DRIFT_THRESHOLD:
        drift_indicators.append({"metric": "review_rate", "direction": "increasing", "change": round(review_drift, 3)})
    elif review_drift < -_REVIEW_DRIFT_THRESHOLD:
        drift_indicators.append({"metric": "review_rate", "direction": "decreasing", "change": round(review_drift, 3)})

    return {
        "drift_detected": drift_detected,
        "baseline_size": len(baseline),
        "recent_size": len(recent),
        "metrics": {
            "baseline_avg_risk": round(baseline_risk, 3),
            "recent_avg_risk": round(recent_risk, 3),
            "risk_drift": round(risk_drift, 3),
            "baseline_review_rate": round(baseline_reviewed, 3),
            "recent_review_rate": round(recent_reviewed, 3),
            "review_drift": round(review_drift, 3),
        },
        "drift_indicators": drift_indicators,
    }
