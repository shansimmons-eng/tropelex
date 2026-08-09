"""Tests for core/safety/gate.py (#54) — the required-safety-metadata gate
for high/critical-risk decisions, and its wiring into add_decision.

Unit tests exercise require_safety_metadata directly (pure function, no
I/O). Router tests exercise POST /api/memory/{project}/decisions end to
end via the real app, matching tests/test_safety_features.py's fixtures.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from core.safety.gate import SafetyMetadataRequiredError, require_safety_metadata
from core.tropebook.web.server import app


# ===========================================================================
#  1. Unit tests — require_safety_metadata (pure function)
# ===========================================================================


class TestRequireSafetyMetadata:
    def test_low_risk_is_a_no_op_even_with_nothing_provided(self):
        require_safety_metadata("low", set(), {})  # must not raise

    def test_medium_risk_is_a_no_op_even_with_nothing_provided(self):
        require_safety_metadata("medium", set(), {})  # must not raise

    def test_high_risk_with_all_fields_provided_does_not_raise(self):
        require_safety_metadata(
            "high",
            {"reversibility", "affected_systems", "requires_review"},
            {"reversibility": False, "affected_systems": ["api"], "requires_review": True},
        )

    def test_critical_risk_with_all_fields_provided_does_not_raise(self):
        require_safety_metadata(
            "critical",
            {"reversibility", "affected_systems", "requires_review"},
            {},
        )

    def test_high_risk_missing_everything_raises(self):
        with pytest.raises(SafetyMetadataRequiredError) as exc_info:
            require_safety_metadata("high", set(), {"reversibility": True})
        err = exc_info.value
        assert err.risk_level == "high"
        assert set(err.missing) == {"reversibility", "affected_systems", "requires_review"}

    def test_high_risk_missing_one_field_raises_with_only_that_field(self):
        with pytest.raises(SafetyMetadataRequiredError) as exc_info:
            require_safety_metadata(
                "high", {"reversibility", "affected_systems"}, {"requires_review": True}
            )
        assert exc_info.value.missing == ["requires_review"]

    def test_error_to_dict_carries_suggestion_scoped_to_required_fields(self):
        suggested = {
            "reversibility": False, "affected_systems": ["auth"],
            "requires_review": True, "safety_category": "governance",
        }
        with pytest.raises(SafetyMetadataRequiredError) as exc_info:
            require_safety_metadata("critical", set(), suggested)
        d = exc_info.value.to_dict()
        assert d["error"] == "safety_metadata_required"
        assert d["risk_level"] == "critical"
        assert set(d["missing_fields"]) == {"reversibility", "affected_systems", "requires_review"}
        # Scoped to the gated fields only — not the whole suggestion dict.
        assert set(d["suggested"].keys()) == {"reversibility", "affected_systems", "requires_review"}
        assert "safety_category" not in d["suggested"]


# ===========================================================================
#  2. Router tests — POST /api/memory/{project}/decisions end to end
# ===========================================================================


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def project() -> str:
    import uuid
    name = f"test_safety_gate_{uuid.uuid4().hex[:8]}"
    TestClient(app).post("/api/memory", json={"project_name": name})
    return name


class TestAddDecisionSafetyGate:
    def test_low_risk_decision_needs_only_category(self, client, project):
        resp = client.post(f"/api/memory/{project}/decisions", json={
            "decision": "Rename a helper function for clarity",
            "context": "",
            "safety_metadata": {"safety_category": "general"},
        })
        assert resp.status_code == 200

    def test_high_risk_text_without_explicit_fields_is_rejected(self, client, project):
        resp = client.post(f"/api/memory/{project}/decisions", json={
            "decision": "Delete the production database schema",
            "context": "",
            "safety_metadata": {"safety_category": "governance"},
        })
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["error"] == "safety_metadata_required"
        assert detail["risk_level"] in ("high", "critical")
        assert set(detail["missing_fields"]) <= {"reversibility", "affected_systems", "requires_review"}
        assert detail["missing_fields"]  # non-empty

    def test_high_risk_text_with_explicit_fields_succeeds(self, client, project):
        resp = client.post(f"/api/memory/{project}/decisions", json={
            "decision": "Delete the production database schema",
            "context": "",
            "safety_metadata": {
                "safety_category": "governance",
                "reversibility": False,
                "affected_systems": ["database"],
                "requires_review": True,
            },
        })
        assert resp.status_code == 200
        data = resp.json()["decision"]["safety_metadata"]
        assert data["risk_level"] in ("high", "critical")
        assert data["reversibility"] is False
        assert data["requires_review"] is True

    def test_explicit_high_risk_level_on_otherwise_mild_text_is_still_gated(self, client, project):
        """The gate keys off the *resolved* risk_level, not just the
        heuristic — a caller explicitly marking a mild-sounding decision
        as high-risk still has to explicitly justify the other fields."""
        resp = client.post(f"/api/memory/{project}/decisions", json={
            "decision": "Update the README wording",
            "context": "",
            "safety_metadata": {"safety_category": "general", "risk_level": "high"},
        })
        assert resp.status_code == 422
        assert resp.json()["detail"]["risk_level"] == "high"
