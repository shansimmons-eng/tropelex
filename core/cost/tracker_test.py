"""Tests for core.cost.tracker — cost tracking with DecisionTree traversal and decay weighting."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any
from unittest.mock import MagicMock

from core.cost import CostEvent, CostError, Ok, Err
from core.cost.tracker import (
    CostTracker,
    get_decision_cost,
    compute_rework_cost,
    compute_cost_trend,
    _validate_event,
    _ensure_id,
    _extract_decisions,
    _load_events,
    _compute_period,
)
from core.decision_tree import DecisionTree


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event(
    decision_id: str = "d1",
    event_type: str = "agent_time",
    amount: float = 100.0,
    unit: str = "seconds",
    description: str = "test event",
    event_id: str = "ev1",
    timestamp: str | None = None,
) -> CostEvent:
    return CostEvent(
        id=event_id,
        decision_id=decision_id,
        event_type=event_type,
        amount=amount,
        unit=unit,
        description=description,
        timestamp=timestamp or _now_iso(),
    )


def _rework_event(decision_id: str = "d1", amount: float = 50.0) -> CostEvent:
    return _event(
        decision_id=decision_id,
        event_type="rework",
        amount=amount,
        unit="seconds",
        description="rework event",
    )


def _token_event(decision_id: str = "d1", amount: float = 1000.0) -> CostEvent:
    return _event(
        decision_id=decision_id,
        event_type="token_usage",
        amount=amount,
        unit="tokens",
        description="token usage",
    )


def _mock_memory_manager(events: list[dict] | None = None, decisions: list[dict] | None = None) -> MagicMock:
    """Create a mock MemoryManager with preset data."""
    mm = MagicMock()
    memory = {
        "cost_events": events or [],
        "decisions": decisions or [],
    }
    mm.get_project_memory.return_value = memory
    return mm


def _empty_tree() -> DecisionTree:
    return DecisionTree()


# ---------------------------------------------------------------------------
# _validate_event (pure)
# ---------------------------------------------------------------------------

class TestValidateEvent:
    def test_valid_event_passes(self):
        event = _event()
        result = _validate_event(event)
        assert result is event

    def test_negative_amount_raises(self):
        event = _event(amount=-5.0)
        try:
            _validate_event(event)
            assert False, "Should have raised CostError"
        except CostError as e:
            assert e.code == "VALIDATION_ERROR"
            assert "non-negative" in str(e)

    def test_empty_event_type_raises(self):
        event = _event(event_type="")
        try:
            _validate_event(event)
            assert False, "Should have raised CostError"
        except CostError as e:
            assert e.code == "VALIDATION_ERROR"
            assert "event_type" in str(e)

    def test_empty_decision_id_raises(self):
        event = _event(decision_id="")
        try:
            _validate_event(event)
            assert False, "Should have raised CostError"
        except CostError as e:
            assert e.code == "VALIDATION_ERROR"
            assert "decision_id" in str(e)


# ---------------------------------------------------------------------------
# _ensure_id (pure)
# ---------------------------------------------------------------------------

class TestEnsureId:
    def test_existing_id_preserved(self):
        event = _event(event_id="custom-id")
        result = _ensure_id(event)
        assert result.id == "custom-id"

    def test_empty_id_generates_hash(self):
        event = CostEvent(
            id="",
            decision_id="d1",
            event_type="agent_time",
            amount=100.0,
            unit="seconds",
            description="test",
            timestamp=_now_iso(),
        )
        result = _ensure_id(event)
        assert result.id != ""
        assert len(result.id) == 12  # sha256 hex[:12]


# ---------------------------------------------------------------------------
# get_decision_cost (pure)
# ---------------------------------------------------------------------------

class TestGetDecisionCost:
    def test_empty_events(self):
        dc = get_decision_cost("d1", [])
        assert dc.decision_id == "d1"
        assert dc.total_cost_usd == 0.0
        assert dc.event_count == 0

    def test_filters_by_decision_id(self):
        events = [_event(decision_id="d1"), _event(decision_id="d2", event_id="ev2")]
        dc = get_decision_cost("d1", events)
        assert dc.event_count == 1

    def test_sums_usd_costs(self):
        events = [_event(decision_id="d1", amount=100.0), _event(decision_id="d1", amount=200.0, event_id="ev2")]
        dc = get_decision_cost("d1", events)
        # agent_time rate = 0.002, so 100*0.002 + 200*0.002 = 0.6
        assert dc.total_cost_usd == 0.6

    def test_counts_tokens(self):
        events = [_token_event(decision_id="d1", amount=500.0)]
        dc = get_decision_cost("d1", events)
        assert dc.total_tokens == 500

    def test_rework_cost_separated(self):
        events = [_event(decision_id="d1"), _rework_event(decision_id="d1", amount=50.0)]
        dc = get_decision_cost("d1", events)
        assert dc.reversal_cost > 0.0

    def test_no_matching_events_returns_zero(self):
        events = [_event(decision_id="d2")]
        dc = get_decision_cost("d1", events)
        assert dc.total_cost_usd == 0.0
        assert dc.event_count == 0


# ---------------------------------------------------------------------------
# compute_rework_cost (pure)
# ---------------------------------------------------------------------------

class TestComputeReworkCost:
    def test_empty_events(self):
        assert compute_rework_cost([]) == 0.0

    def test_no_rework_events(self):
        events = [_event(), _event(event_id="ev2")]
        assert compute_rework_cost(events) == 0.0

    def test_sums_rework_costs(self):
        events = [_rework_event(amount=100.0), _rework_event(amount=200.0)]
        total = compute_rework_cost(events)
        # rework rate = 0.05, so 100*0.05 + 200*0.05 = 15.0
        assert total == 15.0

    def test_ignores_non_rework_events(self):
        events = [_event(amount=1000.0), _rework_event(amount=50.0)]
        total = compute_rework_cost(events)
        assert total == 50.0 * 0.05


# ---------------------------------------------------------------------------
# compute_cost_trend (pure)
# ---------------------------------------------------------------------------

class TestComputeCostTrend:
    def test_empty_events(self):
        assert compute_cost_trend([]) == []

    def test_groups_by_day(self):
        ts1 = "2026-01-15T10:00:00+00:00"
        ts2 = "2026-01-15T14:00:00+00:00"
        ts3 = "2026-01-16T10:00:00+00:00"
        events = [
            _event(timestamp=ts1, amount=100.0, event_id="ev1"),
            _event(timestamp=ts2, amount=200.0, event_id="ev2"),
            _event(timestamp=ts3, amount=300.0, event_id="ev3"),
        ]
        trend = compute_cost_trend(events)
        assert len(trend) == 2
        assert trend[0]["date"] == "2026-01-15"
        assert trend[0]["event_count"] == 2
        assert trend[1]["date"] == "2026-01-16"
        assert trend[1]["event_count"] == 1

    def test_sorted_by_date(self):
        ts1 = "2026-03-01T10:00:00+00:00"
        ts2 = "2026-01-01T10:00:00+00:00"
        events = [_event(timestamp=ts1, event_id="ev1"), _event(timestamp=ts2, event_id="ev2")]
        trend = compute_cost_trend(events)
        assert trend[0]["date"] == "2026-01-01"
        assert trend[1]["date"] == "2026-03-01"

    def test_cost_rounded(self):
        events = [_event(amount=33.333333)]
        trend = compute_cost_trend(events)
        assert len(trend) == 1
        # Check rounding to 6 decimal places
        cost = trend[0]["total_cost"]
        assert cost == round(cost, 6)


# ---------------------------------------------------------------------------
# _extract_decisions (pure)
# ---------------------------------------------------------------------------

class TestExtractDecisions:
    def test_empty_memory(self):
        assert _extract_decisions({}) == {}

    def test_maps_id_to_decision(self):
        memory = {"decisions": [{"id": "d1", "decision": "use fastapi"}, {"id": "d2", "decision": "use postgres"}]}
        result = _extract_decisions(memory)
        assert result == {"d1": "use fastapi", "d2": "use postgres"}

    def test_missing_id_uses_empty_string(self):
        memory = {"decisions": [{"decision": "no id"}]}
        result = _extract_decisions(memory)
        assert "" in result


# ---------------------------------------------------------------------------
# _load_events (pure)
# ---------------------------------------------------------------------------

class TestLoadEvents:
    def test_empty_memory(self):
        assert _load_events({}) == []

    def test_deserializes_events(self):
        memory = {"cost_events": [{"id": "ev1", "decision_id": "d1", "event_type": "agent_time", "amount": 100.0, "unit": "seconds", "description": "test", "timestamp": _now_iso(), "metadata": {}}]}
        events = _load_events(memory)
        assert len(events) == 1
        assert isinstance(events[0], CostEvent)
        assert events[0].id == "ev1"


# ---------------------------------------------------------------------------
# _compute_period (pure)
# ---------------------------------------------------------------------------

class TestComputePeriod:
    def test_empty_events(self):
        assert _compute_period([]) == "no events"

    def test_single_event(self):
        events = [_event(timestamp="2026-01-15T10:00:00+00:00")]
        assert _compute_period(events) == "2026-01-15T10:00:00+00:00 to 2026-01-15T10:00:00+00:00"

    def test_range(self):
        events = [
            _event(timestamp="2026-01-01T00:00:00+00:00", event_id="ev1"),
            _event(timestamp="2026-06-30T00:00:00+00:00", event_id="ev2"),
        ]
        period = _compute_period(events)
        assert "2026-01-01" in period
        assert "2026-06-30" in period


# ---------------------------------------------------------------------------
# CostTracker class
# ---------------------------------------------------------------------------

class TestCostTrackerInit:
    def test_default_dependencies(self):
        tree = DecisionTree()
        tracker = CostTracker(decision_tree=tree)
        assert tracker._tree is tree
        assert tracker._decay_fn is not None

    def test_injected_decay_fn(self):
        tree = DecisionTree()
        custom_decay = lambda ts, **kw: {"score": 0.99}
        tracker = CostTracker(decision_tree=tree, decay_fn=custom_decay)
        assert tracker._decay_fn is custom_decay

    def test_injected_memory_manager(self):
        tree = DecisionTree()
        mm = MagicMock()
        tracker = CostTracker(decision_tree=tree, memory_manager=mm)
        assert tracker._mm is mm


class TestCostTrackerRecordCostEvent:
    def test_records_event(self):
        mm = _mock_memory_manager()
        tracker = CostTracker(decision_tree=_empty_tree(), memory_manager=mm)
        event = _event()
        result = tracker.record_cost_event("test-project", event)
        assert isinstance(result, CostEvent)
        mm.save_project_memory.assert_called_once()

    def test_validates_negative_amount(self):
        mm = _mock_memory_manager()
        tracker = CostTracker(decision_tree=_empty_tree(), memory_manager=mm)
        event = _event(amount=-5.0)
        try:
            tracker.record_cost_event("test-project", event)
            assert False, "Should have raised CostError"
        except CostError as e:
            assert e.code == "VALIDATION_ERROR"

    def test_assigns_id_if_missing(self):
        mm = _mock_memory_manager()
        tracker = CostTracker(decision_tree=_empty_tree(), memory_manager=mm)
        event = CostEvent(
            id="", decision_id="d1", event_type="agent_time",
            amount=100.0, unit="seconds", description="test",
            timestamp=_now_iso(),
        )
        result = tracker.record_cost_event("test-project", event)
        assert result.id != ""

    def test_io_error_raises_cost_error(self):
        mm = MagicMock()
        mm.get_project_memory.return_value = {}
        mm.save_project_memory.side_effect = OSError("disk full")
        tracker = CostTracker(decision_tree=_empty_tree(), memory_manager=mm)
        try:
            tracker.record_cost_event("test-project", _event())
            assert False, "Should have raised CostError"
        except CostError as e:
            assert e.code == "IO_ERROR"


class TestCostTrackerGenerateCostReport:
    def test_empty_project(self):
        mm = _mock_memory_manager()
        tracker = CostTracker(decision_tree=_empty_tree(), memory_manager=mm)
        report = tracker.generate_cost_report("test-project")
        assert report.project == "test-project"
        assert report.total_cost_usd == 0.0
        assert report.cost_per_decision == []

    def test_with_events(self):
        events_dict = [_event_to_dict(_event(decision_id="d1"))]
        decisions = [{"id": "d1", "decision": "use fastapi"}]
        mm = _mock_memory_manager(events=events_dict, decisions=decisions)
        tracker = CostTracker(decision_tree=_empty_tree(), memory_manager=mm)
        report = tracker.generate_cost_report("test-project")
        assert report.total_cost_usd > 0.0
        assert len(report.cost_per_decision) == 1

    def test_io_error_raises_cost_error(self):
        mm = MagicMock()
        mm.get_project_memory.side_effect = OSError("permission denied")
        tracker = CostTracker(decision_tree=_empty_tree(), memory_manager=mm)
        try:
            tracker.generate_cost_report("test-project")
            assert False, "Should have raised CostError"
        except CostError as e:
            assert e.code == "IO_ERROR"


class TestCostTrackerApplyDecayWeighting:
    def test_weights_costs(self):
        costs = {"d1": 100.0, "d2": 200.0}
        decay = {"d1": 0.5, "d2": 0.8}
        result = CostTracker.apply_decay_weighting(costs, decay)
        assert result["d1"] == 50.0
        assert result["d2"] == 160.0

    def test_missing_decay_defaults_to_one(self):
        costs = {"d1": 100.0}
        result = CostTracker.apply_decay_weighting(costs, {})
        assert result["d1"] == 100.0

    def test_empty_inputs(self):
        assert CostTracker.apply_decay_weighting({}, {}) == {}


class TestCostTrackerTraceDecisionCost:
    def test_returns_triple_costs(self):
        events_dict = [_event_to_dict(_event(decision_id="d1"))]
        mm = _mock_memory_manager(events=events_dict)
        tree = DecisionTree()
        tree.add_decision({"id": "d1", "decision": "use fastapi"})
        tracker = CostTracker(decision_tree=tree, memory_manager=mm)
        result = tracker.trace_decision_cost("test-project", "d1")
        assert "direct_cost" in result
        assert "ancestor_costs" in result
        assert "descendant_costs" in result
        assert result["decision_id"] == "d1"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _event_to_dict(event: CostEvent) -> dict[str, Any]:
    """Serialize CostEvent to dict (matches tracker._event_to_dict)."""
    return {
        "id": event.id,
        "decision_id": event.decision_id,
        "event_type": event.event_type,
        "amount": event.amount,
        "unit": event.unit,
        "description": event.description,
        "timestamp": event.timestamp,
        "metadata": event.metadata,
    }
