"""Tests for P2 (Adversarial Hardening plan): decision-level tamper-evidence
via content hashing. Closes gap B -- previously decision text/context/
risk_level could be edited directly in memory/{project}.json with no way
for verify_integrity or detect_tampering to ever notice, since neither
compared current content against anything captured at write time.
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


def _load_memory(project: str) -> dict:
    return MemoryManager().get_project_memory(project)


def _save_memory(project: str, memory: dict) -> None:
    MemoryManager().save_project_memory(project, memory)


@pytest.fixture
def project():
    return f"test_hash_integrity_{uuid.uuid4().hex[:8]}"


def _create(client, project, decision="Use React for frontend", **extra):
    body = {"decision": decision, "context": "", "safety_metadata": {"safety_category": "general"}, **extra}
    return client.post(f"/api/memory/{project}/decisions", json=body).json()["decision"]


class TestHashOnCreate:
    def test_new_decision_carries_a_hash(self, client, project):
        d = _create(client, project)
        assert d.get("decision_hash")

    def test_decision_created_audit_event_carries_the_hash(self, client, project):
        d = _create(client, project)
        audit = client.get(f"/api/memory/{project}/security/audit-log").json()["events"]
        created = next(e for e in audit if e["event_type"] == "decision_created")
        assert created["decision_hash"] == d["decision_hash"]

    def test_clean_project_verifies_valid(self, client, project):
        _create(client, project)
        _create(client, project, decision="Use Postgres for storage")
        integrity = client.get(f"/api/memory/{project}/integrity/verify").json()
        assert integrity["valid"] is True
        assert integrity["issues"] == []


class TestDirectFileEditIsDetected:
    """The core #57-style scenario: a decision's content is edited directly
    in memory/{project}.json, bypassing the API entirely."""

    def test_edited_decision_text_fails_verification(self, client, project):
        d = _create(client, project, decision="Use React for frontend")

        memory = _load_memory(project)
        memory["decisions"][0]["decision"] = "Use Angular for frontend"
        _save_memory(project, memory)

        integrity = client.get(f"/api/memory/{project}/integrity/verify").json()
        assert integrity["valid"] is False
        issue = next(i for i in integrity["issues"] if i["type"] == "decision_content_edited")
        assert issue["decision_id"] == d["id"]
        assert issue["severity"] == "high"

    def test_edited_decision_text_flagged_by_tamper_detection(self, client, project):
        d = _create(client, project, decision="Use React for frontend")

        memory = _load_memory(project)
        memory["decisions"][0]["context"] = "tampered context"
        _save_memory(project, memory)

        tamper = client.get(f"/api/memory/{project}/tamper-detection").json()
        assert tamper["status"] == "compromised"
        flag = next(f for f in tamper["flags"] if f["type"] == "content_edited")
        assert d["id"] in flag["decision_ids"]

    def test_sophisticated_edit_that_also_forges_the_hash_is_caught_by_audit_divergence(self, client, project):
        """An attacker who edits both the content and recomputes
        decision_hash to match evades the plain content-hash check, but
        the audit trail still holds the original hash from the real write
        -- immutably, since it's protected by the audit log's own hash
        chain -- so the divergence check catches it instead."""
        from core.audit import decision_content_hash

        d = _create(client, project, decision="Use React for frontend")

        memory = _load_memory(project)
        memory["decisions"][0]["decision"] = "Use Angular for frontend"
        memory["decisions"][0]["decision_hash"] = decision_content_hash(memory["decisions"][0])
        _save_memory(project, memory)

        integrity = client.get(f"/api/memory/{project}/integrity/verify").json()
        assert integrity["valid"] is False
        issue_types = {i["type"] for i in integrity["issues"]}
        # The naive check no longer fires (hash was recomputed to match)...
        assert "decision_content_edited" not in issue_types
        # ...but the audit trail disagrees with the new hash.
        divergence = next(i for i in integrity["issues"] if i["type"] == "decisions_vs_audit_divergence")
        assert divergence["decision_id"] == d["id"]
        assert divergence["severity"] == "high"


class TestLegitimateMutationsDoNotFalsePositive:
    """Every path that legitimately mutates a decision's hash-covered
    fields after creation must resync the hash, or verify_integrity would
    cry wolf on ordinary use forever after."""

    def test_safety_category_tag_does_not_trip_content_edited(self, client, project):
        # slack_capture 404s on a project that's never been saved to disk
        # yet (unlike add_decision, which lazily creates one) -- create it
        # first, same as any other client would.
        client.post("/api/memory", json={"project_name": project})
        # /slack/capture is the real path that produces untagged decisions
        # (add_decision requires a category up front) -- it also now
        # carries its own decision_hash (P2), same as add_decision.
        client.post(f"/api/memory/{project}/slack/capture", json={
            "decision_text": "Untagged decision", "context": "", "channel": "test",
        })
        untagged = client.get(f"/api/memory/{project}/decisions/untagged").json()
        decision_id = untagged["decisions"][0]["id"]

        resp = client.patch(
            f"/api/memory/{project}/decisions/{decision_id}/safety-category",
            json={"safety_category": "general"},
        )
        assert resp.status_code == 200

        integrity = client.get(f"/api/memory/{project}/integrity/verify").json()
        assert integrity["valid"] is True

    def test_approval_does_not_trip_content_edited(self, client, project):
        d = _create(client, project)
        approved = client.post(
            f"/api/memory/{project}/decisions/{d['id']}/approve",
            params={"reviewer": "shan"},
        )
        assert approved.status_code == 200

        integrity = client.get(f"/api/memory/{project}/integrity/verify").json()
        assert integrity["valid"] is True

    def test_rollback_does_not_trip_content_edited(self, client, project):
        d = _create(client, project, decision="Original text")
        client.post(f"/api/memory/{project}/decisions/{d['id']}/version?change_reason=before edit")

        memory = _load_memory(project)
        memory["decisions"][0]["decision"] = "Edited text"
        _save_memory(project, memory)
        # Resync so this setup step itself doesn't look like tampering --
        # the point of this test is the rollback endpoint, not this edit.
        from core.audit import resync_decision_hash
        memory = _load_memory(project)
        resync_decision_hash(memory, memory["decisions"][0], changed_fields=["decision"])
        _save_memory(project, memory)

        resp = client.post(f"/api/memory/{project}/decisions/{d['id']}/rollback/1")
        assert resp.status_code == 200

        integrity = client.get(f"/api/memory/{project}/integrity/verify").json()
        assert integrity["valid"] is True


class TestOtherEscalationPathsResyncHash:
    """Contradiction Detection and Doc Mining have their own, independent
    copies of the "auto-escalate to review" mutation (same shape as P0's
    persona/market escalation) -- each needs its own resync_decision_hash
    call, or every escalation on any project with hashed decisions would
    permanently look like tampering."""

    def test_contradiction_escalation_resyncs_hash(self):
        from core.audit import decision_content_hash
        from core.contradictions.router import _escalate_to_review

        d = {
            "id": "d1", "decision": "Use REST", "context": "",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "safety_metadata": {"safety_category": "general"},
        }
        d["decision_hash"] = decision_content_hash(d)
        memory = {"decisions": [d]}

        count = _escalate_to_review(memory, {"d1"})
        assert count == 1
        assert d["decision_hash"] == decision_content_hash(d)
        events = [e["event_type"] for e in memory["audit_log"]]
        assert events == ["decision_updated", "contradiction_escalated"]

    def test_docmine_escalation_resyncs_hash(self):
        from core.audit import decision_content_hash
        from core.docmine.router import _escalate_to_review

        d = {
            "id": "d1", "decision": "Use REST", "context": "",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "safety_metadata": {"safety_category": "general"},
        }
        d["decision_hash"] = decision_content_hash(d)
        memory = {"decisions": [d]}

        count = _escalate_to_review(memory, {"d1"})
        assert count == 1
        assert d["decision_hash"] == decision_content_hash(d)
        events = [e["event_type"] for e in memory["audit_log"]]
        assert events == ["decision_updated"]


class TestBackfill:
    def test_legacy_decision_with_no_hash_is_unverified(self, client, project):
        d = _create(client, project)
        memory = _load_memory(project)
        del memory["decisions"][0]["decision_hash"]
        _save_memory(project, memory)

        integrity = client.get(f"/api/memory/{project}/integrity/verify").json()
        assert integrity["valid"] is False
        issue = next(i for i in integrity["issues"] if i["type"] == "unverified_hash")
        assert issue["decision_id"] == d["id"]
        assert issue["severity"] == "medium"

        tamper = client.get(f"/api/memory/{project}/tamper-detection").json()
        flag = next(f for f in tamper["flags"] if f["type"] == "unverified_hash")
        assert d["id"] in flag["decision_ids"]

    def test_backfill_reconstructs_from_audit_snapshot_not_current_state(self, client, project):
        """The backfill utility must pull the hash from the trusted audit
        record, never recompute it from the decision's current (here,
        already-tampered) content -- otherwise it would just launder
        tampering into a clean-looking hash."""
        d = _create(client, project, decision="Original text")

        memory = _load_memory(project)
        original_hash = memory["decisions"][0]["decision_hash"]
        memory["decisions"][0]["decision"] = "Tampered text"
        del memory["decisions"][0]["decision_hash"]
        _save_memory(project, memory)

        resp = client.post(f"/api/memory/{project}/security/backfill-hashes")
        assert resp.status_code == 200
        data = resp.json()
        assert d["id"] in data["backfilled"]

        memory = _load_memory(project)
        restored = memory["decisions"][0]
        assert restored["decision_hash"] == original_hash

        # And since the backfilled hash reflects the *original* content,
        # the tampered text now correctly fails verification instead of
        # being laundered clean.
        integrity = client.get(f"/api/memory/{project}/integrity/verify").json()
        assert integrity["valid"] is False
        issue_types = {i["type"] for i in integrity["issues"]}
        assert "decision_content_edited" in issue_types

    def test_decision_with_no_audit_snapshot_stays_unverified_after_backfill(self, client, project):
        d = _create(client, project)
        memory = _load_memory(project)
        del memory["decisions"][0]["decision_hash"]
        memory["audit_log"] = []  # no snapshot to reconstruct from at all
        _save_memory(project, memory)

        resp = client.post(f"/api/memory/{project}/security/backfill-hashes")
        assert resp.status_code == 200
        data = resp.json()
        assert data["backfilled"] == []
        assert d["id"] in data["still_unverified"]

    def test_backfill_is_a_no_op_when_nothing_needs_it(self, client, project):
        _create(client, project)
        resp = client.post(f"/api/memory/{project}/security/backfill-hashes")
        assert resp.status_code == 200
        data = resp.json()
        assert data["backfilled"] == []
        assert data["still_unverified"] == []
