"""
Tropelex Knowledge Decay & Confidence
Time-based reliability scoring for decisions and citations.

Confidence = f(recency, frequency, contradictions, source_reliability)
Decay = exponential based on age, boosted by re-references
"""

import logging
import math
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("tropelex.knowledge_decay")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(ts: str) -> datetime | None:
    """Parse an ISO timestamp string."""
    if not ts:
        return None
    try:
        ts = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError) as exc:
        logger.warning("Failed to parse timestamp %r: %s", ts, exc)
        return None


def _days_since(dt: datetime | None) -> float:
    """Days since a datetime, or infinity if None."""
    if dt is None:
        return float("inf")
    delta = _now() - dt
    return max(delta.total_seconds() / 86400, 0)


def decay_score(
    timestamp: str,
    half_life_days: float = 90,
    reference_count: int = 0,
    contradiction_count: int = 0,
) -> dict[str, Any]:
    """
    Calculate a decayed confidence score for a decision/citation.

    Args:
        timestamp: ISO timestamp of when the decision was made
        half_life_days: Days until confidence drops to 50% (default: 90)
        reference_count: How many times this has been referenced/used
        contradiction_count: How many times this has been contradicted

    Returns:
        {score, tier, days_old, factors}
    """
    dt = _parse_timestamp(timestamp)
    days = _days_since(dt)

    # Base exponential decay
    decay_rate = math.log(2) / half_life_days
    base_score = math.exp(-decay_rate * days)

    # Boost from re-references (logarithmic, caps at 2x)
    ref_boost = min(math.log2(max(reference_count, 1) + 1) * 0.15, 0.5)

    # Penalty from contradictions (each contradiction halves confidence)
    contra_penalty = 1.0 / (2 ** contradiction_count)

    # Combined score (0.0 to 1.0)
    raw_score = (base_score + ref_boost) * contra_penalty
    score = max(0.0, min(1.0, raw_score))

    # Tier classification
    if score >= 0.8:
        tier = "high"
    elif score >= 0.5:
        tier = "medium"
    elif score >= 0.2:
        tier = "low"
    else:
        tier = "stale"

    # Factor breakdown
    factors = {
        "recency": round(base_score, 3),
        "reference_boost": round(ref_boost, 3),
        "contraction_penalty": round(contra_penalty, 3),
        "days_old": round(days, 1),
        "half_life_days": half_life_days,
    }

    return {
        "score": round(score, 3),
        "tier": tier,
        "days_old": round(days, 1),
        "factors": factors,
    }


def score_decision(decision: dict, all_decisions: list[dict] | None = None) -> dict[str, Any]:
    """
    Score a single decision, considering its relationships.

    Counts:
    - How many other decisions reference the same topics
    - How many times it's been contradicted (reverted/superseded)
    """
    timestamp = decision.get("timestamp", "")
    text = decision.get("decision", "").lower()

    # Count references: other decisions that share significant words
    ref_count = 0
    contra_count = 0

    if all_decisions:
        my_words = set(text.split()) - {"the", "a", "to", "and", "of", "in", "for", "is"}
        for other in all_decisions:
            if other is decision:
                continue
            other_text = other.get("decision", "").lower()
            other_words = set(other_text.split()) - {"the", "a", "to", "and", "of", "in", "for", "is"}
            overlap = len(my_words & other_words)
            if overlap >= 2:
                ref_count += 1
            # Check for contradictions
            if any(kw in other_text for kw in ["revert", "undo", "removed", "superseded"]):
                if overlap >= 2:
                    contra_count += 1

    result = decay_score(
        timestamp,
        reference_count=ref_count,
        contradiction_count=contra_count,
    )

    result["reference_count"] = ref_count
    result["contradiction_count"] = contra_count
    result["decision"] = decision.get("decision", "")[:100]

    return result


def score_decisions(decisions: list[dict]) -> list[dict[str, Any]]:
    """Score all decisions in a list, sorted by confidence."""
    scored = [score_decision(d, decisions) for d in decisions]
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


def get_stale_decisions(
    decisions: list[dict],
    threshold: float = 0.3,
    max_age_days: float = 180,
) -> list[dict[str, Any]]:
    """
    Find decisions that are stale (low confidence or old).
    Returns decisions with their scores, filtered by threshold.
    """
    stale = []
    for d in decisions:
        s = score_decision(d, decisions)
        if s["score"] < threshold or s["days_old"] > max_age_days:
            stale.append({**d, "confidence": s})

    stale.sort(key=lambda x: x["confidence"]["score"])
    return stale


def score_citation(citation: dict) -> dict[str, Any]:
    """
    Score a citation's reliability.
    Citations decay faster than decisions (default 60-day half-life).
    """
    timestamp = citation.get("created_at") or citation.get("timestamp", "")

    result = decay_score(
        timestamp,
        half_life_days=60,  # citations decay faster
        reference_count=citation.get("reference_count", 0),
        contradiction_count=0,
    )

    result["title"] = citation.get("title", "")[:80]
    result["url"] = citation.get("url", "")

    return result


def get_confidence_summary(memory: dict) -> dict[str, Any]:
    """
    Generate a confidence summary for a project's memory.
    """
    decisions = memory.get("decisions", [])
    scored = score_decisions(decisions)

    if not scored:
        return {
            "total": 0,
            "average_confidence": 0,
            "by_tier": {"high": 0, "medium": 0, "low": 0, "stale": 0},
            "stale_count": 0,
        }

    by_tier: dict[str, int] = {"high": 0, "medium": 0, "low": 0, "stale": 0}
    for s in scored:
        by_tier[s["tier"]] = by_tier.get(s["tier"], 0) + 1

    avg = sum(s["score"] for s in scored) / len(scored)
    stale_count = by_tier.get("stale", 0) + by_tier.get("low", 0)

    return {
        "total": len(scored),
        "average_confidence": round(avg, 3),
        "by_tier": by_tier,
        "stale_count": stale_count,
        "most_confident": scored[0] if scored else None,
        "least_confident": scored[-1] if scored else None,
    }


def apply_decay_to_memory(memory: dict) -> dict:
    """
    Enrich memory with confidence scores on each decision.
    Returns the modified memory dict.
    """
    decisions = memory.get("decisions", [])
    for d in decisions:
        d["confidence"] = score_decision(d, decisions)

    memory["confidence_summary"] = get_confidence_summary(memory)
    return memory
