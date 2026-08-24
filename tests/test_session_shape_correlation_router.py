"""Router-level tests for GET /{project}/agents/{agent}/session-shape/
correlation (wishlist #73-3). Uses the real server app end-to-end, same
pattern as test_session_shape_router.py; overrides/friction_history are
seeded directly via MemoryManager since driving them through their own
endpoints isn't the point of these tests.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from core.memory.manager import MemoryManager
from core.tropebook.web.server import app

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def project(client):
    name = f"test_shapecorr_{uuid.uuid4().hex[:8]}"
    res = client.post("/api/memory", json={"project_name": name})
    assert res.status_code == 200, res.text
    return name


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


def _seed(project: str, *, session_shapes=None, overrides=None, friction_history=None) -> None:
    mm = MemoryManager()
    memory = mm.get_project_memory(project)
    if session_shapes is not None:
        memory["session_shapes"] = session_shapes
    if overrides is not None:
        memory["overrides"] = overrides
    if friction_history is not None:
        memory["friction_history"] = friction_history
    mm.save_project_memory(project, memory)


class TestSessionShapeCorrelationEndpoint:
    def test_unknown_project_404s(self, client):
        resp = client.get("/api/memory/does-not-exist-at-all/agents/Claude/session-shape/correlation")
        assert resp.status_code == 404

    def test_insufficient_data_with_no_history(self, client, project):
        resp = client.get(f"/api/memory/{project}/agents/Claude/session-shape/correlation")
        assert resp.status_code == 200
        body = resp.json()
        assert body["project"] == project
        assert body["agent_name"] == "Claude"
        assert body["status"] == "insufficient_data"

    def test_ok_with_enough_history_and_a_correlated_outcome(self, client, project):
        # MIN_BASELINE_SESSIONS (5) consumed as the initial baseline, then
        # MIN_DEVIATION_SAMPLES (5) more so correlate_deviations_with_outcomes
        # itself has enough samples to report "ok" rather than insufficient_data.
        shapes = [_shape(i) for i in range(5)] + [
            _shape(5 + i, tool_call_count=5000, max_call_duration_ms=60000.0) for i in range(5)
        ]
        overrides = [
            {"agent_name": "Claude", "timestamp": (_T0 + timedelta(days=5 + i, hours=2)).isoformat()}
            for i in range(5)
        ]
        _seed(project, session_shapes=shapes, overrides=overrides)

        resp = client.get(
            f"/api/memory/{project}/agents/Claude/session-shape/correlation",
            params={"window_days": 1},
        )

        body = resp.json()
        assert body["status"] == "ok"
        assert body["flagged_sessions"] == 5
        assert body["rate_when_flagged"] == 1.0

    def test_agent_isolated_from_another_agents_history(self, client, project):
        shapes = [_shape(i) for i in range(6)] + [_shape(6, agent_name="Gemini")]
        _seed(project, session_shapes=shapes)

        resp = client.get(f"/api/memory/{project}/agents/Gemini/session-shape/correlation")
        assert resp.json()["status"] == "insufficient_data"

    def test_agent_name_normalized(self, client, project):
        shapes = [_shape(i) for i in range(5)]
        _seed(project, session_shapes=shapes)

        resp = client.get(f"/api/memory/{project}/agents/claude/session-shape/correlation")
        assert resp.json()["agent_name"] == "Claude"
