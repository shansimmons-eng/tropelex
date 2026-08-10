"""
Tests for the Knowledge Decay Loop Closure (#58) router surface: pin/attest/
unpin, the decay-reviews list/dismiss endpoints, needs-attention's third
source, and the /decisions/scored inheritance swap.

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
    name = f"test_decayrouter_{uuid.uuid4().hex[:8]}"
    res = client.post("/api/memory", json={"project_name": name})
    assert res.status_code == 200, res.text
    return name


def _add_decision(client, project, decision="Use Postgres for storage", context=""):
    res = client.post(
        f"/api/memory/{project}/decisions",
        json={
            "decision": decision,
            "context": context,
            # explicit reversibility/affected_systems/requires_review sidesteps
            # #54's gate for decisions whose text (e.g. "delete") happens to
            # auto-classify as high-risk -- not relevant to what #58 tests here.
            "safety_metadata": {
                "safety_category": "general",
                "reversibility": True,
                "affected_systems": [],
                "requires_review": False,
            },
        },
    )
    assert res.status_code == 200, res.text
    return res.json()["decision"]["id"]


class TestPinAttestUnpin:
    def test_pin_sets_pinned_and_attests(self, client, project):
        decision_id = _add_decision(client, project)

        res = client.post(f"/api/memory/{project}/decisions/{decision_id}/pin", json={})

        assert res.status_code == 200, res.text
        body = res.json()
        assert body["pinned"] is True
        assert body["confidence"]["score"] == 1.0
        assert body["confidence"]["tier"] == "high"

        memory = client.get(f"/api/memory/{project}").json()
        decision = next(d for d in memory["decisions"] if d["id"] == decision_id)
        assert decision["pinned"] is True
        assert decision["last_attested"]

    def test_pin_missing_decision_404s(self, client, project):
        res = client.post(f"/api/memory/{project}/decisions/does-not-exist/pin", json={})
        assert res.status_code == 404

    def test_attest_without_pin_409s(self, client, project):
        decision_id = _add_decision(client, project)

        res = client.post(f"/api/memory/{project}/decisions/{decision_id}/attest", json={})

        assert res.status_code == 409

    def test_attest_after_pin_refreshes_timestamp(self, client, project):
        decision_id = _add_decision(client, project)
        client.post(f"/api/memory/{project}/decisions/{decision_id}/pin", json={})

        res = client.post(
            f"/api/memory/{project}/decisions/{decision_id}/attest",
            json={"agent_name": "Claude"},
        )

        assert res.status_code == 200, res.text
        assert res.json()["last_attested"]

    def test_unpin_reverts_to_normal_decay(self, client, project):
        decision_id = _add_decision(client, project)
        client.post(f"/api/memory/{project}/decisions/{decision_id}/pin", json={})

        res = client.post(f"/api/memory/{project}/decisions/{decision_id}/unpin", json={})

        assert res.status_code == 200, res.text
        assert res.json()["pinned"] is False
        memory = client.get(f"/api/memory/{project}").json()
        decision = next(d for d in memory["decisions"] if d["id"] == decision_id)
        assert decision["pinned"] is False

    def test_pin_attest_unpin_write_audit_events(self, client, project):
        decision_id = _add_decision(client, project)
        client.post(f"/api/memory/{project}/decisions/{decision_id}/pin", json={"agent_name": "Claude"})
        client.post(f"/api/memory/{project}/decisions/{decision_id}/attest", json={"agent_name": "Claude"})
        client.post(f"/api/memory/{project}/decisions/{decision_id}/unpin", json={"agent_name": "Claude"})

        memory = client.get(f"/api/memory/{project}").json()
        event_types = [e["event_type"] for e in memory.get("audit_log", [])]
        assert "decision_pinned" in event_types
        assert "decision_attested" in event_types
        assert "decision_unpinned" in event_types

    def test_unpin_missing_decision_404s(self, client, project):
        res = client.post(f"/api/memory/{project}/decisions/does-not-exist/unpin", json={})
        assert res.status_code == 404


class TestDecayReviewsListAndDismiss:
    def test_list_empty_when_no_reviews(self, client, project):
        res = client.get(f"/api/memory/{project}/decay-reviews")
        assert res.status_code == 200
        assert res.json() == {"decay_reviews": [], "count": 0}

    def test_dismiss_missing_review_404s(self, client, project):
        res = client.post(f"/api/memory/{project}/decay-reviews/does-not-exist/dismiss", json={})
        assert res.status_code == 404

    def test_dismiss_a_flagged_review_end_to_end(self, client, project):
        # Build a real stale+referenced pair via the actual decisions API,
        # then run the scheduler's flagging logic directly against this
        # project's memory (same function the background loop calls).
        from datetime import datetime, timedelta, timezone
        from core.memory.manager import MemoryManager
        import asyncio
        from core.scheduler import BackgroundScheduler

        old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
        d1 = _add_decision(client, project, "Delete old cache entries nightly")
        d2 = _add_decision(client, project, "Delete cache entries every deploy")
        _add_decision(client, project, "Completely unrelated filler about deployment scripts")

        mm = MemoryManager()
        memory = mm.get_project_memory(project)
        for d in memory["decisions"]:
            if d["id"] in (d1, d2):
                d["timestamp"] = old
        mm.save_project_memory(project, memory)

        scheduler = BackgroundScheduler(mm.base_path)
        asyncio.run(scheduler._check_stale_decisions())

        listed = client.get(f"/api/memory/{project}/decay-reviews?status=pending").json()
        assert listed["count"] == 2
        review_id = listed["decay_reviews"][0]["id"]

        res = client.post(
            f"/api/memory/{project}/decay-reviews/{review_id}/dismiss",
            json={"agent_name": "Claude", "reason": "known and accepted"},
        )
        assert res.status_code == 200, res.text
        assert res.json()["review_status"] == "dismissed"

        remaining = client.get(f"/api/memory/{project}/decay-reviews?status=pending").json()
        assert remaining["count"] == 1

        memory = client.get(f"/api/memory/{project}").json()
        event_types = [e["event_type"] for e in memory.get("audit_log", [])]
        assert "decay_review_dismissed" in event_types


class TestNeedsAttentionSurfacesDecayedDecisions:
    def test_pending_decay_review_appears_in_needs_attention(self, client, project):
        from datetime import datetime, timedelta, timezone
        from core.memory.manager import MemoryManager
        import asyncio
        from core.scheduler import BackgroundScheduler

        old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
        d1 = _add_decision(client, project, "Delete old cache entries nightly")
        d2 = _add_decision(client, project, "Delete cache entries every deploy")
        _add_decision(client, project, "Completely unrelated filler about deployment scripts")

        mm = MemoryManager()
        memory = mm.get_project_memory(project)
        for d in memory["decisions"]:
            if d["id"] in (d1, d2):
                d["timestamp"] = old
        mm.save_project_memory(project, memory)

        scheduler = BackgroundScheduler(mm.base_path)
        asyncio.run(scheduler._check_stale_decisions())

        res = client.get(f"/api/memory/{project}/needs-attention")
        assert res.status_code == 200
        items = res.json()["items"]
        decayed_items = [i for i in items if i["kind"] == "decayed_decision"]
        assert len(decayed_items) == 2
        assert "confidence decayed to" in decayed_items[0]["detail"]

    def test_no_decay_reviews_means_no_decayed_items(self, client, project):
        _add_decision(client, project)

        res = client.get(f"/api/memory/{project}/needs-attention")

        items = res.json()["items"]
        assert not any(i["kind"] == "decayed_decision" for i in items)


class TestScoredDecisionsCarriesInheritance:
    def test_scored_endpoint_includes_effective_score(self, client, project):
        _add_decision(client, project)

        res = client.get(f"/api/memory/{project}/decisions/scored")

        assert res.status_code == 200
        body = res.json()
        assert body["count"] == 1
        assert "effective_score" in body["decisions"][0]
        assert "inherited_discount" in body["decisions"][0]
        # No ancestors for a lone decision -- no discount applied.
        assert body["decisions"][0]["inherited_discount"] == 1.0
