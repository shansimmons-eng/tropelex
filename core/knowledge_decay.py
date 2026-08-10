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

# Pinned decisions stay exempt from decay only while re-attested within this
# window (wishlist #58) -- exemption is not permanent, it requires periodic
# deliberate re-affirmation. Matches get_stale_decisions' existing
# max_age_days=180 as the project's established "long staleness window".
REATTESTATION_PERIOD_DAYS = 180


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
    pinned: bool = False,
    last_attested: str | None = None,
) -> dict[str, Any]:
    """
    Calculate a decayed confidence score for a decision/citation.

    Args:
        timestamp: ISO timestamp of when the decision was made
        half_life_days: Days until confidence drops to 50% (default: 90)
        reference_count: How many times this has been referenced/used
        contradiction_count: How many times this has been contradicted
        pinned: "Constitutional" decision (#58) -- exempt from decay while
            its re-attestation hasn't lapsed. Not a permanent exemption: if
            `last_attested` is missing or older than
            REATTESTATION_PERIOD_DAYS, this falls through to normal decay
            instead of staying silently pinned.
        last_attested: ISO timestamp of the most recent re-attestation.

    Returns:
        {score, tier, days_old, factors}
    """
    dt = _parse_timestamp(timestamp)
    days = _days_since(dt)

    if pinned:
        attested_days = _days_since(_parse_timestamp(last_attested) if last_attested else None)
        if attested_days <= REATTESTATION_PERIOD_DAYS:
            return {
                "score": 1.0,
                "tier": "high",
                "days_old": round(days, 1),
                "factors": {
                    "pinned": True,
                    "days_since_attestation": round(attested_days, 1),
                    "days_old": round(days, 1),
                    "half_life_days": half_life_days,
                },
            }
        # Pinned but never attested, or attestation lapsed -- fail open
        # toward real decay rather than staying exempt indefinitely.

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
    if pinned:
        # Reached only when the pin exists but attestation lapsed (the
        # early-return above handles the still-valid case) -- surface the
        # lapse instead of silently reverting to unpinned behavior.
        factors["pinned"] = True
        factors["pin_expired"] = True

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
        my_id = decision.get("id")
        my_words = set(text.split()) - {"the", "a", "to", "and", "of", "in", "for", "is"}
        for other in all_decisions:
            if not isinstance(other, dict):
                # Defensive against corrupted storage in the caller's
                # decisions list -- a non-dict entry has no .get().
                continue
            if other is decision or (my_id is not None and other.get("id") == my_id):
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
        pinned=decision.get("pinned", False),
        last_attested=decision.get("last_attested"),
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


def compute_inherited_discount(
    decision_id: str, tree: Any, score_by_id: dict[str, float], max_depth: int = 5
) -> float:
    """How much a decision's confidence should be discounted by its own
    decayed foundations (wishlist #58 -- "downstream decisions lose
    authority when their foundation does").

    `tree` is a core.decision_tree.DecisionTree; `get_ancestors` already
    walks caused_by/supersedes/reverts edges backward to find what a
    decision depends on. Floors at 0.5x, not 0.0x -- one badly-decayed
    ancestor should reduce authority, not erase it outright.
    """
    try:
        ancestors = tree.get_ancestors(decision_id, max_depth=max_depth)
    except Exception as exc:
        logger.warning("compute_inherited_discount: get_ancestors failed for %r: %s", decision_id, exc)
        return 1.0
    if not ancestors:
        return 1.0

    scores = []
    for a in ancestors:
        anc_decision = a.get("decision") if isinstance(a, dict) else None
        anc_id = anc_decision.get("id", "") if isinstance(anc_decision, dict) else ""
        scores.append(score_by_id.get(anc_id, 1.0))
    if not scores:
        return 1.0
    return 0.5 + 0.5 * min(scores)


def score_decisions_with_inheritance(decisions: list[dict]) -> list[dict[str, Any]]:
    """Like score_decisions, but each result also carries
    `inherited_discount` and `effective_score` -- the decision's own score
    discounted by however decayed its ancestors are. `score` keeps its
    existing meaning unchanged (own decay only); this is additive.
    """
    from core.decision_tree import DecisionTree

    if not decisions:
        return []

    tree = DecisionTree.from_decisions(decisions)
    own_scores = [score_decision(d, decisions) for d in decisions]
    score_by_id = {
        (d.get("id") or d.get("timestamp", "")): s["score"]
        for d, s in zip(decisions, own_scores)
    }

    results = []
    for d, s in zip(decisions, own_scores):
        did = d.get("id") or d.get("timestamp", "")
        discount = compute_inherited_discount(did, tree, score_by_id)
        result = dict(s)
        result["inherited_discount"] = round(discount, 3)
        result["effective_score"] = round(s["score"] * discount, 3)
        results.append(result)

    results.sort(key=lambda x: x["effective_score"], reverse=True)
    return results


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
        if not isinstance(d, dict):
            # Defensive against corrupted storage -- a non-dict entry has
            # no .get() for score_decision to call.
            continue
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
