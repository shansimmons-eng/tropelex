"""
Session-Shape correlation with Ghost/Friction outcomes (wishlist #73-3).

Answers a real question #45's baseline alone can't: does a session-shape
deviation for an agent actually predict a worse outcome afterward, or is it
noise? Right now #45 (this module's own baseline.py) and Ghost/Friction's
data are stored independently with no join -- this is that join.

Market is deliberately NOT included: a resolved bet (core/market/
calibration.py) only carries `placed_at`, not a separate resolution
timestamp, so "did a bad outcome happen after this deviation" can't be
computed honestly for it -- the bet could have been placed before the
deviation and resolved after, or the reverse, and there's no way to tell
which from the data alone. Ghost is represented via override events (an
agent proceeding past a gate warning is itself the Ghost-relevant "something
happened" signal) rather than gate_blocked/gate_warned directly, since those
events carried no agent attribution at all until #73-4 added it -- folding
them in here would silently undercount every session recorded before that
change rather than just honestly excluding a signal that isn't available.

Pure functions, no I/O -- same shape as core/prevention_report.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from core.session_shape.baseline import MIN_BASELINE_SESSIONS, classify_deviation, compute_baseline

MIN_DEVIATION_SAMPLES = 5
DEFAULT_WINDOW_DAYS = 7.0
_ELEVATED_FRICTION_THRESHOLD = 0.5


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def deviations_for_agent(records_for_agent: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """For every record after the first MIN_BASELINE_SESSIONS, baseline it
    against only the records strictly before it -- self-exclusion, the same
    principle latest_deviation_for_agent uses for the single most recent
    record, generalized here to every record in the history so each one
    gets its own honest "as of that point in time" severity instead of
    being judged against a baseline that includes its own future.

    Records assumed oldest-first (storage order, matching how session_shapes
    is actually appended).
    """
    records_for_agent = [r for r in (records_for_agent or []) if isinstance(r, dict)]
    out: list[dict[str, Any]] = []
    for i in range(MIN_BASELINE_SESSIONS, len(records_for_agent)):
        prior = records_for_agent[:i]
        current = records_for_agent[i]
        baseline = compute_baseline(prior)
        if baseline.get("status") != "ok":
            continue
        ts = _parse_ts(current.get("timestamp"))
        if ts is None:
            continue
        deviation = classify_deviation(current, baseline)
        out.append({"timestamp": ts, "overall_severity": deviation["overall_severity"]})
    return out


def outcome_events_for_agent(memory: dict[str, Any], agent: str) -> list[dict[str, Any]]:
    """Real per-agent, timestamped signals that something went wrong
    afterward: an override (agent proceeded past a Ghost/Contradiction
    warning) or an elevated-friction scan. Both timestamp fields have
    existed since their respective features shipped, unlike gate_blocked/
    gate_warned which only gained agent attribution with #73-4.
    """
    events: list[dict[str, Any]] = []
    for o in memory.get("overrides", []) or []:
        if not isinstance(o, dict) or o.get("agent_name") != agent:
            continue
        ts = _parse_ts(o.get("timestamp"))
        if ts:
            events.append({"timestamp": ts, "kind": "override"})
    for h in memory.get("friction_history", []) or []:
        if not isinstance(h, dict) or h.get("agent_name") != agent:
            continue
        if _safe_float(h.get("friction_score")) < _ELEVATED_FRICTION_THRESHOLD:
            continue
        ts = _parse_ts(h.get("timestamp"))
        if ts:
            events.append({"timestamp": ts, "kind": "elevated_friction"})
    return events


def correlate_deviations_with_outcomes(
    deviations: list[dict[str, Any]],
    outcome_events: list[dict[str, Any]],
    window_days: float = DEFAULT_WINDOW_DAYS,
) -> dict[str, Any]:
    """For each deviation, check whether an outcome event landed within
    `window_days` afterward. Compares the outcome rate following a flagged
    (non-"normal"-severity) session against the rate following a normal one
    -- the lift is what actually answers whether the deviation predicts
    anything, since some baseline rate of overrides/friction happens
    regardless of session shape and a raw "X% of flagged sessions had an
    outcome" number alone can't distinguish signal from that base rate.
    """
    if len(deviations) < MIN_DEVIATION_SAMPLES:
        return {
            "status": "insufficient_data",
            "sample_size": len(deviations),
            "required": MIN_DEVIATION_SAMPLES,
        }

    window = timedelta(days=window_days)
    flagged_total = flagged_hit = normal_total = normal_hit = 0
    for d in deviations:
        window_end = d["timestamp"] + window
        hit = any(d["timestamp"] < e["timestamp"] <= window_end for e in outcome_events)
        if d["overall_severity"] == "normal":
            normal_total += 1
            normal_hit += int(hit)
        else:
            flagged_total += 1
            flagged_hit += int(hit)

    rate_flagged = round(flagged_hit / flagged_total, 4) if flagged_total else None
    rate_normal = round(normal_hit / normal_total, 4) if normal_total else None
    lift = (
        round(rate_flagged / rate_normal, 3)
        if rate_flagged is not None and rate_normal
        else None
    )

    return {
        "status": "ok",
        "window_days": window_days,
        "flagged_sessions": flagged_total,
        "flagged_followed_by_outcome": flagged_hit,
        "rate_when_flagged": rate_flagged,
        "normal_sessions": normal_total,
        "normal_followed_by_outcome": normal_hit,
        "rate_when_normal": rate_normal,
        "lift": lift,
    }
