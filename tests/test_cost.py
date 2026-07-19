"""
Tests for core.cost — Cost Ledger (models, tracker, router).

Covers pure functions (compute_event_cost, rollup_costs, compute_roi),
tracker class (record, report, trend, rework), and FastAPI router endpoints.
Uses pytest, AAA pattern, all externals mocked, isolated per test.
"""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.cost import (
    CostEvent,
    CostReport,
    DecisionCost,
    Err,
    Ok,
    ROIScore,
    compute_event_cost,
    compute_roi,
    rollup_costs,
)
from core.cost.tracker import (
    CostTracker,
    compute_cost_trend,
    compute_rework_cost,
    get_decision_cost,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _event(
    event_type="agent_time",
    amount=100.0,
    unit="seconds",
    decision_id="d1",
    eid="ev1",
    ts="2026-07-18T00:00:00Z",
    description="test",
    metadata=None,
) -> CostEvent:
    """Create a CostEvent with sensible defaults."""
    return CostEvent(
        id=eid,
        decision_id=decision_id,
        event_type=event_type,
        amount=amount,
        unit=unit,
        description=description,
        timestamp=ts,
        metadata=metadata or {},
    )


def _memory_with_events(events, decisions=None):
    """Build a memory dict containing cost_events and optional decisions."""
    mem: dict = {"cost_events": []}
    for ev in events:
        mem["cost_events"].append({
            "id": ev.id,
            "decision_id": ev.decision_id,
            "event_type": ev.event_type,
            "amount": ev.amount,
            "unit": ev.unit,
            "description": ev.description,
            "timestamp": ev.timestamp,
            "metadata": ev.metadata,
        })
    if decisions is not None:
        mem["decisions"] = decisions
    return mem


def _decay_fn_ok(_ts, reference_count=0, contradiction_count=0):
    """Fake decay function that always returns score=0.7."""
    return {"score": 0.7}


# =========================================================================
# 1. Pure function tests — core/cost/__init__.py
# =========================================================================


class TestComputeEventCost:
    """Tests for compute_event_cost — normalizes events to USD."""

    def test_agent_time(self):
        # Arrange
        ev = _event(event_type="agent_time", amount=1000, unit="seconds")
        # Act
        result = compute_event_cost(ev)
        # Assert
        assert isinstance(result, Ok)
        assert result.value == pytest.approx(1000 * 0.002)

    def test_api_call(self):
        # Arrange
        ev = _event(event_type="api_call", amount=50, unit="calls")
        # Act
        result = compute_event_cost(ev)
        # Assert
        assert isinstance(result, Ok)
        assert result.value == pytest.approx(50 * 0.01)

    def test_rework(self):
        # Arrange
        ev = _event(event_type="rework", amount=10, unit="events")
        # Act
        result = compute_event_cost(ev)
        # Assert
        assert isinstance(result, Ok)
        assert result.value == pytest.approx(10 * 0.05)

    def test_token_usage(self):
        # Arrange
        ev = _event(event_type="token_usage", amount=50000, unit="tokens")
        # Act
        result = compute_event_cost(ev)
        # Assert
        assert isinstance(result, Ok)
        assert result.value == pytest.approx(50000 * 0.000002)

    def test_unknown_event_type(self):
        # Arrange
        ev = _event(event_type="unknown_type", amount=10, unit="x")
        # Act
        result = compute_event_cost(ev)
        # Assert
        assert isinstance(result, Err)
        assert result.code == "VALIDATION_ERROR"
        assert "unknown_type" in result.error

    def test_negative_amount(self):
        # Arrange
        ev = _event(event_type="agent_time", amount=-5, unit="seconds")
        # Act
        result = compute_event_cost(ev)
        # Assert
        assert isinstance(result, Err)
        assert result.code == "VALIDATION_ERROR"
        assert "non-negative" in result.error

    def test_zero_amount(self):
        # Arrange
        ev = _event(event_type="api_call", amount=0, unit="calls")
        # Act
        result = compute_event_cost(ev)
        # Assert
        assert isinstance(result, Ok)
        assert result.value == 0.0


class TestRollupCosts:
    """Tests for rollup_costs — groups events by decision_id."""

    def test_groups_and_sums(self):
        # Arrange
        events = [
            _event(event_type="agent_time", amount=100, decision_id="d1"),
            _event(event_type="api_call", amount=10, decision_id="d1", eid="ev2"),
            _event(event_type="agent_time", amount=200, decision_id="d2", eid="ev3"),
        ]
        # Act
        result = rollup_costs(events)
        # Assert
        assert isinstance(result, Ok)
        assert len(result.value) == 2
        d1 = result.value["d1"]
        assert d1.event_count == 2
        assert d1.total_cost_usd == pytest.approx(100 * 0.002 + 10 * 0.01)
        d2 = result.value["d2"]
        assert d2.event_count == 1
        assert d2.total_cost_usd == pytest.approx(200 * 0.002)

    def test_empty_events(self):
        # Arrange
        events: list[CostEvent] = []
        # Act
        result = rollup_costs(events)
        # Assert
        assert isinstance(result, Ok)
        assert result.value == {}

    def test_token_and_rework_tracking(self):
        # Arrange
        events = [
            _event(event_type="token_usage", amount=1000, unit="tokens", decision_id="d1"),
            _event(event_type="rework", amount=5, unit="events", decision_id="d1", eid="ev2"),
        ]
        # Act
        result = rollup_costs(events)
        # Assert
        assert isinstance(result, Ok)
        d1 = result.value["d1"]
        assert d1.total_tokens == 1000
        assert d1.reversal_cost == pytest.approx(5 * 0.05)

    def test_with_decisions_mapping(self):
        # Arrange
        events = [_event(event_type="agent_time", amount=100, decision_id="d1")]
        decisions = {"d1": "Use FastAPI"}
        # Act
        result = rollup_costs(events, decisions)
        # Assert
        assert isinstance(result, Ok)
        assert result.value["d1"].decision_text == "Use FastAPI"

    def test_propagates_event_error(self):
        # Arrange
        events = [_event(event_type="bogus", amount=10, decision_id="d1")]
        # Act
        result = rollup_costs(events)
        # Assert
        assert isinstance(result, Err)
        assert result.code == "VALIDATION_ERROR"


class TestComputeROI:
    """Tests for compute_roi — ROI = impact / cost."""

    def test_normal_roi(self):
        # Arrange
        dc = DecisionCost(
            decision_id="d1", decision_text="",
            total_cost_usd=10.0, total_tokens=0,
            event_count=1, reversal_cost=0.0,
        )
        # Act
        result = compute_roi(dc, impact_score=5.0)
        # Assert
        assert isinstance(result, Ok)
        assert result.value.roi == pytest.approx(0.5)
        assert result.value.cost == 10.0
        assert result.value.impact_score == 5.0

    def test_zero_cost_returns_zero_roi(self):
        # Arrange
        dc = DecisionCost(
            decision_id="d1", decision_text="",
            total_cost_usd=0.0, total_tokens=0,
            event_count=0, reversal_cost=0.0,
        )
        # Act
        result = compute_roi(dc, impact_score=5.0)
        # Assert
        assert isinstance(result, Ok)
        assert result.value.roi == 0.0

    def test_negative_cost_err(self):
        # Arrange
        dc = DecisionCost(
            decision_id="d1", decision_text="",
            total_cost_usd=-1.0, total_tokens=0,
            event_count=0, reversal_cost=0.0,
        )
        # Act
        result = compute_roi(dc, impact_score=1.0)
        # Assert
        assert isinstance(result, Err)
        assert "non-negative" in result.error

    def test_negative_impact_err(self):
        # Arrange
        dc = DecisionCost(
            decision_id="d1", decision_text="",
            total_cost_usd=5.0, total_tokens=0,
            event_count=1, reversal_cost=0.0,
        )
        # Act
        result = compute_roi(dc, impact_score=-1.0)
        # Assert
        assert isinstance(result, Err)
        assert "non-negative" in result.error


# =========================================================================
# 2. Pure function tests — core/cost/tracker.py
# =========================================================================


class TestGetDecisionCost:
    """Tests for get_decision_cost — filters and rolls up for one decision."""

    def test_filters_correctly(self):
        # Arrange
        events = [
            _event(event_type="agent_time", amount=100, decision_id="d1"),
            _event(event_type="agent_time", amount=200, decision_id="d2", eid="ev2"),
            _event(event_type="rework", amount=5, decision_id="d1", eid="ev3"),
        ]
        # Act
        result = get_decision_cost("d1", events)
        # Assert
        assert result.decision_id == "d1"
        assert result.event_count == 2
        assert result.total_cost_usd == pytest.approx(100 * 0.002 + 5 * 0.05)
        assert result.reversal_cost == pytest.approx(5 * 0.05)

    def test_no_matching_events(self):
        # Arrange
        events = [_event(event_type="agent_time", amount=100, decision_id="d1")]
        # Act
        result = get_decision_cost("d99", events)
        # Assert
        assert result.total_cost_usd == 0.0
        assert result.event_count == 0
        assert result.total_tokens == 0

    def test_token_counting(self):
        # Arrange
        events = [
            _event(event_type="token_usage", amount=5000, unit="tokens", decision_id="d1"),
            _event(event_type="token_usage", amount=3000, unit="tokens", decision_id="d1", eid="ev2"),
        ]
        # Act
        result = get_decision_cost("d1", events)
        # Assert
        assert result.total_tokens == 8000


class TestComputeReworkCost:
    """Tests for compute_rework_cost — sums rework event costs."""

    def test_sums_rework_only(self):
        # Arrange
        events = [
            _event(event_type="rework", amount=10, decision_id="d1"),
            _event(event_type="agent_time", amount=100, decision_id="d1", eid="ev2"),
            _event(event_type="rework", amount=20, decision_id="d1", eid="ev3"),
        ]
        # Act
        result = compute_rework_cost(events)
        # Assert
        assert result == pytest.approx(30 * 0.05)

    def test_no_rework_events(self):
        # Arrange
        events = [_event(event_type="agent_time", amount=100, decision_id="d1")]
        # Act
        result = compute_rework_cost(events)
        # Assert
        assert result == 0.0

    def test_empty_list(self):
        # Arrange/Act
        result = compute_rework_cost([])
        # Assert
        assert result == 0.0


class TestComputeCostTrend:
    """Tests for compute_cost_trend — groups events by day."""

    def test_groups_by_day(self):
        # Arrange
        events = [
            _event(event_type="agent_time", amount=100, decision_id="d1", ts="2026-07-18T10:00:00Z"),
            _event(event_type="api_call", amount=10, decision_id="d1", eid="ev2", ts="2026-07-18T14:00:00Z"),
            _event(event_type="agent_time", amount=200, decision_id="d1", eid="ev3", ts="2026-07-19T09:00:00Z"),
        ]
        # Act
        result = compute_cost_trend(events)
        # Assert
        assert len(result) == 2
        assert result[0]["date"] == "2026-07-18"
        assert result[0]["event_count"] == 2
        assert result[0]["total_cost"] == pytest.approx(100 * 0.002 + 10 * 0.01)
        assert result[1]["date"] == "2026-07-19"
        assert result[1]["event_count"] == 1

    def test_empty_events(self):
        # Arrange/Act
        result = compute_cost_trend([])
        # Assert
        assert result == []

    def test_single_event(self):
        # Arrange
        events = [_event(event_type="agent_time", amount=50, decision_id="d1", ts="2026-07-18T12:00:00Z")]
        # Act
        result = compute_cost_trend(events)
        # Assert
        assert len(result) == 1
        assert result[0]["date"] == "2026-07-18"
        assert result[0]["event_count"] == 1
        assert result[0]["total_cost"] == pytest.approx(50 * 0.002)


# =========================================================================
# 3. CostTracker class tests — IO boundary with mocked MemoryManager
# =========================================================================


class TestCostTrackerRecordEvent:
    """Tests for CostTracker.record_cost_event."""

    def test_success(self):
        # Arrange
        mock_mm = MagicMock()
        mock_mm.get_project_memory.return_value = {"cost_events": []}
        tracker = CostTracker(decision_tree=MagicMock(), memory_manager=mock_mm)
        ev = _event(event_type="agent_time", amount=50, decision_id="d1", eid="")
        # Act
        result = tracker.record_cost_event("proj", ev)
        # Assert
        assert result.event_type == "agent_time"
        assert result.amount == 50
        assert result.id  # auto-generated
        mock_mm.save_project_memory.assert_called_once()

    def test_validation_error_negative_amount(self):
        # Arrange
        tracker = CostTracker(decision_tree=MagicMock(), memory_manager=MagicMock())
        ev = _event(event_type="agent_time", amount=-1, decision_id="d1")
        # Act / Assert
        with pytest.raises(Exception) as exc_info:
            tracker.record_cost_event("proj", ev)
        assert "non-negative" in str(exc_info.value)

    def test_validation_error_empty_event_type(self):
        # Arrange
        tracker = CostTracker(decision_tree=MagicMock(), memory_manager=MagicMock())
        ev = _event(event_type="", amount=10, decision_id="d1")
        # Act / Assert
        with pytest.raises(Exception) as exc_info:
            tracker.record_cost_event("proj", ev)
        assert "event_type" in str(exc_info.value)

    def test_validation_error_empty_decision_id(self):
        # Arrange
        tracker = CostTracker(decision_tree=MagicMock(), memory_manager=MagicMock())
        ev = _event(event_type="agent_time", amount=10, decision_id="")
        # Act / Assert
        with pytest.raises(Exception) as exc_info:
            tracker.record_cost_event("proj", ev)
        assert "decision_id" in str(exc_info.value)

    def test_io_error_on_save(self):
        # Arrange
        mock_mm = MagicMock()
        mock_mm.get_project_memory.return_value = {"cost_events": []}
        mock_mm.save_project_memory.side_effect = OSError("disk full")
        tracker = CostTracker(decision_tree=MagicMock(), memory_manager=mock_mm)
        ev = _event(event_type="agent_time", amount=10, decision_id="d1")
        # Act / Assert
        with pytest.raises(Exception) as exc_info:
            tracker.record_cost_event("proj", ev)
        assert "disk full" in str(exc_info.value)


class TestCostTrackerGenerateReport:
    """Tests for CostTracker.generate_cost_report."""

    def test_full_report(self):
        # Arrange
        events = [
            _event(event_type="agent_time", amount=100, decision_id="d1"),
            _event(event_type="rework", amount=5, decision_id="d1", eid="ev2"),
        ]
        memory = _memory_with_events(events, decisions=[{"id": "d1", "decision": "Use FastAPI"}])
        mock_mm = MagicMock()
        mock_mm.get_project_memory.return_value = memory
        tree = MagicMock()
        tree.get_decision.return_value = {"id": "d1", "timestamp": "2026-07-01T00:00:00Z"}
        tree.get_descendants.return_value = []
        tracker = CostTracker(decision_tree=tree, decay_fn=_decay_fn_ok, memory_manager=mock_mm)
        # Act
        report = tracker.generate_cost_report("proj")
        # Assert
        assert report.project == "proj"
        assert report.total_cost_usd > 0
        assert len(report.cost_per_decision) == 1
        assert report.cost_per_decision[0].decision_id == "d1"
        assert report.rework_costs > 0
        assert len(report.roi_scores) == 1

    def test_empty_report(self):
        # Arrange
        memory = _memory_with_events([], decisions=[])
        mock_mm = MagicMock()
        mock_mm.get_project_memory.return_value = memory
        tracker = CostTracker(decision_tree=MagicMock(), memory_manager=mock_mm)
        # Act
        report = tracker.generate_cost_report("proj")
        # Assert
        assert report.total_cost_usd == 0.0
        assert report.cost_per_decision == []
        assert report.roi_scores == []
        assert report.period == "no events"

    def test_io_error_on_load(self):
        # Arrange
        mock_mm = MagicMock()
        mock_mm.get_project_memory.side_effect = OSError("file not found")
        tracker = CostTracker(decision_tree=MagicMock(), memory_manager=mock_mm)
        # Act / Assert
        with pytest.raises(Exception) as exc_info:
            tracker.generate_cost_report("proj")
        assert "file not found" in str(exc_info.value)


class TestCostTrackerTrendAndRework:
    """Additional tracker pure-function coverage."""

    def test_trend_groups_by_day(self):
        # Arrange
        events = [
            _event(event_type="agent_time", amount=100, decision_id="d1", ts="2026-07-18T10:00:00Z"),
            _event(event_type="api_call", amount=20, decision_id="d1", eid="ev2", ts="2026-07-18T15:00:00Z"),
            _event(event_type="agent_time", amount=200, decision_id="d1", eid="ev3", ts="2026-07-19T10:00:00Z"),
        ]
        # Act
        trend = compute_cost_trend(events)
        # Assert
        assert len(trend) == 2
        assert trend[0]["date"] == "2026-07-18"
        assert trend[0]["event_count"] == 2
        assert trend[1]["date"] == "2026-07-19"

    def test_rework_sums_only_rework(self):
        # Arrange
        events = [
            _event(event_type="rework", amount=3, decision_id="d1"),
            _event(event_type="rework", amount=7, decision_id="d1", eid="ev2"),
            _event(event_type="agent_time", amount=100, decision_id="d1", eid="ev3"),
        ]
        # Act
        result = compute_rework_cost(events)
        # Assert
        assert result == pytest.approx(10 * 0.05)


# =========================================================================
# 4. Router tests — FastAPI endpoints via TestClient
# =========================================================================


@pytest.fixture()
def _patch_router(monkeypatch):
    """Shared fixture that patches router helpers per test."""
    import core.cost.router as router_mod

    patches = {}

    def set_memory(data, project="test-proj"):
        def fake_load(p):
            if p != project:
                from fastapi import HTTPException
                raise HTTPException(status_code=404, detail=f"Project '{p}' not found")
            return data
        monkeypatch.setattr(router_mod, "_load_memory", fake_load)

    patches["set_memory"] = set_memory
    return patches


class TestRouterRecordCost:
    """Tests for POST /{project}/cost/record."""

    def test_success(self, _patch_router, tmp_path):
        # Arrange
        import core.cost.router as router_mod
        original = router_mod.BASE_DIR
        router_mod.BASE_DIR = tmp_path

        memory = _memory_with_events([], decisions=[{"id": "d1", "decision": "test"}])
        _patch_router["set_memory"](memory)

        app = FastAPI()
        app.include_router(router_mod.cost_router)
        client = TestClient(app, raise_server_exceptions=False)

        body = {
            "decision_id": "d1",
            "event_type": "agent_time",
            "amount": 100.0,
            "unit": "seconds",
            "description": "coding",
        }
        # Act
        resp = client.post("/api/memory/test-proj/cost/record", json=body)
        # Assert
        assert resp.status_code == 200
        data = resp.json()
        assert data["event_type"] == "agent_time"
        assert data["amount"] == 100.0
        assert data["decision_id"] == "d1"
        assert "id" in data

        router_mod.BASE_DIR = original

    def test_missing_project_404(self, _patch_router, tmp_path):
        # Arrange
        import core.cost.router as router_mod
        original = router_mod.BASE_DIR
        router_mod.BASE_DIR = tmp_path

        _patch_router["set_memory"]({}, project="other")

        app = FastAPI()
        app.include_router(router_mod.cost_router)
        client = TestClient(app, raise_server_exceptions=False)

        body = {
            "decision_id": "d1",
            "event_type": "agent_time",
            "amount": 10.0,
            "unit": "seconds",
        }
        # Act
        resp = client.post("/api/memory/missing-proj/cost/record", json=body)
        # Assert
        assert resp.status_code == 404

        router_mod.BASE_DIR = original

    def test_validation_error_422(self, _patch_router, tmp_path):
        # Arrange — invalid request body (missing required fields)
        import core.cost.router as router_mod
        original = router_mod.BASE_DIR
        router_mod.BASE_DIR = tmp_path

        memory = _memory_with_events([], decisions=[{"id": "d1", "decision": "test"}])
        _patch_router["set_memory"](memory)

        app = FastAPI()
        app.include_router(router_mod.cost_router)
        client = TestClient(app, raise_server_exceptions=False)

        # Act — missing decision_id
        resp = client.post("/api/memory/test-proj/cost/record", json={
            "event_type": "agent_time",
            "amount": 10.0,
            "unit": "seconds",
        })
        # Assert
        assert resp.status_code == 422

        router_mod.BASE_DIR = original


class TestRouterCostReport:
    """Tests for GET /{project}/cost/report."""

    def test_success(self, _patch_router, tmp_path):
        # Arrange
        import core.cost.router as router_mod
        original = router_mod.BASE_DIR
        router_mod.BASE_DIR = tmp_path

        events = [_event(event_type="agent_time", amount=100, decision_id="d1")]
        memory = _memory_with_events(events, decisions=[{"id": "d1", "decision": "Use FastAPI"}])
        _patch_router["set_memory"](memory)

        app = FastAPI()
        app.include_router(router_mod.cost_router)
        client = TestClient(app, raise_server_exceptions=False)
        # Act
        resp = client.get("/api/memory/test-proj/cost/report")
        # Assert
        assert resp.status_code == 200
        data = resp.json()
        assert data["project"] == "test-proj"
        assert data["total_cost_usd"] > 0
        assert isinstance(data["cost_per_decision"], list)
        assert isinstance(data["roi_scores"], list)
        assert "period" in data

        router_mod.BASE_DIR = original

    def test_empty_report(self, _patch_router, tmp_path):
        # Arrange
        import core.cost.router as router_mod
        original = router_mod.BASE_DIR
        router_mod.BASE_DIR = tmp_path

        memory = _memory_with_events([], decisions=[])
        _patch_router["set_memory"](memory)

        app = FastAPI()
        app.include_router(router_mod.cost_router)
        client = TestClient(app, raise_server_exceptions=False)
        # Act
        resp = client.get("/api/memory/test-proj/cost/report")
        # Assert
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_cost_usd"] == 0.0
        assert data["cost_per_decision"] == []
        assert data["period"] == "no events"

        router_mod.BASE_DIR = original


class TestRouterDecisionCost:
    """Tests for GET /{project}/cost/decision/{decision_id}."""

    def test_success(self, _patch_router, tmp_path):
        # Arrange
        import core.cost.router as router_mod
        original = router_mod.BASE_DIR
        router_mod.BASE_DIR = tmp_path

        events = [_event(event_type="agent_time", amount=100, decision_id="d1")]
        memory = _memory_with_events(events, decisions=[{"id": "d1", "decision": "Use FastAPI"}])
        _patch_router["set_memory"](memory)

        app = FastAPI()
        app.include_router(router_mod.cost_router)
        client = TestClient(app, raise_server_exceptions=False)
        # Act
        resp = client.get("/api/memory/test-proj/cost/decision/d1")
        # Assert
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision_id"] == "d1"
        assert "direct_cost" in data
        assert data["direct_cost"]["decision_id"] == "d1"
        assert data["direct_cost"]["total_cost_usd"] > 0
        assert "ancestor_costs" in data
        assert "descendant_costs" in data

        router_mod.BASE_DIR = original

    def test_not_found_404(self, _patch_router, tmp_path):
        # Arrange
        import core.cost.router as router_mod
        original = router_mod.BASE_DIR
        router_mod.BASE_DIR = tmp_path

        memory = _memory_with_events([], decisions=[{"id": "d1", "decision": "test"}])
        _patch_router["set_memory"](memory)

        app = FastAPI()
        app.include_router(router_mod.cost_router)
        client = TestClient(app, raise_server_exceptions=False)
        # Act
        resp = client.get("/api/memory/test-proj/cost/decision/nonexistent")
        # Assert
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

        router_mod.BASE_DIR = original

    def test_missing_project_404(self, _patch_router, tmp_path):
        # Arrange
        import core.cost.router as router_mod
        original = router_mod.BASE_DIR
        router_mod.BASE_DIR = tmp_path

        _patch_router["set_memory"]({}, project="other")

        app = FastAPI()
        app.include_router(router_mod.cost_router)
        client = TestClient(app, raise_server_exceptions=False)
        # Act
        resp = client.get("/api/memory/missing-proj/cost/decision/d1")
        # Assert
        assert resp.status_code == 404

        router_mod.BASE_DIR = original
