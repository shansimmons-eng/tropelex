"""
Tests for the cross-cutting agent-identity aggregate endpoints:
GET /api/memory/{project}/agents
GET /api/memory/{project}/agents/{agent}/summary

These combine data from AgentSkillGraph, friction_history, and SessionReplay
per agent — unlike those modules' own tests, these exercise the real server
app end-to-end through the actual HTTP surface, using a test_-prefixed
project so tests/conftest.py's autouse cleanup fixture removes it after.
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
    """A properly-created project — friction/scan requires the project to
    already exist via MemoryManager.list_projects(), unlike agent-skills/
    record and sessions/record, which lazily create-on-write."""
    name = f"test_agentid_{uuid.uuid4().hex[:8]}"
    res = client.post("/api/memory", json={"project_name": name})
    assert res.status_code == 200, res.text
    return name


def _record_skill(client, project, agent, outcome="success", categories=None):
    res = client.post(
        f"/api/memory/{project}/agent-skills/record",
        json={
            "session_type": "manual",
            "categories": categories or ["ui"],
            "outcome": outcome,
            "agent_name": agent,
        },
    )
    assert res.status_code == 200, res.text
    return res.json()


def _scan_friction(client, project, agent, transcript="no thats wrong, try again"):
    res = client.post(
        f"/api/memory/{project}/friction/scan",
        json={"transcript": transcript, "agent_name": agent},
    )
    assert res.status_code == 200, res.text
    return res.json()


def _record_session(client, project, agent, session_type="manual"):
    res = client.post(
        f"/api/memory/{project}/sessions/record",
        json={"summary": "test session", "session_type": session_type, "agent_name": agent},
    )
    assert res.status_code == 200, res.text
    return res.json()


class TestListProjectAgents:
    def test_empty_project_has_no_agents(self, client, project):
        res = client.get(f"/api/memory/{project}/agents")
        assert res.status_code == 200
        assert res.json() == {"agents": [], "count": 0}

    def test_collects_agents_from_skills(self, client, project):
        _record_skill(client, project, "Claude")
        res = client.get(f"/api/memory/{project}/agents")
        assert res.json()["agents"] == ["Claude"]

    def test_collects_agents_from_friction(self, client, project):
        _scan_friction(client, project, "Gemini")
        res = client.get(f"/api/memory/{project}/agents")
        assert res.json()["agents"] == ["Gemini"]

    def test_collects_agents_from_sessions(self, client, project):
        _record_session(client, project, "Big Pickle")
        res = client.get(f"/api/memory/{project}/agents")
        assert res.json()["agents"] == ["Big Pickle"]

    def test_union_across_all_three_sources_deduped_and_sorted(self, client, project):
        _record_skill(client, project, "Gemini")
        _scan_friction(client, project, "Claude")
        _record_session(client, project, "Claude")  # same agent as friction, not double-counted
        res = client.get(f"/api/memory/{project}/agents")
        data = res.json()
        assert data["agents"] == ["Claude", "Gemini"]
        assert data["count"] == 2

    def test_unspecified_never_appears(self, client, project):
        _record_skill(client, project, "")  # falls back to "unspecified"
        res = client.get(f"/api/memory/{project}/agents")
        assert res.json()["agents"] == []


class TestGetAgentSummary:
    def test_unknown_agent_returns_zeroed_summary_not_404(self, client, project):
        res = client.get(f"/api/memory/{project}/agents/NoSuchAgent/summary")
        assert res.status_code == 200
        body = res.json()
        assert body["agent_name"] == "NoSuchAgent"
        assert body["skills"] == []
        assert body["friction"]["total_scans"] == 0
        assert body["sessions"]["total"] == 0

    def test_combines_skills_friction_and_sessions_for_one_agent(self, client, project):
        _record_skill(client, project, "Claude", outcome="success", categories=["ui"])
        _scan_friction(client, project, "Claude")
        _record_session(client, project, "Claude", session_type="manual")

        res = client.get(f"/api/memory/{project}/agents/Claude/summary")
        assert res.status_code == 200
        body = res.json()
        assert body["agent_name"] == "Claude"
        assert body["skills"][0]["skill"] == "ui"
        assert body["skills"][0]["score"] == 1.0
        assert body["friction"]["total_scans"] == 1
        assert body["sessions"]["total"] == 1
        assert body["sessions"]["by_type"] == {"manual": 1}

    def test_two_agents_summaries_are_isolated(self, client, project):
        _record_skill(client, project, "Claude", outcome="success")
        _record_skill(client, project, "Gemini", outcome="failure")

        claude = client.get(f"/api/memory/{project}/agents/Claude/summary").json()
        gemini = client.get(f"/api/memory/{project}/agents/Gemini/summary").json()
        assert claude["skills"][0]["score"] == 1.0
        assert gemini["skills"][0]["score"] == 0.0

    def test_strengths_and_weaknesses_reflect_agent_scope(self, client, project):
        for _ in range(5):
            _record_skill(client, project, "Claude", outcome="success")
        for _ in range(5):
            _record_skill(client, project, "Gemini", outcome="failure")

        claude = client.get(f"/api/memory/{project}/agents/Claude/summary").json()
        gemini = client.get(f"/api/memory/{project}/agents/Gemini/summary").json()
        assert "ui" in claude["strengths"]
        assert "ui" in gemini["weaknesses"]
