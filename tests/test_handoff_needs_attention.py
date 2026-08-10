"""
Integration tests for Signed Handoffs' (#59) wiring into the real server:
generate → audit event → Needs Attention surfacing → acknowledge → clears.

Uses the real server app end-to-end (test_-prefixed project, cleaned up by
tests/conftest.py's autouse fixture), same pattern as
tests/test_decay_router.py / tests/test_injection_sentinel_router.py.
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
    name = f"test_handoffneeds_{uuid.uuid4().hex[:8]}"
    res = client.post("/api/memory", json={"project_name": name})
    assert res.status_code == 200, res.text
    return name


class TestHandoffLifecycleEndToEnd:
    def test_generated_handoff_surfaces_in_needs_attention(self, client, project):
        gen = client.post(
            f"/api/memory/{project}/handoff",
            json={"role": "CoderAgent", "agent_name": "Claude"},
        )
        assert gen.status_code == 200, gen.text
        packet_hash = gen.json()["packet_hash"]
        assert packet_hash

        attention = client.get(f"/api/memory/{project}/needs-attention")
        items = [i for i in attention.json()["items"] if i["kind"] == "unacknowledged_handoff"]
        assert len(items) == 1
        assert items[0]["id"] == packet_hash
        assert "CoderAgent" in items[0]["label"]

    def test_acknowledging_clears_it_from_needs_attention(self, client, project):
        gen = client.post(f"/api/memory/{project}/handoff", json={"role": "CoderAgent"})
        packet_hash = gen.json()["packet_hash"]

        ack = client.post(
            f"/api/memory/{project}/handoff/acknowledge",
            json={"packet_hash": packet_hash, "agent_name": "Claude"},
        )
        assert ack.status_code == 200, ack.text

        attention = client.get(f"/api/memory/{project}/needs-attention")
        items = [i for i in attention.json()["items"] if i["kind"] == "unacknowledged_handoff"]
        assert items == []

    def test_acknowledging_unknown_hash_404s(self, client, project):
        res = client.post(
            f"/api/memory/{project}/handoff/acknowledge",
            json={"packet_hash": "never-generated"},
        )
        assert res.status_code == 404

    def test_two_handoffs_one_acknowledged_only_other_surfaces(self, client, project):
        gen1 = client.post(f"/api/memory/{project}/handoff", json={"role": "CoderAgent"})
        gen2 = client.post(f"/api/memory/{project}/handoff", json={"role": "TestEngineer"})
        hash1 = gen1.json()["packet_hash"]
        hash2 = gen2.json()["packet_hash"]
        assert hash1 != hash2

        client.post(f"/api/memory/{project}/handoff/acknowledge", json={"packet_hash": hash1})

        attention = client.get(f"/api/memory/{project}/needs-attention")
        items = [i for i in attention.json()["items"] if i["kind"] == "unacknowledged_handoff"]
        assert len(items) == 1
        assert items[0]["id"] == hash2

    def test_unacknowledged_list_endpoint_matches_needs_attention(self, client, project):
        gen = client.post(f"/api/memory/{project}/handoff", json={"role": "CoderAgent"})
        packet_hash = gen.json()["packet_hash"]

        listed = client.get(f"/api/memory/{project}/handoff/unacknowledged")
        assert listed.status_code == 200
        assert listed.json()["count"] == 1
        assert listed.json()["handoffs"][0]["packet_hash"] == packet_hash

    def test_audit_log_has_both_events_after_full_lifecycle(self, client, project):
        gen = client.post(
            f"/api/memory/{project}/handoff",
            json={"role": "CoderAgent", "agent_name": "Claude"},
        )
        packet_hash = gen.json()["packet_hash"]
        client.post(
            f"/api/memory/{project}/handoff/acknowledge",
            json={"packet_hash": packet_hash, "agent_name": "Claude"},
        )

        memory = client.get(f"/api/memory/{project}").json()
        event_types = [e["event_type"] for e in memory.get("audit_log", [])]
        assert "handoff_created" in event_types
        assert "handoff_acknowledged" in event_types

    def test_no_handoffs_no_content_flagged_items(self, client, project):
        attention = client.get(f"/api/memory/{project}/needs-attention")
        assert attention.status_code == 200
        assert not any(i["kind"] == "unacknowledged_handoff" for i in attention.json()["items"])


class TestCompletenessViolationSurfacing:
    """#69's sixth Needs Attention source. Protection at both loss points
    (_select_decisions/_trim_to_budget) is unconditional by construction,
    so a real generate_handoff call can never produce a violation to
    surface here -- same reasoning as #69's Drift-Bench positive scenario.
    Seeds a handoff_completeness_violation audit entry directly via
    MemoryManager, the same approach already used to verify #59's
    unacknowledged_handoff source before it shipped."""

    def _seed_violation(self, project, decision_id="d1", description="dropped"):
        from core.memory.manager import MemoryManager
        from core.audit import append_audit_event

        mm = MemoryManager()
        memory = mm.get_project_memory(project)
        append_audit_event(
            memory, "handoff_completeness_violation",
            packet_hash="seeded-hash", role="CoderAgent", agent_name="Claude",
            decision_id=decision_id, description=description,
        )
        mm.save_project_memory(project, memory)

    def test_seeded_violation_surfaces_in_needs_attention(self, client, project):
        self._seed_violation(project, decision_id="db-critical", description="a critical decision was dropped")

        attention = client.get(f"/api/memory/{project}/needs-attention")
        items = [i for i in attention.json()["items"] if i["kind"] == "handoff_completeness_violation"]
        assert len(items) == 1
        assert items[0]["id"] == "db-critical"
        assert "a critical decision was dropped" in items[0]["detail"]

    def test_no_violations_no_items(self, client, project):
        attention = client.get(f"/api/memory/{project}/needs-attention")
        assert attention.status_code == 200
        assert not any(i["kind"] == "handoff_completeness_violation" for i in attention.json()["items"])

    def test_seeded_violation_matches_completeness_violations_endpoint(self, client, project):
        self._seed_violation(project, decision_id="db-critical")

        listed = client.get(f"/api/memory/{project}/handoff/completeness-violations")
        assert listed.status_code == 200
        assert listed.json()["count"] == 1
        assert listed.json()["violations"][0]["decision_id"] == "db-critical"
