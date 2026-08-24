"""Tests for core/safety/classifier.py (wishlist #73) -- SafetyMetadata and
auto_classify_safety, moved out of core/tropebook/web/server.py's inline
safety block. Pure model + pure function, no I/O, so tested directly at
their new home the same way tests/test_safety_gate.py tests gate.py.

Router-level behavior (add_decision, preview-category endpoint) is already
covered end to end by tests/test_safety_features.py and
tests/test_alignment_governance.py -- this file locks in the classifier's
own behavior at its relocated import path, not a duplicate of those.
"""

from __future__ import annotations

from core.safety.classifier import SafetyMetadata, auto_classify_safety


class TestSafetyMetadataModel:
    def test_defaults(self):
        m = SafetyMetadata()
        assert m.risk_level == "low"
        assert m.reversibility is True
        assert m.affected_systems == []
        assert m.safety_category is None

    def test_rejects_invalid_risk_level(self):
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SafetyMetadata(risk_level="extreme")

    def test_rejects_invalid_safety_category(self):
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SafetyMetadata(safety_category="not-a-real-category")

    def test_accepts_a_real_safety_category(self):
        m = SafetyMetadata(safety_category="governance")
        assert m.safety_category == "governance"


class TestAutoClassifySafety:
    def test_low_risk_default(self):
        result = auto_classify_safety("Use tabs for indentation", "")
        assert result["risk_level"] == "low"
        assert result["requires_review"] is False

    def test_critical_risk_keyword(self):
        result = auto_classify_safety("Run rm -rf on the staging bucket", "")
        assert result["risk_level"] == "critical"
        assert result["requires_review"] is True

    def test_high_risk_keyword(self):
        result = auto_classify_safety("Rotate the production API key", "")
        assert result["risk_level"] == "high"
        assert result["requires_review"] is True

    def test_medium_risk_keyword(self):
        result = auto_classify_safety("Update the dependency version", "")
        assert result["risk_level"] == "medium"
        assert result["requires_review"] is False

    def test_category_classification(self):
        result = auto_classify_safety("Add a red team exercise for the login flow", "")
        assert result["safety_category"] == "adversarial"

    def test_category_defaults_to_general(self):
        result = auto_classify_safety("Rename the button label", "")
        assert result["safety_category"] == "general"

    def test_irreversible_keyword(self):
        result = auto_classify_safety("Delete the old backup table", "")
        assert result["reversibility"] is False

    def test_reversible_keyword(self):
        result = auto_classify_safety("Add a new caching layer", "")
        assert result["reversibility"] is True

    def test_affected_systems_detection(self):
        result = auto_classify_safety("Fix the login auth session bug", "")
        assert "auth" in result["affected_systems"]

    def test_returns_all_expected_fields(self):
        result = auto_classify_safety("test decision", "test context")
        assert set(result.keys()) == {
            "risk_level", "reversibility", "affected_systems",
            "rationale_quality", "alignment_considerations", "requires_review",
            "safety_category",
        }

    def test_considers_both_decision_and_context(self):
        result = auto_classify_safety("Update the config", "This touches production credentials")
        assert result["risk_level"] == "high"
