"""
Session-Shape Baselining (wishlist.md #45) — pure functions.

Baselines the *shape* of a normal agent session (tool-call counts,
variance, latency, hang duration, output size) per (agent, project) pair,
so a deviation from that baseline becomes a detectable signal instead of
something only noticed in hindsight. Data comes from mcp_server/server.py's
_request() wrapper, flushed through POST /sessions/record at end_session.

No I/O here — same shape as core/prevention_report.py. Every function
treats malformed/missing input defensively rather than raising: this reads
agent-supplied telemetry that originates outside this codebase's direct
control, not internal data whose shape is fully guaranteed end-to-end. A
single bad record must degrade gracefully, not take down baseline
computation for everything else.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timezone
from typing import Any

from core.agent_identity import normalize_agent_name

SHAPE_METRICS = (
    "tool_call_count",
    "unique_tools_used",
    "avg_call_duration_ms",
    "max_call_duration_ms",
    "error_count",
    "avg_output_bytes",
    "total_duration_s",
)

# Minimum meaningful difference per metric — floors the MAD so a metric
# with zero historical spread (e.g. every past session had error_count==0)
# never divides by zero and doesn't flag on trivial noise.
_METRIC_FLOORS: dict[str, float] = {
    "tool_call_count": 1.0,
    "unique_tools_used": 1.0,
    "avg_call_duration_ms": 50.0,
    "max_call_duration_ms": 50.0,
    "error_count": 1.0,
    "avg_output_bytes": 20.0,
    "total_duration_s": 5.0,
}

# Below this many prior sessions, a baseline is degenerate (either matches
# the lone point exactly, or has no real spread) rather than just noisy —
# report insufficient_data honestly instead of a meaningless comparison.
MIN_BASELINE_SESSIONS = 5

# Generous vs friction_history's 50: each record is ~7 floats, and a tight
# cap risks crowding out a low-activity agent's baseline entirely if a
# high-activity agent dominates recent history.
MAX_STORED_RECORDS = 300

# Standard Iglewicz & Hoya modified-z-score outlier bands, plus an explicit
# "normal" state below the first threshold (not folded into "low").
_SEVERITY_BANDS: tuple[tuple[float, str], ...] = (
    (3.5, "normal"),
    (5.0, "low"),
    (8.0, "medium"),
)
_SEVERITY_HIGH = "high"
_SEVERITY_RANK = {"normal": 0, "low": 1, "medium": 2, "high": 3}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Coerce to float defensively. See module docstring: this reads
    agent-supplied telemetry, so a malformed value must degrade to a
    default rather than raise."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def filter_records_for_agent(records: list[Any], agent: str) -> list[dict[str, Any]]:
    """Filter a project's session_shapes down to one agent, normalized the
    same way friction_history/compute_friction_by_agent already does.
    Silently skips any entry that isn't a dict rather than raising —
    defensive against corrupted storage, matching this module's stance
    throughout."""
    if not records:
        return []
    agent = normalize_agent_name(agent)
    return [r for r in records if isinstance(r, dict) and r.get("agent_name") == agent]


def _median_and_mad(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    median = statistics.median(values)
    mad = statistics.median([abs(v - median) for v in values])
    return median, mad


def compute_baseline(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute a per-metric median+MAD baseline from prior session_shapes
    records (already filtered to one agent).

    Median+MAD, not mean+stddev: per-call durations/sizes are right-skewed
    in real sessions (one slow call dwarfs the rest) — mean+stddev is
    exactly the wrong tool since outliers inflate the baseline's own
    spread. One method for every metric.
    """
    records = records or []
    n = len(records)
    if n < MIN_BASELINE_SESSIONS:
        return {"status": "insufficient_data", "sample_size": n, "required": MIN_BASELINE_SESSIONS}

    metrics: dict[str, dict[str, float]] = {}
    for metric in SHAPE_METRICS:
        values = [_safe_float(r.get(metric)) for r in records if isinstance(r, dict)]
        median, mad = _median_and_mad(values)
        metrics[metric] = {"median": median, "mad": mad}

    return {"status": "ok", "sample_size": n, "metrics": metrics}


def _modified_z(value: float, median: float, mad: float, floor: float) -> float:
    """Modified z-score (Iglewicz & Hoya), robust to outliers unlike a
    mean/stddev z-score. `floor` prevents divide-by-zero on a metric with
    no historical spread."""
    scale = max(mad, floor, 1e-9)  # 1e-9 as a final guard, never truly zero
    return 0.6745 * (value - median) / scale


def _severity_for_z(z: float) -> str:
    az = abs(z)
    for threshold, severity in _SEVERITY_BANDS:
        if az < threshold:
            return severity
    return _SEVERITY_HIGH


def classify_deviation(current: dict[str, Any] | None, baseline: dict[str, Any]) -> dict[str, Any]:
    """Compare one session's shape against a computed baseline.

    overall_severity is the worst severity across any single metric — same
    "keep the worst" convention core/docmine/combined.py's combined_severity
    uses for cross-detector findings.
    """
    if not isinstance(baseline, dict) or baseline.get("status") != "ok":
        return {"overall_severity": "insufficient_data", "metrics": {}}

    current = current if isinstance(current, dict) else {}
    baseline_metrics = baseline.get("metrics")
    if not isinstance(baseline_metrics, dict):
        baseline_metrics = {}
    worst = "normal"
    per_metric: dict[str, Any] = {}
    for metric in SHAPE_METRICS:
        bm = baseline_metrics.get(metric)
        if not isinstance(bm, dict):
            bm = {"median": 0.0, "mad": 0.0}
        value = _safe_float(current.get(metric))
        floor = _METRIC_FLOORS.get(metric, 1.0)
        z = _modified_z(value, _safe_float(bm.get("median")), _safe_float(bm.get("mad")), floor)
        severity = _severity_for_z(z)
        per_metric[metric] = {
            "value": value,
            "baseline_median": _safe_float(bm.get("median")),
            "z_score": round(z, 3),
            "severity": severity,
        }
        if _SEVERITY_RANK[severity] > _SEVERITY_RANK[worst]:
            worst = severity

    return {"overall_severity": worst, "metrics": per_metric}


def record_session_shape(
    memory: dict[str, Any], agent_name: str, current_metrics: dict[str, Any] | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Baseline `current_metrics` against this agent's PRIOR history (not
    including the record being added), append the new record to memory in
    place, and return (memory, result). Caller is responsible for
    persisting `memory` afterward.
    """
    agent = normalize_agent_name(agent_name)
    current_metrics = current_metrics if isinstance(current_metrics, dict) else {}
    if not isinstance(memory, dict):
        memory = {}
    existing = memory.get("session_shapes")
    if not isinstance(existing, list):
        existing = []

    prior_for_agent = filter_records_for_agent(existing, agent)
    baseline = compute_baseline(prior_for_agent)
    deviation = classify_deviation(current_metrics, baseline)

    entry = {
        "agent_name": agent,
        "timestamp": _now_iso(),
        **{metric: _safe_float(current_metrics.get(metric)) for metric in SHAPE_METRICS},
    }
    updated = existing + [entry]
    memory["session_shapes"] = updated[-MAX_STORED_RECORDS:]

    return memory, {"baseline": baseline, "deviation": deviation}


def latest_deviation_for_agent(records_for_agent: list[dict[str, Any]]) -> dict[str, Any]:
    """For the read endpoint: baseline over all-but-the-latest record,
    deviation of the latest record against that baseline — same
    self-exclusion principle record_session_shape uses at write time, so
    a session is never baselined against itself. Records are assumed
    already filtered to one agent, oldest first (storage order)."""
    records_for_agent = records_for_agent or []
    if not records_for_agent:
        return {"status": "insufficient_data", "sample_size": 0, "required": MIN_BASELINE_SESSIONS}

    prior, latest = records_for_agent[:-1], records_for_agent[-1]
    baseline = compute_baseline(prior)
    if baseline.get("status") != "ok":
        return baseline

    deviation = classify_deviation(latest, baseline)
    return {
        "status": "ok",
        "sample_size": baseline["sample_size"],
        "baseline": baseline,
        "latest": latest,
        "deviation": deviation,
    }
