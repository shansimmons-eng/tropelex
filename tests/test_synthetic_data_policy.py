"""Tests for Synthetic Data Policy feature."""

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
    return f"test_synth_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def sample_policy():
    return {
        "dataset_name": "Customer Transactions v2",
        "generated_by": "MOSTLY AI",
        "authorized_by": "Jane Smith (DPO)",
        "source_seed_data": "Real customer transactions from 2024, GDPR Art. 6(1)(b) - contract performance",
        "synthetic_real_ratio": "100 real:10000 synthetic",
        "models_used": "CTGAN with default hyperparameters",
        "architecture_type": "gan",
        "eu_ai_act_tier": "high",
        "data_types": ["Tabular", "Time-Series"],
        "purpose": "Training fraud detection model without exposing real customer data",
        "operational_constraints": "Never use for credit scoring or lending decisions",
        "rationale": "Real data contains PII that cannot be shared with third-party ML vendors",
        "fidelity_score": "KS statistic: 0.92, Wasserstein: 0.08",
        "utility_validation": "TSTR accuracy: 94.2% (vs 95.1% on real data)",
        "dp_epsilon": 1.0,
        "dp_delta": 0.00001,
        "privacy_parameters": "ε=1.0, δ=0.00001",
        "bias_audit_results": "Demographic parity ratio: 0.98 (within acceptable range)",
        "adversarial_testing": "MIA success rate: 52.1% (barely above random), AIA: 51.8%",
        "distinguishability_marking": "Watermarked with synthetic data tag in metadata field",
        "attested_by": "Third-party auditor (PrivacyCo)",
        "retention_deletion": "Delete after 12 months or upon model retirement",
        "review_date": "2026-12-31",
    }


@pytest.fixture
def minimal_policy():
    return {
        "dataset_name": "Test Dataset",
        "generated_by": "SDV",
        "source_seed_data": "Test data",
        "synthetic_real_ratio": "10:100",
        "models_used": "Gaussian Copula",
        "purpose": "Testing",
        "rationale": "Need synthetic data for unit tests",
    }


class TestCreateSyntheticDataPolicy:
    def test_create_full_policy(self, client, project, sample_policy):
        response = client.post(f"/api/memory/{project}/synthetic-data-policies", json=sample_policy)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["compliance_status"] == "compliant"

    def test_create_minimal_policy(self, client, project, minimal_policy):
        response = client.post(f"/api/memory/{project}/synthetic-data-policies", json=minimal_policy)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # Minimal policy should be partial or non-compliant due to missing fields
        assert data["compliance_status"] in ["partial", "non_compliant"]

    def test_create_policy_missing_required(self, client, project):
        response = client.post(f"/api/memory/{project}/synthetic-data-policies", json={"dataset_name": "Test"})
        assert response.status_code == 422  # Validation error


class TestListSyntheticDataPolicies:
    def test_empty_list(self, client, project):
        response = client.get(f"/api/memory/{project}/synthetic-data-policies")
        assert response.status_code == 200
        data = response.json()
        assert data["total_policies"] == 0

    def test_with_policies(self, client, project, sample_policy):
        client.post(f"/api/memory/{project}/synthetic-data-policies", json=sample_policy)
        response = client.get(f"/api/memory/{project}/synthetic-data-policies")
        assert response.status_code == 200
        data = response.json()
        assert data["total_policies"] == 1


class TestGetSyntheticDataPolicy:
    def test_get_existing(self, client, project, sample_policy):
        resp = client.post(f"/api/memory/{project}/synthetic-data-policies", json=sample_policy)
        policy_id = resp.json()["policy_id"]
        
        response = client.get(f"/api/memory/{project}/synthetic-data-policies/{policy_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == policy_id

    def test_get_nonexistent(self, client, project):
        response = client.get(f"/api/memory/{project}/synthetic-data-policies/fake_id")
        assert response.status_code == 404


class TestUpdateSyntheticDataPolicy:
    def test_update_existing(self, client, project, sample_policy):
        resp = client.post(f"/api/memory/{project}/synthetic-data-policies", json=sample_policy)
        policy_id = resp.json()["policy_id"]
        
        updated = {**sample_policy, "dataset_name": "Updated Dataset Name"}
        response = client.put(f"/api/memory/{project}/synthetic-data-policies/{policy_id}", json=updated)
        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_update_nonexistent(self, client, project, sample_policy):
        response = client.put(f"/api/memory/{project}/synthetic-data-policies/fake_id", json=sample_policy)
        assert response.status_code == 404


class TestDeleteSyntheticDataPolicy:
    def test_delete_existing(self, client, project, sample_policy):
        resp = client.post(f"/api/memory/{project}/synthetic-data-policies", json=sample_policy)
        policy_id = resp.json()["policy_id"]
        
        response = client.delete(f"/api/memory/{project}/synthetic-data-policies/{policy_id}")
        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_delete_nonexistent(self, client, project):
        response = client.delete(f"/api/memory/{project}/synthetic-data-policies/fake_id")
        assert response.status_code == 404


class TestComplianceCheck:
    def test_compliant_policy(self, client, project, sample_policy):
        resp = client.post(f"/api/memory/{project}/synthetic-data-policies", json=sample_policy)
        policy_id = resp.json()["policy_id"]
        
        response = client.get(f"/api/memory/{project}/synthetic-data-policies/{policy_id}/compliance")
        assert response.status_code == 200
        data = response.json()
        assert data["compliance_status"] == "compliant"
        assert "blocking_gates" in data

    def test_nonexistent_policy(self, client, project):
        response = client.get(f"/api/memory/{project}/synthetic-data-policies/fake_id/compliance")
        assert response.status_code == 404


class TestSyntheticDataSummary:
    def test_empty_summary(self, client, project):
        response = client.get(f"/api/memory/{project}/synthetic-data/summary")
        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["total_policies"] == 0

    def test_with_policies(self, client, project, sample_policy, minimal_policy):
        client.post(f"/api/memory/{project}/synthetic-data-policies", json=sample_policy)
        client.post(f"/api/memory/{project}/synthetic-data-policies", json=minimal_policy)
        
        response = client.get(f"/api/memory/{project}/synthetic-data/summary")
        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["total_policies"] == 2
        assert "tier_distribution" in data
        assert "architecture_distribution" in data


class TestBlockingGates:
    def test_fidelity_gate(self, client, project, minimal_policy):
        """Minimal policy without fidelity score should fail fidelity gate."""
        resp = client.post(f"/api/memory/{project}/synthetic-data-policies", json=minimal_policy)
        policy_id = resp.json()["policy_id"]
        
        response = client.get(f"/api/memory/{project}/synthetic-data-policies/{policy_id}/compliance")
        data = response.json()
        assert data["blocking_gates"]["fidelity"]["passed"] is False

    def test_high_risk_requires_privacy(self, client, project, sample_policy):
        """High-risk policy with privacy params should pass privacy gate."""
        resp = client.post(f"/api/memory/{project}/synthetic-data-policies", json=sample_policy)
        policy_id = resp.json()["policy_id"]
        
        response = client.get(f"/api/memory/{project}/synthetic-data-policies/{policy_id}/compliance")
        data = response.json()
        assert data["blocking_gates"]["privacy"]["passed"] is True
