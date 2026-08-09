"""
Prevention Report — aggregates the append-only audit trail (core/audit.py,
#52) into "what have we prevented so far?" (wishlist.md #61).

Pure function: reads an audit_log list, returns counts/severity/rationale.
No I/O, no memory mutation — same shape as core/docmine/combined.py's
combine_doc_and_ghost_findings, a join over structured output that already
exists rather than new detection logic.

Historical only, by construction: gate_blocked/gate_warned/
contradiction_escalated events only exist from the moment this feature
shipped onward (see core/ghost/preventive_router.py, core/contradictions/
router.py). Same honestly-disclosed backfill limitation #52 already carries
for its own audit log.
"""

from __future__ import annotations

from typing import Any

# Event types this report reads. Kept as a set (not hardcoded per-field
# lookups scattered through the function) so a future event type is a
# one-line addition here plus a filter below, not a rewrite.
_PREVENTION_EVENT_TYPES = {"gate_blocked", "gate_warned", "override", "contradiction_escalated"}


def _sum_severity_counts(events: list[dict[str, Any]]) -> int:
    """Total occurrences across a list of events carrying severity_counts."""
    return sum(sum(e.get("severity_counts", {}).values()) for e in events)


def _accumulate_severity(dist: dict[str, int], events: list[dict[str, Any]]) -> None:
    for e in events:
        for sev, n in e.get("severity_counts", {}).items():
            if sev in dist:
                dist[sev] += n


def build_prevention_report(audit_log: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate prevention-relevant audit_log entries into a report.

    Only reads audit_log — doesn't touch or recompute live decision state,
    so this is strictly a historical view (what got logged), not a live
    recomputation the way get_provenance_chain used to be before #52.
    """
    blocked = [e for e in audit_log if e.get("event_type") == "gate_blocked"]
    warned = [e for e in audit_log if e.get("event_type") == "gate_warned"]
    overridden = [e for e in audit_log if e.get("event_type") == "override"]
    escalated = [e for e in audit_log if e.get("event_type") == "contradiction_escalated"]

    severity_distribution = {"high": 0, "medium": 0, "low": 0}
    _accumulate_severity(severity_distribution, blocked)
    _accumulate_severity(severity_distribution, warned)
    _accumulate_severity(severity_distribution, escalated)

    gate_blocked_count = _sum_severity_counts(blocked)
    gate_warned_count = _sum_severity_counts(warned)
    contradiction_escalated_count = len(escalated)
    override_count = len(overridden)

    total_prevented = gate_blocked_count + gate_warned_count + contradiction_escalated_count

    # Rough calibration signal (wishlist #61): a gate whose warnings mostly
    # get overridden is either mistuned or the policy is too strict for this
    # project — worth surfacing either way, not proof of anything on its own.
    gate_signal_count = gate_blocked_count + gate_warned_count
    calibration_denom = gate_signal_count + override_count
    override_rate = round(override_count / calibration_denom, 4) if calibration_denom else 0.0

    overrides_detail = [
        {
            "override_id": e.get("override_id"),
            "decision_id": e.get("decision_id"),
            "rationale": e.get("rationale"),
            "agent_name": e.get("agent_name"),
            "timestamp": e.get("timestamp"),
        }
        for e in overridden
    ]

    relevant = [e for e in audit_log if e.get("event_type") in _PREVENTION_EVENT_TYPES]

    return {
        "gate_blocked_count": gate_blocked_count,
        "gate_warned_count": gate_warned_count,
        "contradiction_escalated_count": contradiction_escalated_count,
        "override_count": override_count,
        "total_prevented": total_prevented,
        "severity_distribution": severity_distribution,
        "override_rate": override_rate,
        "overrides": overrides_detail,
        "earliest_event": relevant[0]["timestamp"] if relevant else None,
        "latest_event": relevant[-1]["timestamp"] if relevant else None,
    }
