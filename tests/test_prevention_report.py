"""
Tests for core/prevention_report.py — the pure aggregation function behind
"what have we prevented so far?" (wishlist.md #61).

Uses pytest, AAA pattern, no shared state, no I/O (the function under test
takes a plain list and returns a plain dict).
"""

from core.prevention_report import build_prevention_report


def _event(event_type, **fields):
    return {"event_type": event_type, "timestamp": "2026-08-09T00:00:00+00:00", **fields}


class TestBuildPreventionReportEmpty:
    def test_empty_audit_log(self):
        # Act
        report = build_prevention_report([])

        # Assert
        assert report["gate_blocked_count"] == 0
        assert report["gate_warned_count"] == 0
        assert report["contradiction_escalated_count"] == 0
        assert report["override_count"] == 0
        assert report["total_prevented"] == 0
        assert report["severity_distribution"] == {"high": 0, "medium": 0, "low": 0}
        assert report["override_rate"] == 0.0
        assert report["overrides"] == []
        assert report["earliest_event"] is None
        assert report["latest_event"] is None

    def test_audit_log_with_only_unrelated_events(self):
        # Arrange — decision_created/review_submitted/version_created aren't
        # prevention signals; the report must not count them.
        audit_log = [
            _event("decision_created", decision_id="d1"),
            _event("review_submitted", decision_id="d1"),
            _event("version_created", decision_id="d1"),
        ]

        # Act
        report = build_prevention_report(audit_log)

        # Assert
        assert report["total_prevented"] == 0
        assert report["earliest_event"] is None


class TestBuildPreventionReportCounts:
    def test_counts_multiple_severities_in_one_gate_blocked_event(self):
        # Arrange — one gate_blocked event can cover several warnings from
        # a single ghost-check call (see preventive_router._severity_counts)
        audit_log = [
            _event("gate_blocked", decision_ids=["d1", "d2"],
                   severity_counts={"high": 2, "medium": 0, "low": 0}),
        ]

        # Act
        report = build_prevention_report(audit_log)

        # Assert
        assert report["gate_blocked_count"] == 2
        assert report["total_prevented"] == 2
        assert report["severity_distribution"] == {"high": 2, "medium": 0, "low": 0}

    def test_gate_warned_and_contradiction_escalated_both_count(self):
        # Arrange
        audit_log = [
            _event("gate_warned", decision_ids=["d1"],
                   severity_counts={"high": 0, "medium": 1, "low": 0}),
            _event("contradiction_escalated", decision_id="d2", severity_counts={"high": 1}),
        ]

        # Act
        report = build_prevention_report(audit_log)

        # Assert
        assert report["gate_warned_count"] == 1
        assert report["contradiction_escalated_count"] == 1
        assert report["total_prevented"] == 2
        assert report["severity_distribution"] == {"high": 1, "medium": 1, "low": 0}

    def test_override_count_and_detail(self):
        # Arrange
        audit_log = [
            _event("override", override_id="o1", decision_id="d1",
                   rationale="legacy SDK casing", agent_name="claude"),
        ]

        # Act
        report = build_prevention_report(audit_log)

        # Assert
        assert report["override_count"] == 1
        assert report["overrides"] == [{
            "override_id": "o1",
            "decision_id": "d1",
            "rationale": "legacy SDK casing",
            "agent_name": "claude",
            "timestamp": "2026-08-09T00:00:00+00:00",
        }]
        # An override alone (no matching block logged) still doesn't count
        # toward total_prevented -- it represents accepted risk, not
        # something stopped.
        assert report["total_prevented"] == 0


class TestBuildPreventionReportOverrideRate:
    def test_no_gate_signals_and_no_overrides_is_zero(self):
        assert build_prevention_report([])["override_rate"] == 0.0

    def test_all_blocked_no_overrides_is_zero(self):
        audit_log = [_event("gate_blocked", decision_ids=["d1"],
                             severity_counts={"high": 1, "medium": 0, "low": 0})]
        assert build_prevention_report(audit_log)["override_rate"] == 0.0

    def test_all_overridden_no_blocks_is_one(self):
        audit_log = [_event("override", override_id="o1", decision_id="d1",
                             rationale="x", agent_name="claude")]
        assert build_prevention_report(audit_log)["override_rate"] == 1.0

    def test_mixed_blocks_and_overrides(self):
        # Arrange — 3 gate signals (2 blocked + 1 warned), 1 override
        # -> 1 / (3 + 1) = 0.25
        audit_log = [
            _event("gate_blocked", decision_ids=["d1"],
                   severity_counts={"high": 2, "medium": 0, "low": 0}),
            _event("gate_warned", decision_ids=["d2"],
                   severity_counts={"high": 0, "medium": 1, "low": 0}),
            _event("override", override_id="o1", decision_id="d1",
                   rationale="x", agent_name="claude"),
        ]

        # Act
        report = build_prevention_report(audit_log)

        # Assert
        assert report["override_rate"] == 0.25


class TestBuildPreventionReportEventRange:
    def test_earliest_and_latest_span_only_relevant_events(self):
        # Arrange — decision_created is not a prevention event and must not
        # widen the reported range even though it's chronologically first.
        audit_log = [
            _event("decision_created", decision_id="d0"),
            {**_event("gate_blocked", decision_ids=["d1"],
                       severity_counts={"high": 1, "medium": 0, "low": 0}),
             "timestamp": "2026-08-01T00:00:00+00:00"},
            {**_event("override", override_id="o1", decision_id="d1",
                       rationale="x", agent_name="claude"),
             "timestamp": "2026-08-05T00:00:00+00:00"},
        ]

        # Act
        report = build_prevention_report(audit_log)

        # Assert
        assert report["earliest_event"] == "2026-08-01T00:00:00+00:00"
        assert report["latest_event"] == "2026-08-05T00:00:00+00:00"
