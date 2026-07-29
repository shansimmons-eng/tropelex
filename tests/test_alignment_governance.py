"""Tests for Alignment Evaluation & Governance features."""

from __future__ import annotations

import uuid
import pytest
from fastapi.testclient import TestClient

from core.tropebook.web.server import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def project():
    return f"test_alignment_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def sample_decision_high_risk():
    return {
        "decision": "Deploy critical security patch to production",
        "context": "Zero-day vulnerability requires immediate action",
        "safety_metadata": {
            "risk_level": "high",
            "reversibility": False,
            "affected_systems": ["api", "database", "auth"],
            "requires_review": True,
            "safety_category": "robustness",
            "alignment_considerations": "Critical security infrastructure change",
        },
    }


@pytest.fixture
def sample_decision_low_risk():
    return {
        "decision": "Update documentation for API endpoints",
        "context": "Minor documentation improvements",
        "safety_metadata": {
            "risk_level": "low",
            "reversibility": True,
            "affected_systems": ["docs"],
            "requires_review": False,
            "safety_category": "general",
        },
    }


class TestAlignmentEvaluateEndpoint:
    """Tests for GET /api/memory/{project}/alignment/evaluate."""

    def test_empty_project(self, client, project):
        response = client.get(f"/api/memory/{project}/alignment/evaluate")
        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["total_decisions"] == 0
        assert data["summary"]["alignment_score"] == 1.0

    def test_with_decisions(self, client, project, sample_decision_high_risk):
        client.post(f"/api/memory/{project}/decisions", json=sample_decision_high_risk)

        response = client.get(f"/api/memory/{project}/alignment/evaluate")
        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["total_decisions"] >= 1
        assert "category_scores" in data
        assert "criteria_used" in data

    def test_category_scores_present(self, client, project, sample_decision_high_risk):
        client.post(f"/api/memory/{project}/decisions", json=sample_decision_high_risk)

        response = client.get(f"/api/memory/{project}/alignment/evaluate")
        data = response.json()
        assert "interpretability" in data["category_scores"]
        assert "safety" in data["category_scores"]
        assert "fairness" in data["category_scores"]


class TestDecisionAlignmentEndpoint:
    """Tests for POST /api/memory/{project}/decisions/{decision_id}/alignment."""

    def test_nonexistent_decision(self, client, project):
        response = client.post(f"/api/memory/{project}/decisions/fake_id/alignment", json={})
        assert response.status_code == 404

    def test_existing_decision(self, client, project, sample_decision_high_risk):
        resp = client.post(f"/api/memory/{project}/decisions", json=sample_decision_high_risk)
        decision_id = resp.json()["decision"]["id"]

        response = client.post(f"/api/memory/{project}/decisions/{decision_id}/alignment", json={})
        assert response.status_code == 200
        data = response.json()
        assert "evaluation" in data
        assert data["evaluation"]["decision_id"] == decision_id

    def test_with_governance_check(self, client, project, sample_decision_high_risk):
        resp = client.post(f"/api/memory/{project}/decisions", json=sample_decision_high_risk)
        decision_id = resp.json()["decision"]["id"]

        response = client.post(
            f"/api/memory/{project}/decisions/{decision_id}/alignment",
            json={"include_governance_check": True},
        )
        assert response.status_code == 200
        data = response.json()
        assert "governance_check" in data

    def test_with_safety_case(self, client, project, sample_decision_high_risk):
        resp = client.post(f"/api/memory/{project}/decisions", json=sample_decision_high_risk)
        decision_id = resp.json()["decision"]["id"]

        response = client.post(
            f"/api/memory/{project}/decisions/{decision_id}/alignment",
            json={"include_safety_case": True},
        )
        assert response.status_code == 200
        data = response.json()
        assert "safety_case" in data

    def test_custom_criteria(self, client, project, sample_decision_high_risk):
        resp = client.post(f"/api/memory/{project}/decisions", json=sample_decision_high_risk)
        decision_id = resp.json()["decision"]["id"]

        response = client.post(
            f"/api/memory/{project}/decisions/{decision_id}/alignment",
            json={
                "criteria": [
                    {"name": "custom_check", "description": "Custom test", "weight": 1.0, "category": "general"}
                ]
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["evaluation"]["criteria_evaluated"]) == 1


class TestGovernancePoliciesEndpoint:
    """Tests for GET /api/memory/{project}/governance/policies."""

    def test_get_policies(self, client, project):
        response = client.get(f"/api/memory/{project}/governance/policies")
        assert response.status_code == 200
        data = response.json()
        assert "default_policies" in data
        assert "project_policies" in data
        assert data["total_policies"] >= 5


class TestGovernanceComplianceEndpoint:
    """Tests for GET /api/memory/{project}/governance/compliance."""

    def test_empty_project(self, client, project):
        response = client.get(f"/api/memory/{project}/governance/compliance")
        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["total_decisions"] == 0
        assert data["summary"]["compliance_rate"] == 1.0

    def test_with_decisions(self, client, project, sample_decision_high_risk):
        client.post(f"/api/memory/{project}/decisions", json=sample_decision_high_risk)

        response = client.get(f"/api/memory/{project}/governance/compliance")
        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["total_decisions"] >= 1

    def test_compliance_violations(self, client, project, sample_decision_high_risk):
        client.post(f"/api/memory/{project}/decisions", json=sample_decision_high_risk)

        response = client.get(f"/api/memory/{project}/governance/compliance")
        data = response.json()
        # High-risk decision without review should have violations
        assert data["summary"]["non_compliant_count"] >= 1


class TestInterpretabilityEndpoint:
    """Tests for GET /api/memory/{project}/interpretability/{decision_id}."""

    def test_nonexistent_decision(self, client, project):
        response = client.get(f"/api/memory/{project}/interpretability/fake_id")
        assert response.status_code == 404

    def test_existing_decision(self, client, project, sample_decision_high_risk):
        resp = client.post(f"/api/memory/{project}/decisions", json=sample_decision_high_risk)
        decision_id = resp.json()["decision"]["id"]

        response = client.get(f"/api/memory/{project}/interpretability/{decision_id}")
        assert response.status_code == 200
        data = response.json()
        assert "report" in data
        assert "factors" in data["report"]
        assert "explanation" in data["report"]

    def test_missing_risk_level_key(self, client, project):
        """Regression: a decision whose safety_metadata has no risk_level key
        at all (vs. explicitly "low") used to 500 with KeyError. `safety.get(
        "risk_level") != "low"` is True for both a missing key and a real
        non-low value, but the branch then did a direct safety['risk_level']
        bracket access. The public API always fills in a default via the
        SafetyMetadata pydantic model, so this writes the decision directly
        to reproduce the malformed shape that slipped through in practice."""
        from core.tropebook.web.server import get_memory_manager

        mm = get_memory_manager()
        memory = mm.get_project_memory(project)
        memory.setdefault("decisions", []).append(
            {
                "id": "no_risk_level_decision",
                "timestamp": "2026-01-01T00:00:00+00:00",
                "decision": "Legacy decision with no risk metadata",
                "context": "",
                "safety_metadata": {"affected_systems": []},
            }
        )
        mm.save_project_memory(project, memory)

        response = client.get(f"/api/memory/{project}/interpretability/no_risk_level_decision")
        assert response.status_code == 200
        data = response.json()
        assert "report" in data
