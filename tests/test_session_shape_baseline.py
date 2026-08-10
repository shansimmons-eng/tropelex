"""
Tests for core.session_shape.baseline — pure functions, no I/O.

Uses pytest, AAA pattern. Extra emphasis on defensive/malformed-input
coverage throughout, since this module explicitly treats session_shapes
records as agent-supplied telemetry rather than fully-trusted internal
data (see the module's own docstring).
"""

from core.session_shape.baseline import (
    MAX_STORED_RECORDS,
    MIN_BASELINE_SESSIONS,
    SHAPE_METRICS,
    _modified_z,
    _severity_for_z,
    classify_deviation,
    compute_baseline,
    filter_records_for_agent,
    latest_deviation_for_agent,
    record_session_shape,
)


def _record(agent="Claude", **overrides):
    base = {
        "agent_name": agent,
        "timestamp": "2026-08-10T00:00:00+00:00",
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


class TestFilterRecordsForAgent:
    def test_empty_records_returns_empty(self):
        assert filter_records_for_agent([], "Claude") == []

    def test_filters_to_matching_agent_only(self):
        records = [_record(agent="Claude"), _record(agent="Gemini"), _record(agent="Claude")]

        result = filter_records_for_agent(records, "Claude")

        assert len(result) == 2
        assert all(r["agent_name"] == "Claude" for r in result)

    def test_normalizes_agent_name_before_matching(self):
        """normalize_agent_name collapses casing/alias variants -- 'claude'
        must match a stored 'Claude' record."""
        records = [_record(agent="Claude")]

        result = filter_records_for_agent(records, "claude")

        assert len(result) == 1

    def test_skips_non_dict_entries_defensively(self):
        records = [_record(agent="Claude"), "corrupted", None, 42]

        result = filter_records_for_agent(records, "Claude")

        assert len(result) == 1


class TestComputeBaseline:
    def test_below_minimum_returns_insufficient_data(self):
        records = [_record() for _ in range(MIN_BASELINE_SESSIONS - 1)]

        result = compute_baseline(records)

        assert result == {
            "status": "insufficient_data",
            "sample_size": MIN_BASELINE_SESSIONS - 1,
            "required": MIN_BASELINE_SESSIONS,
        }

    def test_exactly_minimum_returns_ok(self):
        records = [_record() for _ in range(MIN_BASELINE_SESSIONS)]

        result = compute_baseline(records)

        assert result["status"] == "ok"
        assert result["sample_size"] == MIN_BASELINE_SESSIONS

    def test_all_metrics_present_in_result(self):
        records = [_record() for _ in range(MIN_BASELINE_SESSIONS)]

        result = compute_baseline(records)

        assert set(result["metrics"].keys()) == set(SHAPE_METRICS)
        for metric_stats in result["metrics"].values():
            assert "median" in metric_stats and "mad" in metric_stats

    def test_median_ignores_a_skewed_outlier_unlike_mean_would(self):
        """The whole point of choosing median+MAD over mean+stddev: one
        wildly slow call shouldn't drag the baseline's center toward it."""
        durations = [100.0, 105.0, 95.0, 110.0, 90.0, 5000.0]  # one huge outlier
        records = [_record(avg_call_duration_ms=d) for d in durations]

        result = compute_baseline(records)

        median = result["metrics"]["avg_call_duration_ms"]["median"]
        # Median of [90,95,100,105,110,5000] is (100+105)/2 = 102.5 --
        # nowhere near the mean (~917), proving the outlier didn't drag it.
        assert 95.0 <= median <= 110.0

    def test_empty_records_does_not_raise(self):
        result = compute_baseline([])
        assert result["status"] == "insufficient_data"
        assert result["sample_size"] == 0

    def test_records_missing_a_metric_field_default_to_zero_not_raise(self):
        records = [{"agent_name": "Claude"} for _ in range(MIN_BASELINE_SESSIONS)]

        result = compute_baseline(records)

        assert result["status"] == "ok"
        assert result["metrics"]["tool_call_count"]["median"] == 0.0

    def test_non_numeric_metric_values_default_to_zero_not_raise(self):
        records = [_record(tool_call_count="not a number") for _ in range(MIN_BASELINE_SESSIONS)]

        result = compute_baseline(records)

        assert result["status"] == "ok"
        assert result["metrics"]["tool_call_count"]["median"] == 0.0


class TestModifiedZAndSeverity:
    def test_zero_deviation_from_median_is_zero_z(self):
        assert _modified_z(100.0, 100.0, 10.0, 1.0) == 0.0

    def test_floor_prevents_divide_by_zero_on_flat_history(self):
        # mad=0 (every past value identical) must not raise or return inf
        z = _modified_z(150.0, 100.0, 0.0, floor=50.0)
        assert z == 0.6745 * (150.0 - 100.0) / 50.0

    def test_severity_boundaries_exactly_at_thresholds(self):
        # Just under each threshold -> the lower tier; just at/over -> the next.
        assert _severity_for_z(3.49) == "normal"
        assert _severity_for_z(3.5) == "low"
        assert _severity_for_z(4.99) == "low"
        assert _severity_for_z(5.0) == "medium"
        assert _severity_for_z(7.99) == "medium"
        assert _severity_for_z(8.0) == "high"

    def test_severity_is_symmetric_for_negative_z(self):
        assert _severity_for_z(-6.0) == _severity_for_z(6.0)


class TestClassifyDeviation:
    def _ok_baseline(self):
        records = [_record() for _ in range(MIN_BASELINE_SESSIONS)]
        return compute_baseline(records)

    def test_insufficient_baseline_propagates_as_insufficient_data(self):
        result = classify_deviation(_record(), {"status": "insufficient_data", "sample_size": 2})
        assert result["overall_severity"] == "insufficient_data"
        assert result["metrics"] == {}

    def test_current_matching_baseline_is_normal(self):
        baseline = self._ok_baseline()
        result = classify_deviation(_record(), baseline)
        assert result["overall_severity"] == "normal"

    def test_wildly_different_current_flags_high_on_the_responsible_metric(self):
        baseline = self._ok_baseline()
        anomalous = _record(tool_call_count=1000, max_call_duration_ms=60000.0)

        result = classify_deviation(anomalous, baseline)

        assert result["overall_severity"] == "high"
        assert result["metrics"]["tool_call_count"]["severity"] == "high"

    def test_overall_severity_is_worst_of_any_single_metric(self):
        """Same 'keep the worst' convention as docmine's combined_severity
        (#55) -- one badly-deviated metric shouldn't get averaged away by
        the rest looking normal."""
        baseline = self._ok_baseline()
        one_bad_metric = _record(tool_call_count=1000)  # only this one is extreme

        result = classify_deviation(one_bad_metric, baseline)

        assert result["overall_severity"] == "high"
        assert result["metrics"]["error_count"]["severity"] == "normal"

    def test_none_current_does_not_raise(self):
        baseline = self._ok_baseline()
        result = classify_deviation(None, baseline)
        assert result["overall_severity"] in ("normal", "low", "medium", "high")

    def test_malformed_baseline_does_not_raise(self):
        # A non-dict "metrics" value must not crash -- it degrades to a
        # median=0/mad=0 fallback per metric, so real nonzero values
        # correctly score as deviations rather than "normal" (there's no
        # sane default here that experienced anything but "no baseline").
        result = classify_deviation(_record(), {"status": "ok", "metrics": "not a dict"})
        assert result["overall_severity"] in ("normal", "low", "medium", "high")
        assert set(result["metrics"].keys()) == set(SHAPE_METRICS)


class TestRecordSessionShape:
    def test_appends_entry_and_persists_into_memory(self):
        memory = {}

        memory, result = record_session_shape(memory, "Claude", _record())

        assert len(memory["session_shapes"]) == 1
        assert memory["session_shapes"][0]["agent_name"] == "Claude"
        assert "baseline" in result and "deviation" in result

    def test_new_agent_with_no_history_is_insufficient_data(self):
        memory = {}

        _, result = record_session_shape(memory, "Claude", _record())

        assert result["baseline"]["status"] == "insufficient_data"
        assert result["deviation"]["overall_severity"] == "insufficient_data"

    def test_baseline_excludes_the_record_being_classified(self):
        """Self-inclusion regression: if the record being added were
        included in its own baseline, a single anomalous session could
        never register as a deviation against a history of just itself."""
        memory = {"session_shapes": [_record() for _ in range(MIN_BASELINE_SESSIONS)]}

        _, result = record_session_shape(memory, "Claude", _record(tool_call_count=1000))

        assert result["baseline"]["sample_size"] == MIN_BASELINE_SESSIONS  # prior only
        assert result["deviation"]["overall_severity"] == "high"

    def test_different_agents_get_independent_baselines(self):
        memory = {"session_shapes": [_record(agent="Gemini") for _ in range(MIN_BASELINE_SESSIONS)]}

        # Claude has zero history of their own -- Gemini's history must not count toward it.
        _, result = record_session_shape(memory, "Claude", _record(agent="Claude"))

        assert result["baseline"]["status"] == "insufficient_data"

    def test_cap_at_max_stored_records(self):
        memory = {"session_shapes": [_record() for _ in range(MAX_STORED_RECORDS)]}

        memory, _ = record_session_shape(memory, "Claude", _record())

        assert len(memory["session_shapes"]) == MAX_STORED_RECORDS

    def test_none_current_metrics_does_not_raise(self):
        memory = {}
        memory, result = record_session_shape(memory, "Claude", None)
        assert len(memory["session_shapes"]) == 1

    def test_non_list_session_shapes_in_memory_does_not_raise(self):
        """Defensive against corrupted storage -- a non-list value under
        this key must not crash the write path."""
        memory = {"session_shapes": "corrupted"}

        memory, result = record_session_shape(memory, "Claude", _record())

        assert len(memory["session_shapes"]) == 1


class TestLatestDeviationForAgent:
    def test_no_records_is_insufficient_data(self):
        result = latest_deviation_for_agent([])
        assert result["status"] == "insufficient_data"
        assert result["sample_size"] == 0

    def test_below_minimum_prior_history_is_insufficient_data(self):
        # 5 records total means only 4 prior once the latest is excluded.
        records = [_record() for _ in range(MIN_BASELINE_SESSIONS)]
        result = latest_deviation_for_agent(records)
        assert result["status"] == "insufficient_data"

    def test_enough_history_returns_ok_with_deviation(self):
        records = [_record() for _ in range(MIN_BASELINE_SESSIONS + 1)]

        result = latest_deviation_for_agent(records)

        assert result["status"] == "ok"
        assert result["sample_size"] == MIN_BASELINE_SESSIONS
        assert "deviation" in result

    def test_anomalous_latest_record_is_flagged(self):
        records = [_record() for _ in range(MIN_BASELINE_SESSIONS)] + [_record(tool_call_count=1000)]

        result = latest_deviation_for_agent(records)

        assert result["deviation"]["overall_severity"] == "high"
