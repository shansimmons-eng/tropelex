"""
Tests for Live Telemetry — in-memory ring-buffer event log.

Covers _emit_telemetry, ring-buffer eviction at maxlen=200, and the
GET /api/telemetry/recent polling endpoint's since_id cursor behavior.
"""

from __future__ import annotations

from itertools import count

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import core.telemetry as telemetry_module
from core.telemetry import _emit_telemetry, telemetry_router


@pytest.fixture(autouse=True)
def _isolated_telemetry_state():
    """Reset the module-level ring buffer and id sequence around each test.

    Both are plain module globals shared process-wide (matching the
    _rate_limits reset pattern in tests/conftest.py) — without this,
    tests would see ids/events left over from whichever test ran first.
    """
    telemetry_module._telemetry_log.clear()
    telemetry_module._telemetry_seq = count(1)
    yield
    telemetry_module._telemetry_log.clear()
    telemetry_module._telemetry_seq = count(1)


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(telemetry_router)
    return TestClient(app)


class TestEmitTelemetry:
    def test_returns_entry_with_expected_shape(self):
        entry = _emit_telemetry("OK", "Decision captured in demo")
        assert entry["id"] == 1
        assert entry["kind"] == "OK"
        assert entry["message"] == "[OK] Decision captured in demo"
        assert "timestamp" in entry

    def test_ids_are_monotonic(self):
        first = _emit_telemetry("OK", "one")
        second = _emit_telemetry("DECAY", "two")
        assert second["id"] == first["id"] + 1

    def test_appends_to_module_log(self):
        _emit_telemetry("GHOST", "drift check")
        assert len(telemetry_module._telemetry_log) == 1
        assert telemetry_module._telemetry_log[0]["kind"] == "GHOST"

    def test_ring_buffer_evicts_oldest_beyond_200(self):
        for i in range(210):
            _emit_telemetry("OK", f"event {i}")
        assert len(telemetry_module._telemetry_log) == 200
        # Oldest 10 (ids 1-10) evicted; the buffer starts at id 11.
        assert telemetry_module._telemetry_log[0]["id"] == 11
        assert telemetry_module._telemetry_log[-1]["id"] == 210


class TestRecentEndpoint:
    def test_empty_on_fresh_start(self, client):
        res = client.get("/api/telemetry/recent")
        assert res.status_code == 200
        assert res.json() == {"events": [], "latest_id": 0}

    def test_returns_all_events_when_since_id_zero(self, client):
        _emit_telemetry("OK", "a")
        _emit_telemetry("DECAY", "b")
        res = client.get("/api/telemetry/recent")
        data = res.json()
        assert data["latest_id"] == 2
        assert [e["kind"] for e in data["events"]] == ["OK", "DECAY"]

    def test_since_id_filters_to_newer_events_only(self, client):
        _emit_telemetry("OK", "a")
        second = _emit_telemetry("DECAY", "b")
        _emit_telemetry("RESEARCH", "c")
        res = client.get(f"/api/telemetry/recent?since_id={second['id']}")
        data = res.json()
        assert [e["kind"] for e in data["events"]] == ["RESEARCH"]
        assert data["latest_id"] == 3

    def test_since_id_at_latest_returns_empty(self, client):
        entry = _emit_telemetry("OK", "a")
        res = client.get(f"/api/telemetry/recent?since_id={entry['id']}")
        data = res.json()
        assert data["events"] == []
        assert data["latest_id"] == entry["id"]

    def test_since_id_beyond_latest_still_reports_latest_id(self, client):
        _emit_telemetry("OK", "a")
        res = client.get("/api/telemetry/recent?since_id=999")
        data = res.json()
        assert data["events"] == []
        assert data["latest_id"] == 1

    def test_negative_since_id_rejected(self, client):
        res = client.get("/api/telemetry/recent?since_id=-1")
        assert res.status_code == 422

    def test_no_events_returns_since_id_as_latest(self, client):
        """latest_id falls back to the caller's since_id when the log is empty,
        so a client polling with a stale cursor doesn't regress to 0."""
        res = client.get("/api/telemetry/recent?since_id=42")
        assert res.json() == {"events": [], "latest_id": 42}
