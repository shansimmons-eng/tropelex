"""Tests for Fairness, Accountability, Robustness, Alignment, and Provenance features."""

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
    return f"test_features_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def sample_decisions(client, project):
    """Create a set of sample decisions for testing."""
    decisions = [
        {
            "decision": "Deploy critical security patch",
            "context": "Zero-day vulnerability in authentication system",
            "safety_metadata": {
                "risk_level": "high",
                "reversibility": True,
                "affected_systems": ["auth", "api"],
                "requires_review": True,
                "safety_category": "robustness",
            },
        },
        {
            "decision": "Update documentation",
            "context": "Minor doc improvements",
            "safety_metadata": {
                "risk_level": "low",
                "reversibility": True,
                "affected_systems": ["docs"],
                "requires_review": False,
                "safety_category": "general",
            },
        },
        {
            "decision": "Migrate database schema",
            "context": "Required for new features",
            "safety_metadata": {
                "risk_level": "critical",
                "reversibility": False,
                "affected_systems": ["database", "api"],
                "requires_review": True,
                "safety_category": "robustness",
            },
        },
    ]

    created = []
    for d in decisions:
        resp = client.post(f"/api/memory/{project}/decisions", json=d)
        created.append(resp.json()["decision"])

    return created


# ===== Fairness, Accountability, Robustness Tests =====


class TestFairnessAudit:
    def test_empty_project(self, client, project):
        response = client.get(f"/api/memory/{project}/fairness/audit")
        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["total_decisions"] == 0

    def test_with_decisions(self, client, project, sample_decisions):
        response = client.get(f"/api/memory/{project}/fairness/audit")
        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["total_decisions"] == 3
        assert "category_risk_distribution" in data
        assert "bias_flags" in data


class TestAccountabilityReport:
    def test_empty_project(self, client, project):
        response = client.get(f"/api/memory/{project}/accountability/report")
        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["total_decisions"] == 0

    def test_with_decisions(self, client, project, sample_decisions):
        response = client.get(f"/api/memory/{project}/accountability/report")
        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["total_decisions"] == 3
        assert "accountability_gaps" in data


class TestRobustnessTest:
    def test_empty_project(self, client, project):
        response = client.get(f"/api/memory/{project}/robustness/test")
        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["total_decisions"] == 0

    def test_with_decisions(self, client, project, sample_decisions):
        response = client.get(f"/api/memory/{project}/robustness/test")
        assert response.status_code == 200
        data = response.json()
        assert "issues" in data
        assert "robustness_score" in data["summary"]


class TestTransparencyReport:
    def test_empty_project(self, client, project):
        response = client.get(f"/api/memory/{project}/transparency/report")
        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["total_decisions"] == 0

    def test_with_decisions(self, client, project, sample_decisions):
        response = client.get(f"/api/memory/{project}/transparency/report")
        assert response.status_code == 200
        data = response.json()
        assert len(data["decisions"]) == 3
        assert "key_insights" in data


# ===== Alignment Tests =====


class TestValueAlignment:
    def test_default_values(self, client, project, sample_decisions):
        response = client.get(f"/api/memory/{project}/alignment/values")
        assert response.status_code == 200
        data = response.json()
        assert len(data["values_evaluated"]) == 5

    def test_custom_values(self, client, project, sample_decisions):
        response = client.get(f"/api/memory/{project}/alignment/values", params={"values": "safety,transparency"})
        assert response.status_code == 200
        data = response.json()
        assert len(data["values_evaluated"]) == 2


class TestSafetyEnvelope:
    def test_empty_project(self, client, project):
        response = client.get(f"/api/memory/{project}/safety-envelope")
        assert response.status_code == 200
        data = response.json()
        assert data["envelope_status"] == "healthy"

    def test_with_decisions(self, client, project, sample_decisions):
        response = client.get(f"/api/memory/{project}/safety-envelope")
        assert response.status_code == 200
        data = response.json()
        assert "envelope_status" in data
        assert "metrics" in data


class TestAlignmentDrift:
    def test_insufficient_data(self, client, project, sample_decisions):
        response = client.get(f"/api/memory/{project}/alignment/drift")
        assert response.status_code == 200
        data = response.json()
        assert data["drift_detected"] == False


class TestCorrigibilityTracker:
    def test_empty_project(self, client, project):
        response = client.get(f"/api/memory/{project}/corrigibility")
        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["total_decisions"] == 0

    def test_with_decisions(self, client, project, sample_decisions):
        response = client.get(f"/api/memory/{project}/corrigibility")
        assert response.status_code == 200
        data = response.json()
        assert "corrigibility_score" in data["summary"]


# ===== Provenance, Integrity, Security Tests =====


class TestProvenanceChain:
    def test_empty_project(self, client, project):
        response = client.get(f"/api/memory/{project}/provenance/chain")
        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["chain_length"] == 0

    def test_with_decisions(self, client, project, sample_decisions):
        response = client.get(f"/api/memory/{project}/provenance/chain")
        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["chain_length"] == 3
        assert len(data["chain"]) == 3


class TestIntegrityVerification:
    def test_valid_integrity(self, client, project, sample_decisions):
        response = client.get(f"/api/memory/{project}/integrity/verify")
        assert response.status_code == 200
        data = response.json()
        assert "integrity_score" in data["summary"]


class TestTamperDetection:
    def test_clean_project(self, client, project, sample_decisions):
        response = client.get(f"/api/memory/{project}/tamper-detection")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["clean", "alert", "compromised"]

    def test_no_decisions_is_clean(self, client, project):
        response = client.get(f"/api/memory/{project}/tamper-detection")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "clean"
        assert data["flags"] == []

    def test_timestamp_swap_on_hashed_decisions_is_compromised(self, client, project):
        """P2 (gap B): timestamp is one of the fields covered by
        decision_hash, so directly rewriting it in the memory JSON after
        creation -- exactly what this test does -- now also trips
        content_edited (high), not just the old low-confidence
        timestamp_anomaly heuristic. That's the point of P2: a signal that
        used to be ambiguous (could be clock skew, backdated import, or
        real tampering) is now conclusive once a hash is involved, because
        a legitimate backdated-import workflow sets its timestamp *through
        the API* at creation time -- the hash would cover that -- rather
        than rewriting an already-hashed decision's timestamp after the
        fact the way this test does."""
        client.post(f"/api/memory/{project}/decisions", json={
            "decision": "First", "context": "", "safety_metadata": {"safety_category": "general"},
        })
        client.post(f"/api/memory/{project}/decisions", json={
            "decision": "Second", "context": "", "safety_metadata": {"safety_category": "general"},
        })

        memory = _load_memory(project)
        decisions = memory["decisions"]
        decisions[0]["timestamp"], decisions[1]["timestamp"] = decisions[1]["timestamp"], decisions[0]["timestamp"]
        _save_memory(project, memory)

        response = client.get(f"/api/memory/{project}/tamper-detection")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "compromised"
        flag_types = {f["type"] for f in data["flags"]}
        assert "timestamp_anomaly" in flag_types
        assert "content_edited" in flag_types

    def test_timestamp_anomaly_alone_stays_low_confidence(self, client, project):
        """Same ordering irregularity as above, but on decisions with no
        stored hash (e.g. legacy data predating P2) -- content_edited can't
        fire without a hash to compare against, so this stays exactly the
        low-confidence signal it always was."""
        client.post(f"/api/memory/{project}/decisions", json={
            "decision": "First", "context": "", "safety_metadata": {"safety_category": "general"},
        })
        client.post(f"/api/memory/{project}/decisions", json={
            "decision": "Second", "context": "", "safety_metadata": {"safety_category": "general"},
        })

        memory = _load_memory(project)
        decisions = memory["decisions"]
        for d in decisions:
            d.pop("decision_hash", None)
        decisions[0]["timestamp"], decisions[1]["timestamp"] = decisions[1]["timestamp"], decisions[0]["timestamp"]
        _save_memory(project, memory)

        response = client.get(f"/api/memory/{project}/tamper-detection")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "alert"
        flag_types = {f["type"] for f in data["flags"]}
        assert "timestamp_anomaly" in flag_types
        assert "content_edited" not in flag_types
        anomaly = next(f for f in data["flags"] if f["type"] == "timestamp_anomaly")
        assert anomaly["severity"] == "low"
        assert "not conclusive" in anomaly["message"].lower()

    def test_duplicate_ids_is_compromised_with_high_severity(self, client, project):
        client.post(f"/api/memory/{project}/decisions", json={
            "decision": "First", "context": "", "safety_metadata": {"safety_category": "general"},
        })

        memory = _load_memory(project)
        original = memory["decisions"][0]
        memory["decisions"].append({**original})  # exact duplicate, including id
        _save_memory(project, memory)

        response = client.get(f"/api/memory/{project}/tamper-detection")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "compromised"
        flag_types = {f["type"] for f in data["flags"]}
        assert "duplicate_ids" in flag_types

    def test_malformed_id_is_compromised(self, client, project):
        client.post(f"/api/memory/{project}/decisions", json={
            "decision": "First", "context": "", "safety_metadata": {"safety_category": "general"},
        })

        memory = _load_memory(project)
        memory["decisions"][0]["id"] = "not-a-real-id"
        _save_memory(project, memory)

        response = client.get(f"/api/memory/{project}/tamper-detection")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "compromised"
        flag_types = {f["type"] for f in data["flags"]}
        assert "malformed_ids" in flag_types


class TestSecurityAuditLog:
    def test_empty_project(self, client, project):
        response = client.get(f"/api/memory/{project}/security/audit-log")
        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["total_events"] == 0

    def test_with_decisions(self, client, project, sample_decisions):
        response = client.get(f"/api/memory/{project}/security/audit-log")
        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["decision_events"] == 3


class TestAuditLogTamperEvidence:
    """Proves the actual value of the append-only audit_log rewrite: before
    this, provenance/chain and security/audit-log were recomputed from the
    current (mutable) decisions list on every call, with chain_valid
    hardcoded True — editing history directly in the memory JSON produced a
    perfectly clean-looking response. These tests directly edit an
    audit_log entry the way a rogue direct-file-edit would, and assert the
    tampering is now actually detected, which the old implementation could
    never do regardless of what was edited.
    """

    def test_decision_creation_writes_a_real_chained_entry(self, client, project):
        resp = client.post(f"/api/memory/{project}/decisions", json={
            "decision": "First", "context": "", "safety_metadata": {"safety_category": "general"},
        })
        assert resp.status_code == 200

        memory = _load_memory(project)
        audit_log = memory["audit_log"]
        assert len(audit_log) == 1
        assert audit_log[0]["event_type"] == "decision_created"
        assert audit_log[0]["previous_hash"] == "genesis"
        assert audit_log[0]["hash"]

    def test_editing_an_audit_log_entry_is_detected_as_tampering(self, client, project):
        client.post(f"/api/memory/{project}/decisions", json={
            "decision": "Original text", "context": "", "safety_metadata": {"safety_category": "general"},
        })

        memory = _load_memory(project)
        memory["audit_log"][0]["decision"] = "Tampered text"  # content edited, hash untouched
        _save_memory(project, memory)

        chain = client.get(f"/api/memory/{project}/provenance/chain").json()
        assert chain["chain"][0]["chain_valid"] is False

        integrity = client.get(f"/api/memory/{project}/integrity/verify").json()
        issue_types = {i["type"] for i in integrity["issues"]}
        assert "entry_hash_mismatch" in issue_types
        assert integrity["valid"] is False

    def test_deleting_an_audit_log_entry_breaks_the_chain_link(self, client, project):
        client.post(f"/api/memory/{project}/decisions", json={
            "decision": "First", "context": "", "safety_metadata": {"safety_category": "general"},
        })
        client.post(f"/api/memory/{project}/decisions", json={
            "decision": "Second", "context": "", "safety_metadata": {"safety_category": "general"},
        })

        memory = _load_memory(project)
        del memory["audit_log"][0]  # remove the genesis entry, leaving a dangling previous_hash
        _save_memory(project, memory)

        integrity = client.get(f"/api/memory/{project}/integrity/verify").json()
        issue_types = {i["type"] for i in integrity["issues"]}
        assert "chain_link_broken" in issue_types

    def test_clean_audit_log_passes_verification(self, client, project, sample_decisions):
        integrity = client.get(f"/api/memory/{project}/integrity/verify").json()
        assert integrity["valid"] is True
        assert integrity["issues"] == []

    def test_review_and_version_events_are_independently_chained(self, client, project):
        created = client.post(f"/api/memory/{project}/decisions", json={
            "decision": "First", "context": "", "safety_metadata": {"safety_category": "general"},
        }).json()["decision"]

        client.post(
            f"/api/memory/{project}/decisions/{created['id']}/review",
            json={"reviewer": "alice", "status": "approved"},
        )
        client.post(f"/api/memory/{project}/decisions/{created['id']}/version?change_reason=edit")

        memory = _load_memory(project)
        audit_log = memory["audit_log"]
        # An approval flips safety_metadata.requires_review, which is a
        # hash-covered field (P2) -- resync_decision_hash records its own
        # decision_updated event ahead of review_submitted.
        assert [e["event_type"] for e in audit_log] == [
            "decision_created", "decision_updated", "review_submitted", "version_created",
        ]
        # Each entry's previous_hash must chain to the prior entry's actual hash.
        assert audit_log[1]["previous_hash"] == audit_log[0]["hash"]
        assert audit_log[2]["previous_hash"] == audit_log[1]["hash"]
        assert audit_log[3]["previous_hash"] == audit_log[2]["hash"]

        integrity = client.get(f"/api/memory/{project}/integrity/verify").json()
        assert integrity["valid"] is True
