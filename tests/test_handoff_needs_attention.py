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
