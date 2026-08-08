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

    def test_timestamp_only_anomaly_is_alert_not_compromised(self, client, project):
        """A single ordering irregularity (the only kind of flag a normal
        multi-agent/backdated-import workflow can trigger) must read as a
        low-confidence alert, not an assertion that the project was
        compromised — that word is reserved for structural violations the
        API's own validation would never allow through."""
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
        assert data["status"] == "alert"
        assert data["flags"][0]["type"] == "timestamp_anomaly"
        assert data["flags"][0]["severity"] == "low"
        assert "not conclusive" in data["flags"][0]["message"].lower()

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
