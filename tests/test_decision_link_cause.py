"""Tests for the explicit, user-authored caused_by/led_to decision link
feature (POST .../decisions/{id}/link-cause). This is the non-heuristic
mechanism core.decision_tree._find_caused_by's docstring calls for as the
only acceptable replacement for the keyword heuristic it replaced.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from core.decision_tree import DecisionTree
from core.tropebook.web.server import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def project():
    return f"test_link_cause_{uuid.uuid4().hex[:8]}"


def _create(client, project, decision):
    body = {"decision": decision, "context": "", "safety_metadata": {"safety_category": "general"}}
    return client.post(f"/api/memory/{project}/decisions", json=body).json()["decision"]


class TestLinkCauseEndpoint:
    def test_caused_by_direction_writes_onto_this_decision(self, client, project):
        cause = _create(client, project, "Switched to PostgreSQL")
        effect = _create(client, project, "Rewrote the ORM layer")
        resp = client.post(
            f"/api/memory/{project}/decisions/{effect['id']}/link-cause",
            json={"targets": [cause["id"]], "direction": "caused_by", "note": "needed real transactions"},
        )
        assert resp.status_code == 200
        assert resp.json()["linked"] == [cause["id"]]

        detail = client.get(f"/api/memory/{project}/decision-tree/{effect['id']}").json()
        ancestors = detail["ancestors"]
        assert len(ancestors) == 1
        assert ancestors[0]["decision"]["id"] == cause["id"]
        assert ancestors[0]["relationship"] == "caused_by"
        assert ancestors[0]["note"] == "needed real transactions"

    def test_led_to_direction_writes_onto_the_target(self, client, project):
        source = _create(client, project, "Deprecated the v1 API")
        target = _create(client, project, "Migrated clients to v2")
        resp = client.post(
            f"/api/memory/{project}/decisions/{source['id']}/link-cause",
            json={"targets": [target["id"]], "direction": "led_to", "note": "v1 removal forced the move"},
        )
        assert resp.status_code == 200
        assert resp.json()["linked"] == [target["id"]]

        detail = client.get(f"/api/memory/{project}/decision-tree/{source['id']}").json()
        descendants = detail["descendants"]
        assert len(descendants) == 1
        assert descendants[0]["decision"]["id"] == target["id"]
        assert descendants[0]["relationship"] == "caused_by"

    def test_self_link_rejected(self, client, project):
        d = _create(client, project, "Use FastAPI")
        resp = client.post(
            f"/api/memory/{project}/decisions/{d['id']}/link-cause",
            json={"targets": [d["id"]], "direction": "caused_by"},
        )
        assert resp.status_code == 422

    def test_missing_target_404s(self, client, project):
        d = _create(client, project, "Use FastAPI")
        resp = client.post(
            f"/api/memory/{project}/decisions/{d['id']}/link-cause",
            json={"targets": ["does-not-exist"], "direction": "caused_by"},
        )
        assert resp.status_code == 404

    def test_missing_source_404s(self, client, project):
        d = _create(client, project, "Use FastAPI")
        resp = client.post(
            f"/api/memory/{project}/decisions/does-not-exist/link-cause",
            json={"targets": [d["id"]], "direction": "caused_by"},
        )
        assert resp.status_code == 404

    def test_duplicate_link_is_skipped_not_duplicated(self, client, project):
        cause = _create(client, project, "Adopted Docker")
        effect = _create(client, project, "Standardized the CI pipeline")
        req = {"targets": [cause["id"]], "direction": "caused_by", "note": "first"}
        first = client.post(f"/api/memory/{project}/decisions/{effect['id']}/link-cause", json=req)
        second = client.post(f"/api/memory/{project}/decisions/{effect['id']}/link-cause", json=req)
        assert first.json()["linked"] == [cause["id"]]
        assert second.json()["skipped"] == [cause["id"]]

        detail = client.get(f"/api/memory/{project}/decision-tree/{effect['id']}").json()
        assert len(detail["ancestors"]) == 1

    def test_link_cause_does_not_change_decision_hash(self, client, project):
        cause = _create(client, project, "Adopted pytest")
        effect = _create(client, project, "Switched the test runner to pytest")
        hash_before = effect["decision_hash"]
        client.post(
            f"/api/memory/{project}/decisions/{effect['id']}/link-cause",
            json={"targets": [cause["id"]], "direction": "caused_by"},
        )
        verify = client.get(f"/api/memory/{project}/integrity/verify")
        assert verify.status_code == 200
        assert verify.json().get("valid", True) is True
        # decision_hash itself is unchanged -- manual_causes is a relationship
        # field, excluded from decision_content_hash same as citation_ids.
        raw = client.get(f"/api/memory/{project}").json()
        stored = next(d for d in raw["decisions"] if d["id"] == effect["id"])
        assert stored["decision_hash"] == hash_before

    def test_manual_link_recorded_in_audit_log(self, client, project):
        cause = _create(client, project, "Chose Redis for caching")
        effect = _create(client, project, "Added a cache-invalidation hook")
        client.post(
            f"/api/memory/{project}/decisions/{effect['id']}/link-cause",
            json={"targets": [cause["id"]], "direction": "caused_by", "note": "explains the hook"},
        )
        audit = client.get(f"/api/memory/{project}/security/audit-log").json()["events"]
        event = next(e for e in audit if e["event_type"] == "decision_manual_link")
        assert event["decision_id"] == effect["id"]
        assert event["target_id"] == cause["id"]


class TestManualCausesFeedsChainWalking:
    def test_manual_causes_produces_a_caused_by_edge(self):
        tree = DecisionTree()
        tree.add_decision({"decision": "Cause", "id": "cause-1", "timestamp": "2026-01-01T00:00:00Z"})
        tree.add_decision({
            "decision": "Effect", "id": "effect-1", "timestamp": "2026-01-02T00:00:00Z",
            "manual_causes": [{"target_id": "cause-1", "note": "explicit link", "created_at": "2026-01-02T00:00:00Z"}],
        })
        node = tree.get_decision("effect-1")
        edges = [e for e in node["edges"] if e["relationship"] == "caused_by"]
        assert len(edges) == 1
        assert edges[0]["target"] == "cause-1"
        assert edges[0]["note"] == "explicit link"

    def test_manual_causes_participates_in_chain_walking(self):
        tree = DecisionTree()
        tree.add_decision({"decision": "Root cause", "id": "c1", "timestamp": "2026-01-01T00:00:00Z"})
        tree.add_decision({
            "decision": "Downstream effect", "id": "c2", "timestamp": "2026-01-02T00:00:00Z",
            "manual_causes": [{"target_id": "c1", "note": "", "created_at": "2026-01-02T00:00:00Z"}],
        })
        chains = tree.get_chains()
        assert any(
            {d["id"] for d in chain} == {"c1", "c2"}
            for chain in chains
        )

    def test_manual_causes_alone_does_not_reintroduce_the_heuristic(self):
        """A decision with no manual_causes field must never get a
        caused_by edge just from sharing keywords -- confirms the removal
        from #_find_caused_by is still in effect and this feature doesn't
        quietly bring it back."""
        tree = DecisionTree()
        tree.add_decision({
            "decision": "Use MySQL for the primary database", "id": "d1",
            "timestamp": "2026-01-01T00:00:00Z",
        })
        tree.add_decision({
            "decision": "Cache the memory payload after profiling showed slow database reads",
            "id": "d2", "timestamp": "2026-01-02T00:00:00Z",
        })
        node = tree.get_decision("d2")
        assert all(e["relationship"] != "caused_by" for e in node["edges"])
