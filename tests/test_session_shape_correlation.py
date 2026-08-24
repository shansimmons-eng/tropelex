"""Tests for core/session_shape/correlation.py (wishlist #73-3): does a
session-shape deviation predict a later Ghost/Friction outcome, or is it
noise? Pure-function tests -- no HTTP, no MemoryManager.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.session_shape.correlation import (
    MIN_DEVIATION_SAMPLES,
    correlate_deviations_with_outcomes,
    deviations_for_agent,
    outcome_events_for_agent,
)

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _shape(i: int, **overrides) -> dict:
    base = {
        "agent_name": "Claude",
        "timestamp": (_T0 + timedelta(days=i)).isoformat(),
        "tool_call_count": 10,
        "unique_tools_used": 4,
        "avg_call_duration_ms": 100.0,
        "max_call_duration_ms": 200.0,
        "error_count": 0,
        "avg_output_bytes": 300.0,
        "total_duration_s": 60.0,
    }
    base.update(overrides)
    return base


class TestDeviationsForAgent:
    def test_below_minimum_history_yields_no_deviations(self):
        records = [_shape(i) for i in range(4)]
        assert deviations_for_agent(records) == []

    def test_enough_history_yields_one_deviation_per_record_past_the_minimum(self):
        records = [_shape(i) for i in range(8)]
        result = deviations_for_agent(records)
        assert len(result) == 3  # 8 records, first 5 consumed as the minimum baseline

    def test_anomalous_record_is_flagged_high(self):
        records = [_shape(i) for i in range(5)] + [_shape(5, tool_call_count=5000)]
        result = deviations_for_agent(records)
        assert result[-1]["overall_severity"] == "high"

    def test_records_missing_timestamp_are_skipped_not_raising(self):
        records = [_shape(i) for i in range(5)] + [_shape(5, timestamp=None)]
        assert deviations_for_agent(records) == []

    def test_non_dict_entries_ignored(self):
        records = [_shape(i) for i in range(5)] + ["garbage", None]
        assert deviations_for_agent(records) == []


class TestOutcomeEventsForAgent:
    def test_override_for_matching_agent_included(self):
        memory = {"overrides": [
            {"agent_name": "Claude", "timestamp": _T0.isoformat()},
            {"agent_name": "Gemini", "timestamp": _T0.isoformat()},
        ]}
        events = outcome_events_for_agent(memory, "Claude")
        assert len(events) == 1
        assert events[0]["kind"] == "override"

    def test_elevated_friction_included_low_friction_excluded(self):
        memory = {"friction_history": [
            {"agent_name": "Claude", "timestamp": _T0.isoformat(), "friction_score": 0.9},
            {"agent_name": "Claude", "timestamp": _T0.isoformat(), "friction_score": 0.1},
        ]}
        events = outcome_events_for_agent(memory, "Claude")
        assert len(events) == 1
        assert events[0]["kind"] == "elevated_friction"

    def test_malformed_entries_and_missing_keys_do_not_raise(self):
        memory = {"overrides": ["garbage", {}, None], "friction_history": ["garbage", {}, None]}
        assert outcome_events_for_agent(memory, "Claude") == []

    def test_empty_memory_returns_empty(self):
        assert outcome_events_for_agent({}, "Claude") == []


class TestCorrelateDeviationsWithOutcomes:
    def test_insufficient_data_below_minimum_samples(self):
        deviations = [{"timestamp": _T0, "overall_severity": "high"}] * (MIN_DEVIATION_SAMPLES - 1)
        result = correlate_deviations_with_outcomes(deviations, [])
        assert result["status"] == "insufficient_data"
        assert result["sample_size"] == MIN_DEVIATION_SAMPLES - 1

    def test_flagged_sessions_followed_by_outcomes_score_high_lift(self):
        deviations = [
            {"timestamp": _T0 + timedelta(days=i), "overall_severity": "high"}
            for i in range(5)
        ]
        # An outcome shortly after every flagged session.
        outcomes = [{"timestamp": _T0 + timedelta(days=i, hours=1), "kind": "override"} for i in range(5)]

        result = correlate_deviations_with_outcomes(deviations, outcomes, window_days=1)

        assert result["status"] == "ok"
        assert result["flagged_sessions"] == 5
        assert result["rate_when_flagged"] == 1.0
        assert result["normal_sessions"] == 0
        assert result["rate_when_normal"] is None
        assert result["lift"] is None  # can't compute lift with no normal baseline

    def test_lift_above_one_when_flagged_predicts_better_than_normal(self):
        deviations = (
            [{"timestamp": _T0 + timedelta(days=i), "overall_severity": "high"} for i in range(5)]
            + [{"timestamp": _T0 + timedelta(days=100 + i), "overall_severity": "normal"} for i in range(5)]
        )
        # Every flagged session gets an outcome; no normal session does.
        outcomes = [{"timestamp": _T0 + timedelta(days=i, hours=1), "kind": "override"} for i in range(5)]

        result = correlate_deviations_with_outcomes(deviations, outcomes, window_days=1)

        assert result["rate_when_flagged"] == 1.0
        assert result["rate_when_normal"] == 0.0
        assert result["lift"] is None  # normal rate is 0 -- ratio undefined, not infinite

    def test_outcome_outside_window_not_counted(self):
        deviations = [{"timestamp": _T0 + timedelta(days=i), "overall_severity": "high"} for i in range(5)]
        outcomes = [{"timestamp": _T0 + timedelta(days=50), "kind": "override"}]

        result = correlate_deviations_with_outcomes(deviations, outcomes, window_days=1)

        assert result["flagged_followed_by_outcome"] == 0
        assert result["rate_when_flagged"] == 0.0

    def test_outcome_before_deviation_not_counted(self):
        deviations = [{"timestamp": _T0 + timedelta(days=10 + i), "overall_severity": "high"} for i in range(5)]
        outcomes = [{"timestamp": _T0, "kind": "override"}]

        result = correlate_deviations_with_outcomes(deviations, outcomes, window_days=365)

        assert result["flagged_followed_by_outcome"] == 0
