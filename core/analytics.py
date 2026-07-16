"""
Memory Analytics — usage patterns, growth trends, quality metrics.

Pure functions that analyse memory history to surface actionable insights
about how memory is being used and where it's most valuable.
"""

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from core.knowledge_decay import score_decisions


def compute_analytics(memory: dict) -> dict[str, Any]:
    """Full analytics report for a project.

    Returns:
        {
            usage: {decision_rate, session_rate, pattern_rate},
            growth: {timeline, total_items},
            quality: {avg_confidence, tier_distribution, trend},
            top_categories: [...],
            recommendations: [...],
        }
    """
    decisions = memory.get("decisions", [])
    sessions = memory.get("session_history", [])
    patterns = memory.get("patterns", [])

    usage = _compute_usage_rates(decisions, sessions, patterns)
    growth = _compute_growth_timeline(decisions, sessions)
    quality = _compute_quality_metrics(decisions)
    categories = _extract_top_categories(decisions)
    recs = _generate_analytics_recommendations(usage, quality, growth)

    return {
        "usage": usage,
        "growth": growth,
        "quality": quality,
        "top_categories": categories,
        "recommendations": recs,
    }


def _compute_usage_rates(
    decisions: list[dict], sessions: list[dict], patterns: list[dict]
) -> dict[str, Any]:
    """Compute items per month rates."""
    now = datetime.now(timezone.utc)
    months = max(_months_span(decisions, now), 1)

    return {
        "total_decisions": len(decisions),
        "total_sessions": len(sessions),
        "total_patterns": len(patterns),
        "decisions_per_month": round(len(decisions) / months, 1),
        "sessions_per_month": round(len(sessions) / months, 1),
        "patterns_per_month": round(len(patterns) / months, 1),
        "active_months": round(months, 1),
    }


def _compute_growth_timeline(
    decisions: list[dict], sessions: list[dict]
) -> dict[str, Any]:
    """Monthly growth timeline."""
    monthly: dict[str, dict[str, int]] = defaultdict(lambda: {"decisions": 0, "sessions": 0})

    for d in decisions:
        month = _extract_month(d.get("timestamp", ""))
        if month:
            monthly[month]["decisions"] += 1

    for s in sessions:
        month = _extract_month(s.get("date", ""))
        if month:
            monthly[month]["sessions"] += 1

    timeline = [
        {"month": m, "decisions": v["decisions"], "sessions": v["sessions"]}
        for m, v in sorted(monthly.items())
    ]

    return {
        "timeline": timeline[-12:],  # Last 12 months
        "total_items": len(decisions) + len(sessions),
    }


def _compute_quality_metrics(decisions: list[dict]) -> dict[str, Any]:
    """Quality metrics from confidence scoring."""
    if not decisions:
        return {"avg_confidence": 0, "tier_distribution": {}, "trend": "no_data"}

    scored = score_decisions(decisions)
    scores = [s["score"] for s in scored]
    avg = sum(scores) / len(scores)

    tier_dist: dict[str, int] = {}
    for s in scored:
        tier = s.get("tier", "unknown")
        tier_dist[tier] = tier_dist.get(tier, 0) + 1

    # Trend: compare first half vs second half confidence
    mid = len(scored) // 2
    if mid > 0:
        first_half = sum(s["score"] for s in scored[:mid]) / mid
        second_half = sum(s["score"] for s in scored[mid:]) / (len(scored) - mid)
        if second_half > first_half * 1.1:
            trend = "improving"
        elif second_half < first_half * 0.9:
            trend = "declining"
        else:
            trend = "stable"
    else:
        trend = "insufficient_data"

    return {
        "avg_confidence": round(avg, 3),
        "min_confidence": round(min(scores), 3),
        "max_confidence": round(max(scores), 3),
        "tier_distribution": tier_dist,
        "trend": trend,
    }


def _extract_top_categories(decisions: list[dict]) -> list[dict[str, Any]]:
    """Extract most common decision categories/topics."""
    word_freq: dict[str, int] = defaultdict(int)
    for d in decisions:
        text = d.get("decision", "").lower()
        for word in text.split():
            clean = "".join(c for c in word if c.isalnum())
            if len(clean) > 3:
                word_freq[clean] += 1

    top = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:10]
    return [{"topic": word, "count": count} for word, count in top]


def _generate_analytics_recommendations(
    usage: dict, quality: dict, growth: dict
) -> list[str]:
    """Actionable recommendations based on analytics."""
    recs: list[str] = []

    if usage["total_decisions"] < 5:
        recs.append("Record more decisions to build a useful knowledge base")
    if usage["sessions_per_month"] < 1:
        recs.append("Run more sessions to keep memory fresh and relevant")
    if quality.get("avg_confidence", 0) < 0.4:
        recs.append("Decision confidence is low — add more context to decisions")
    if quality.get("trend") == "declining":
        recs.append("Confidence trend is declining — consider reviewing old decisions")
    if usage["total_patterns"] == 0:
        recs.append("No patterns detected yet — patterns emerge from repeated decisions")
    if not growth.get("timeline"):
        recs.append("No growth data yet — memory will grow as you use Tropelex")

    if not recs:
        recs.append("Memory usage looks healthy — keep recording decisions and sessions")

    return recs


def _months_span(items: list[dict], now: datetime) -> float:
    """Months between earliest item and now."""
    earliest = now
    for item in items:
        ts = item.get("timestamp") or item.get("date", "")
        dt = _parse_ts(ts)
        if dt and dt < earliest:
            earliest = dt
    delta = now - earliest
    return max(delta.days / 30.44, 1)


def _extract_month(ts: str) -> str:
    """Extract YYYY-MM from timestamp."""
    dt = _parse_ts(ts)
    if dt:
        return dt.strftime("%Y-%m")
    return ""


def _parse_ts(ts: str) -> datetime | None:
    """Parse ISO timestamp."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
