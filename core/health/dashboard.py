"""
Memory Health Dashboard — aggregate health metrics for a project.

Pure functions that analyse memory state and produce actionable diagnostics:
stale decisions, coverage gaps, growth trends, and quality scores.
"""

from typing import Any

from core.knowledge_decay import get_confidence_summary, get_stale_decisions, score_decisions


def aggregate_health_metrics(memory: dict) -> dict[str, Any]:
    """Compute a full health report for a single project's memory.

    Returns:
        {
            stale_decisions: [...],
            coverage_gaps: [...],
            growth_trends: {decision_count, session_count, pattern_count},
            quality_score: float 0-1,
            recommendations: [...],
        }
    """
    decisions = memory.get("decisions", [])
    scored = score_decisions(decisions)
    stale = get_stale_decisions(decisions)
    confidence = get_confidence_summary(memory)
    tech_stack = memory.get("tech_stack", [])
    gaps = _compute_coverage_gaps(decisions, tech_stack)
    quality = _compute_quality_score(scored)
    trends = _compute_growth_trends(memory)
    recs = _generate_recommendations(stale, gaps, quality, confidence)

    return {
        "stale_decisions": [_format_stale(s) for s in stale[:10]],
        "coverage_gaps": gaps,
        "growth_trends": trends,
        "quality_score": round(quality, 3),
        "recommendations": recs,
        "confidence_summary": confidence,
    }


def _compute_coverage_gaps(decisions: list[dict], tech_stack: list[str]) -> list[str]:
    """Find tech_stack items not mentioned in any decision."""
    if not tech_stack:
        return []
    covered = set()
    for d in decisions:
        text = (d.get("decision", "") + " " + d.get("context", "")).lower()
        for tech in tech_stack:
            if tech.lower() in text:
                covered.add(tech)
    return [t for t in tech_stack if t not in covered]


def _compute_quality_score(scored_decisions: list[dict]) -> float:
    """Weighted average confidence score (0-1). Returns 0 if no decisions."""
    if not scored_decisions:
        return 0.0
    total = sum(s.get("score", 0) for s in scored_decisions)
    return total / len(scored_decisions)


def _compute_growth_trends(memory: dict) -> dict[str, int]:
    """Count key memory components for growth tracking."""
    return {
        "decision_count": len(memory.get("decisions", [])),
        "session_count": len(memory.get("session_history", [])),
        "pattern_count": len(memory.get("patterns", [])),
    }


def _generate_recommendations(
    stale: list[dict],
    gaps: list[str],
    quality: float,
    confidence: dict[str, Any],
) -> list[str]:
    """Produce actionable maintenance suggestions."""
    recs: list[str] = []
    if stale:
        recs.append(f"Review {len(stale)} stale decision(s) for relevance")
    if gaps:
        recs.append(f"Add decisions covering: {', '.join(gaps[:3])}")
    if quality < 0.5:
        recs.append("Overall confidence is low — record more context for decisions")
    tier = confidence.get("by_tier", {})
    if tier.get("stale", 0) > tier.get("high", 0):
        recs.append("More stale than high-confidence decisions — consider a review session")
    if not recs:
        recs.append("Memory health looks good — keep recording decisions")
    return recs


def _format_stale(entry: dict) -> dict[str, Any]:
    """Return a minimal view of a stale decision for the dashboard."""
    return {
        "decision": entry.get("decision", "")[:120],
        "timestamp": entry.get("timestamp", ""),
        "confidence": entry.get("confidence", {}).get("score", 0),
    }
