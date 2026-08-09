"""
Tests for POST /api/memory/{project}/sessions/record -- the single, now-
consolidated way to end a session.

Before this, POST /sessions (dashboard button, PatternLearner only) and
POST /sessions/record (MCP end_session tool, SessionReplay snapshot only)
were two disconnected endpoints, each doing half the job: ending a session
through one path silently skipped what the other did, and the pattern-
learning half had its own bug (see tests/test_learner.py) where the raw
summary text was never actually stored. POST /sessions has been removed;
this is the one way now, and it does both jobs in one call.

Uses the real server app end-to-end (test_-prefixed project, cleaned up by
tests/conftest.py's autouse fixture), same pattern as
tests/test_agent_identity_endpoints.py.
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
    name = f"test_sessionrecord_{uuid.uuid4().hex[:8]}"
    res = client.post("/api/memory", json={"project_name": name})
    assert res.status_code == 200, res.text
    return name


class TestRecordSessionConsolidation:
    def test_records_snapshot_and_learns_patterns_in_one_call(self, client, project):
        resp = client.post(
            f"/api/memory/{project}/sessions/record",
            json={"summary": "Fixed CSS layout bug in the header component", "agent_name": "claude"},
        )

        assert resp.status_code == 200
        body = resp.json()
        # The snapshot half (previously the only thing this endpoint did).
        assert "session_id" in body
        assert "change_count" in body
        # The pattern-learning half (previously only POST /sessions did this).
        assert "ui" in body["detected_categories"]
        assert "bug" in body["detected_categories"]
        assert len(body["key_insights"]) > 0

    def test_session_history_gets_the_real_summary_text(self, client, project):
        client.post(
            f"/api/memory/{project}/sessions/record",
            json={"summary": "Refactored the auth module for clarity", "agent_name": "claude"},
        )

        memory = client.get(f"/api/memory/{project}").json()
        entries = memory["session_history"]
        assert len(entries) == 1
        assert entries[0]["summary"] == "Refactored the auth module for clarity"

    def test_two_recorded_sessions_both_carry_their_own_summary(self, client, project):
        client.post(f"/api/memory/{project}/sessions/record", json={"summary": "Added API endpoint for login"})
        client.post(f"/api/memory/{project}/sessions/record", json={"summary": "Fixed CSS on the settings page"})

        memory = client.get(f"/api/memory/{project}").json()
        summaries = [e["summary"] for e in memory["session_history"]]
        assert summaries == ["Added API endpoint for login", "Fixed CSS on the settings page"]

    def test_empty_summary_records_snapshot_without_session_history_entry(self, client, project):
        resp = client.post(f"/api/memory/{project}/sessions/record", json={})

        assert resp.status_code == 200
        assert resp.json()["detected_categories"] == []
        memory = client.get(f"/api/memory/{project}").json()
        assert memory.get("session_history", []) == []

    def test_old_post_sessions_endpoint_is_gone(self, client, project):
        """POST /sessions (dashboard-only, pattern-learning-only) was
        removed as part of consolidating to one way to end a session."""
        resp = client.post(f"/api/memory/{project}/sessions", json={"summary": "test"})

        assert resp.status_code in (404, 405)
