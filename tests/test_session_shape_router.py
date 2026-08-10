"""
Tests for session-shape baselining's router-level behavior (wishlist.md
#45): the session_shape field on POST /sessions/record, and
GET /{project}/agents/{agent}/session-shape.

Uses the real server app end-to-end (test_-prefixed project, cleaned up by
tests/conftest.py's autouse fixture), same pattern as
tests/test_session_record_router.py.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from core.tropebook.web.server import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def project(client):
    name = f"test_sessionshape_{uuid.uuid4().hex[:8]}"
    res = client.post("/api/memory", json={"project_name": name})
    assert res.status_code == 200, res.text
    return name


def _shape(**overrides):
    base = {
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


def _record_session(client, project, agent="Claude", summary="session", shape=None):
    body = {"summary": summary, "agent_name": agent}
    if shape is not None:
        body["session_shape"] = shape
    resp = client.post(f"/api/memory/{project}/sessions/record", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestRecordSessionWithShape:
    def test_session_shape_present_persists_to_memory(self, client, project):
        _record_session(client, project, shape=_shape())

        memory = client.get(f"/api/memory/{project}").json()
        assert len(memory["session_shapes"]) == 1
        assert memory["session_shapes"][0]["agent_name"] == "Claude"
        assert memory["session_shapes"][0]["tool_call_count"] == 10

    def test_session_shape_absent_does_not_add_an_entry(self, client, project):
        _record_session(client, project, shape=None)

        memory = client.get(f"/api/memory/{project}").json()
        assert memory.get("session_shapes", []) == []

    def test_response_includes_session_shape_result_when_provided(self, client, project):
        data = _record_session(client, project, shape=_shape())

        assert "session_shape" in data
        assert "baseline" in data["session_shape"]
        assert "deviation" in data["session_shape"]

    def test_response_omits_session_shape_key_when_not_provided(self, client, project):
        data = _record_session(client, project, shape=None)

        assert "session_shape" not in data

    def test_invalid_session_shape_field_rejected_with_422(self, client, project):
        resp = client.post(
            f"/api/memory/{project}/sessions/record",
            json={"summary": "x", "agent_name": "Claude", "session_shape": {"tool_call_count": -1}},
        )
        assert resp.status_code == 422  # ge=0 constraint violated, and required fields missing

    def test_learner_categories_and_session_shape_both_survive_together(self, client, project):
        """Regression for the reload-before-mutate race: record_session()
        reads `current` once at the top, then learner.
        update_project_from_session() does its own independent
        read/mutate/save cycle. Writing session_shapes into the stale
        `current` afterward would silently clobber whatever the learner
        just wrote. Both must be present after one call."""
        data = _record_session(
            client, project, summary="Fixed CSS layout bug in the header component", shape=_shape(),
        )

        assert "ui" in data["detected_categories"]
        assert "bug" in data["detected_categories"]
        assert "session_shape" in data

        memory = client.get(f"/api/memory/{project}").json()
        assert len(memory["session_history"]) == 1
        assert memory["session_history"][0]["summary"] == "Fixed CSS layout bug in the header component"
        assert len(memory["session_shapes"]) == 1

    def test_different_agents_produce_independent_history(self, client, project):
        _record_session(client, project, agent="Claude", shape=_shape())
        _record_session(client, project, agent="Gemini", shape=_shape())

        memory = client.get(f"/api/memory/{project}").json()
        agents = {r["agent_name"] for r in memory["session_shapes"]}
        assert agents == {"Claude", "Gemini"}


class TestSessionShapeReadEndpoint:
    def test_insufficient_data_before_any_sessions(self, client, project):
        resp = client.get(f"/api/memory/{project}/agents/Claude/session-shape")

        assert resp.status_code == 200
        body = resp.json()
        assert body["project"] == project
        assert body["agent_name"] == "Claude"
        assert body["status"] == "insufficient_data"

    def test_insufficient_data_below_minimum_sample_size(self, client, project):
        for _ in range(3):
            _record_session(client, project, shape=_shape())

        resp = client.get(f"/api/memory/{project}/agents/Claude/session-shape")

        assert resp.json()["status"] == "insufficient_data"

    def test_ok_status_with_deviation_once_enough_history_exists(self, client, project):
        for _ in range(6):
            _record_session(client, project, shape=_shape())

        resp = client.get(f"/api/memory/{project}/agents/Claude/session-shape")

        body = resp.json()
        assert body["status"] == "ok"
        assert body["sample_size"] == 5  # 6 total, latest excluded from its own baseline
        assert body["deviation"]["overall_severity"] in ("normal", "low", "medium", "high")

    def test_anomalous_latest_session_flagged_via_the_real_endpoint(self, client, project):
        for _ in range(5):
            _record_session(client, project, shape=_shape())
        _record_session(client, project, shape=_shape(tool_call_count=1000, max_call_duration_ms=60000.0))

        resp = client.get(f"/api/memory/{project}/agents/Claude/session-shape")

        body = resp.json()
        assert body["status"] == "ok"
        assert body["deviation"]["overall_severity"] == "high"
        assert body["deviation"]["metrics"]["tool_call_count"]["severity"] == "high"

    def test_agent_with_no_sessions_is_isolated_from_another_agents_history(self, client, project):
        for _ in range(6):
            _record_session(client, project, agent="Claude", shape=_shape())

        resp = client.get(f"/api/memory/{project}/agents/Gemini/session-shape")

        assert resp.json()["status"] == "insufficient_data"

    def test_agent_name_normalized_in_response(self, client, project):
        for _ in range(6):
            _record_session(client, project, agent="Claude", shape=_shape())

        resp = client.get(f"/api/memory/{project}/agents/claude/session-shape")

        assert resp.json()["agent_name"] == "Claude"

    def test_unknown_project_404s(self, client):
        resp = client.get("/api/memory/does-not-exist-at-all/agents/Claude/session-shape")
        assert resp.status_code == 404
