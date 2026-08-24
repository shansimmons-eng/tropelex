"""
Research Feed Intelligence — trend detection and anomaly flagging.

Pure functions that analyse historical feed run data to surface
trending topics, velocity changes, and anomalous patterns.
"""

from collections import Counter, defaultdict
from typing import Any


def detect_trends(feed_runs: list[dict]) -> dict[str, Any]:
    """Analyse feed runs for trending topics and velocity.

    Args:
        feed_runs: List of run dicts, each with 'citations' (list) and 'timestamp'.

    Returns:
        {trending_topics: [...], peak_periods: [...], overall_trend: str}
    """
    if not feed_runs:
        return {"trending_topics": [], "peak_periods": [], "overall_trend": "stable"}

    topic_counts = _count_topics(feed_runs)
    velocity = _compute_velocity(topic_counts, window=max(1, len(feed_runs) // 3))
    trending = _extract_trending(topic_counts, velocity)
    peaks = _find_peak_periods(feed_runs)
    overall = _classify_overall_trend(velocity)

    return {
        "trending_topics": trending,
        "peak_periods": peaks,
        "overall_trend": overall,
    }


def flag_anomalies(feed_runs: list[dict]) -> list[dict[str, Any]]:
    """Detect unusual patterns in feed run history.

    Returns list of anomalies with type, severity, description, and run_index.
    """
    if len(feed_runs) < 2:
        return []

    anomalies: list[dict[str, Any]] = []
    sizes = [len(r.get("citations", [])) for r in feed_runs]
    avg = sum(sizes) / len(sizes) if sizes else 0

    for i, size in enumerate(sizes):
        if avg > 0 and size > avg * 3:
            anomalies.append(_make_anomaly("spike", "medium", i, size, avg))
        elif avg > 0 and size < avg * 0.1 and avg > 2:
            anomalies.append(_make_anomaly("drop", "medium", i, size, avg))

    anomalies.extend(_detect_error_clusters(feed_runs))
    anomalies.extend(_detect_stale_runs(feed_runs))
    return anomalies


def compute_feed_intelligence(feed_runs: list[dict]) -> dict[str, Any]:
    """Combined intelligence report from feed run history."""
    return {
        "trends": detect_trends(feed_runs),
        "anomalies": flag_anomalies(feed_runs),
        "run_count": len(feed_runs),
        "total_citations": sum(len(r.get("citations", [])) for r in feed_runs),
    }


def score_feed_citation_health(citations: list[dict]) -> dict[str, Any]:
    """Score a feed's own citations for staleness using knowledge_decay's
    score_citation -- defined since #40 (Injection Sentinel) but never
    wired to anything until now (wishlist #80). Citations decay faster
    than decisions (60-day half-life, see score_citation), so a feed left
    on manual/monthly interval can quietly accumulate citations nobody
    would trust anymore.

    Args:
        citations: List of citation dicts (Citation.to_dict() shape) for
            one feed's citation_ids, already resolved by the caller.

    Returns:
        {count, average_score, aging_count, citations: [scored...]}
        aging_count counts 'low'/'stale' tier citations -- the same two
        tiers get_confidence_summary treats as needing attention.
    """
    if not citations:
        return {"count": 0, "average_score": None, "aging_count": 0, "citations": []}

    from core.knowledge_decay import score_citation

    scored = [score_citation(c) for c in citations]
    aging_count = sum(1 for s in scored if s["tier"] in ("low", "stale"))
    average_score = round(sum(s["score"] for s in scored) / len(scored), 3)

    return {
        "count": len(scored),
        "average_score": average_score,
        "aging_count": aging_count,
        "citations": scored,
    }


def _count_topics(runs: list[dict]) -> dict[str, list[int]]:
    """Count citation topics per run index.

    Only resolved citation dicts (with a 'topic'/'title' field) carry
    anything to group by -- a run history built from FeedRun.citations_added
    (plain citation-id strings, see feed_intelligence_router.py's own
    caller-side comment) has no topic text at all, so those entries are
    skipped rather than crashing on `.get()` against a bare string or
    silently bucketing everything under 'unknown'.
    """
    topic_runs: dict[str, list[int]] = defaultdict(list)
    for i, run in enumerate(runs):
        for cit in run.get("citations", []):
            if not isinstance(cit, dict):
                continue
            topic = cit.get("topic") or cit.get("title", "unknown")
            topic_runs[topic].append(i)
    return dict(topic_runs)


def _compute_velocity(counts: dict[str, list[int]], window: int) -> dict[str, float]:
    """Rate of change per topic — positive = accelerating."""
    velocity: dict[str, float] = {}
    for topic, run_indices in counts.items():
        if len(run_indices) < 2:
            velocity[topic] = 0.0
            continue
        recent = sum(1 for i in run_indices if i >= max(run_indices) - window + 1)
        earlier = sum(1 for i in run_indices if i < max(run_indices) - window + 1)
        velocity[topic] = (recent - earlier) / max(window, 1)
    return velocity


def _extract_trending(
    counts: dict[str, list[int]], velocity: dict[str, float]
) -> list[dict[str, Any]]:
    """Top trending topics by frequency and positive velocity."""
    items = []
    for topic, run_indices in counts.items():
        vel = velocity.get(topic, 0)
        if len(run_indices) >= 2 or vel > 0:
            items.append({
                "topic": topic,
                "frequency": len(run_indices),
                "velocity": round(vel, 2),
            })
    items.sort(key=lambda x: x["frequency"], reverse=True)
    return items[:10]


def _find_peak_periods(runs: list[dict]) -> list[dict[str, Any]]:
    """Identify runs with unusually high citation counts."""
    if not runs:
        return []
    sizes = [len(r.get("citations", [])) for r in runs]
    avg = sum(sizes) / len(sizes) if sizes else 0
    threshold = max(avg * 2, 3)
    peaks = []
    for i, size in enumerate(sizes):
        if size >= threshold:
            peaks.append({
                "run_index": i,
                "timestamp": runs[i].get("timestamp", ""),
                "citation_count": size,
            })
    return peaks


def _classify_overall_trend(velocity: dict[str, float]) -> str:
    """Classify the overall trend direction."""
    if not velocity:
        return "stable"
    avg_vel = sum(velocity.values()) / len(velocity)
    if avg_vel > 0.5:
        return "increasing"
    if avg_vel < -0.5:
        return "decreasing"
    return "stable"


def _make_anomaly(
    anomaly_type: str, severity: str, run_index: int, size: float, avg: float
) -> dict[str, Any]:
    """Construct an anomaly dict."""
    return {
        "anomaly_type": anomaly_type,
        "severity": severity,
        "description": f"Run {run_index}: {anomaly_type} ({size} citations, avg {avg:.1f})",
        "run_index": run_index,
    }


def _detect_error_clusters(runs: list[dict]) -> list[dict[str, Any]]:
    """Flag consecutive runs with errors."""
    anomalies: list[dict[str, Any]] = []
    streak = 0
    for i, run in enumerate(runs):
        if run.get("errors") or run.get("status") == "error":
            streak += 1
        else:
            if streak >= 3:
                anomalies.append({
                    "anomaly_type": "error_cluster",
                    "severity": "high",
                    "description": f"{streak} consecutive error runs ending at index {i - 1}",
                    "run_index": i - 1,
                })
            streak = 0
    if streak >= 3:
        anomalies.append({
            "anomaly_type": "error_cluster",
            "severity": "high",
            "description": f"{streak} consecutive error runs at end",
            "run_index": len(runs) - 1,
        })
    return anomalies


def _detect_stale_runs(runs: list[dict]) -> list[dict[str, Any]]:
    """Flag runs with zero citations (possibly stale or misconfigured)."""
    anomalies: list[dict[str, Any]] = []
    for i, run in enumerate(runs):
        if not run.get("citations") and run.get("status") != "error":
            anomalies.append({
                "anomaly_type": "stale",
                "severity": "low",
                "description": f"Run {i} produced zero citations",
                "run_index": i,
            })
    return anomalies
