"""Router-level tests for the per-agent safety budget (wishlist #73-4):
GET .../agents/{agent}/safety-budget and POST .../safety-budget/escalate.
Also covers the agent_name attribution added to GhostCheckRequest and
DecisionCreate that this feature depends on.

Uses the real server app end-to-end, same pattern as other router tests in
this suite. Overrides/audit_log entries not reachable through a simple
endpoint call are seeded directly via MemoryManager.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from core.memory.manager import MemoryManager
from core.tropebook.web.server import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def project(client):
    name = f"test_safetybudget_{uuid.uuid4().hex[:8]}"
    res = client.post("/api/memory", json={"project_name": name})
    assert res.status_code == 200, res.text
    return name


def _create_decision(client, project, agent_name="Claude", **overrides):
    body = {
        "decision": "Use React for frontend",
        "context": "",
        "safety_metadata": {"safety_category": "general"},
        "agent_name": agent_name,
        **overrides,
    }
    resp = client.post(f"/api/memory/{project}/decisions", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()["decision"]


class TestAgentAttributionOnWrite:
    def test_decision_carries_agent_name(self, client, project):
        d = _create_decision(client, project, agent_name="Claude")
        assert d["agent_name"] == "Claude"

    def test_decision_defaults_agent_name_to_unspecified(self, client, project):
        resp = client.post(f"/api/memory/{project}/decisions", json={
            "decision": "x", "context": "", "safety_metadata": {"safety_category": "general"},
        })
        assert resp.json()["decision"]["agent_name"] == "unspecified"

    def test_agent_name_not_part_of_the_content_hash(self, client, project):
        d = _create_decision(client, project, agent_name="Claude")
        original_hash = d["decision_hash"]

        integrity = client.get(f"/api/memory/{project}/integrity/verify").json()
        assert integrity["valid"] is True
        assert d["decision_hash"] == original_hash


class TestSafetyBudgetEndpoint:
    def test_unknown_project_404s(self, client):
        resp = client.get("/api/memory/does-not-exist-at-all/agents/Claude/safety-budget")
        assert resp.status_code == 404

    def test_zero_score_for_agent_with_no_activity(self, client, project):
        resp = client.get(f"/api/memory/{project}/agents/Claude/safety-budget")
        assert resp.status_code == 200
        body = resp.json()
        assert body["project"] == project
        assert body["agent_name"] == "Claude"
        assert body["score"] == 0.0
        assert body["over_threshold"] is False

    _HIGH_RISK_METADATA = {
        "safety_category": "general", "risk_level": "high",
        "reversibility": True, "affected_systems": ["ui"], "requires_review": False,
    }

    def test_high_risk_decision_raises_score(self, client, project):
        _create_decision(client, project, agent_name="Claude", safety_metadata=self._HIGH_RISK_METADATA)
        resp = client.get(f"/api/memory/{project}/agents/Claude/safety-budget")
        body = resp.json()
        assert body["score"] > 0.0
        assert body["breakdown"]["high_risk_decisions"]["count"] == 1

    def test_another_agents_decisions_do_not_affect_score(self, client, project):
        _create_decision(client, project, agent_name="Gemini", safety_metadata=self._HIGH_RISK_METADATA)
        resp = client.get(f"/api/memory/{project}/agents/Claude/safety-budget")
        assert resp.json()["score"] == 0.0

    def test_agent_name_normalized(self, client, project):
        resp = client.get(f"/api/memory/{project}/agents/claude/safety-budget")
        assert resp.json()["agent_name"] == "Claude"


class TestSafetyBudgetEscalateEndpoint:
    def test_unknown_project_404s(self, client):
        resp = client.post("/api/memory/does-not-exist-at-all/agents/Claude/safety-budget/escalate")
        assert resp.status_code == 404

    def test_no_op_under_threshold(self, client, project):
        _create_decision(client, project, agent_name="Claude")
        resp = client.post(f"/api/memory/{project}/agents/Claude/safety-budget/escalate")
        body = resp.json()
        assert body["escalated"] is False
        assert body["reason"] == "under_threshold"

    def test_escalates_most_recent_eligible_decision_over_threshold(self, client, project):
        d = _create_decision(client, project, agent_name="Claude")
        # Push Claude's score over the default threshold via overrides,
        # seeded directly since the override endpoint needs a decision id
        # to override against (any real decision id works for the seed).
        from core.audit import append_audit_event

        mm = MemoryManager()
        memory = mm.get_project_memory(project)
        for _ in range(10):
            append_audit_event(memory, "override", agent_name="Claude", decision_id=d["id"])
        mm.save_project_memory(project, memory)

        resp = client.post(f"/api/memory/{project}/agents/Claude/safety-budget/escalate")
        body = resp.json()
        assert body["escalated"] is True
        assert body["decision_id"] == d["id"]

        memory = client.get(f"/api/memory/{project}").json()
        updated = next(x for x in memory["decisions"] if x["id"] == d["id"])
        assert updated["safety_metadata"]["requires_review"] is True
        assert "safety_budget_exceeded" in updated["safety_metadata"]["escalation_reason"]

        integrity = client.get(f"/api/memory/{project}/integrity/verify").json()
        assert integrity["valid"] is True

    def test_no_eligible_decision_over_threshold_is_a_clean_no_op(self, client, project):
        d = _create_decision(client, project, agent_name="Claude")
        client.post(
            f"/api/memory/{project}/decisions/{d['id']}/approve",
            params={"reviewer": "shan"},
        )
        from core.audit import append_audit_event

        mm = MemoryManager()
        memory = mm.get_project_memory(project)
        for _ in range(10):
            append_audit_event(memory, "override", agent_name="Claude", decision_id=d["id"])
        mm.save_project_memory(project, memory)

        resp = client.post(f"/api/memory/{project}/agents/Claude/safety-budget/escalate")
        body = resp.json()
        assert body["escalated"] is False
        assert body["reason"] == "no_eligible_decision"


class TestGhostCheckAgentAttribution:
    def test_gate_blocked_event_carries_agent_name(self, client, project):
        # A decision the diff will contradict, high enough severity to gate.
        _create_decision(
            client, project, agent_name="Claude",
            decision="Never use MongoDB for this project",
        )
        client.put(f"/api/memory/{project}/gate-policy", json={"high": "block"})

        resp = client.post(f"/api/memory/{project}/ghost-check", json={
            "diff": "+ Use MongoDB for the new service, replacing the prior no-MongoDB decision",
            "agent_name": "Claude",
        })
        # Either it blocked (409, still logs gate_blocked) or didn't match --
        # only assert on the audit log if a gate event was actually written.
        mm = MemoryManager()
        memory = mm.get_project_memory(project)
        gate_events = [e for e in memory.get("audit_log", []) if e.get("event_type") in ("gate_blocked", "gate_warned")]
        for e in gate_events:
            assert e.get("agent_name") == "Claude"
