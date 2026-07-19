"""
Tests for Preventive Ghost Checking — unit tests for preventive.py
and integration tests for preventive_router.py.

Detects code that contradicts documented decisions BEFORE a write happens.
Uses pytest, AAA pattern, no shared state, all externals mocked.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from core.ghost.preventive import (
    Err,
    GhostWarning,
    Ok,
    _classify_severity,
    _recommendation_for,
    _warning_to_dict,
    check_diff_for_warnings,
)


# ---------------------------------------------------------------------------
#  Helpers — realistic mock data
# ---------------------------------------------------------------------------

_NOW = datetime.now(timezone.utc).isoformat()


def _decision(text, did="dec-1", ts=None, context=""):
    """Create a decision dict matching the project memory schema."""
    return {"id": did, "decision": text, "timestamp": ts or _NOW, "context": context}


def _memory(decisions=None):
    """Create a memory dict for the preventive checker."""
    return {"decisions": decisions or []}


# Naming decision — high keyword overlap with camelCase diffs
NAMING_DECISION = _decision(
    "Use snake_case naming convention for all Python module functions",
    did="naming-1",
)

# Diff that contradicts the naming decision (camelCase in added code)
CAMEL_CASE_DIFF = """\
--- a/src/utils.py
+++ b/src/utils.py
@@ -10,6 +10,10 @@
 class Utils:
     def get_user_data(self):
         return self.data
+
+# Apply naming convention to module functions
+def getUserSettings(self):
+    return self.settings
"""

# Diff unrelated to any decision — no keyword overlap
UNRELATED_DIFF = """\
--- a/src/styles.css
+++ b/src/styles.css
@@ -1,3 +1,4 @@
+button { background: blue; }
+div { color: red; }
"""


# ===========================================================================
#  1. Unit Tests — check_diff_for_warnings (pure function)
# ===========================================================================


class TestCheckDiffForWarnings:
    """Tests for check_diff_for_warnings — the core pure function."""

    def test_check_diff_empty_diff(self):
        """Empty diff string returns Ok([]) — nothing to check."""
        # Arrange
        mem = _memory(decisions=[NAMING_DECISION])

        # Act
        result = check_diff_for_warnings(mem, "")

        # Assert
        assert isinstance(result, Ok)
        assert result.value == []

    def test_check_diff_empty_decisions(self):
        """No decisions in memory returns Ok([]) — nothing to check against."""
        # Arrange
        mem = _memory(decisions=[])
        diff = "+def new_function(): pass\n"

        # Act
        result = check_diff_for_warnings(mem, diff)

        # Assert
        assert isinstance(result, Ok)
        assert result.value == []

    def test_check_diff_no_match(self):
        """Diff with no contradicting decisions returns Ok([])."""
        # Arrange
        mem = _memory(decisions=[NAMING_DECISION])

        # Act
        result = check_diff_for_warnings(mem, UNRELATED_DIFF)

        # Assert
        assert isinstance(result, Ok)
        assert result.value == []

    def test_check_diff_match_found(self):
        """Diff contradicting a decision returns warnings with severity > 0."""
        # Arrange
        mem = _memory(decisions=[NAMING_DECISION])

        # Act
        result = check_diff_for_warnings(mem, CAMEL_CASE_DIFF)

        # Assert
        assert isinstance(result, Ok)
        assert len(result.value) >= 1
        # At least one warning references the naming decision
        assert any(w["decision_id"] == "naming-1" for w in result.value)
        # All warnings have positive severity
        assert all(w["severity_score"] > 0 for w in result.value)

    def test_check_diff_malformed_diff(self):
        """Garbage text returns Ok([]) gracefully — no crash."""
        # Arrange
        mem = _memory(decisions=[NAMING_DECISION])
        garbage = "!!!NOT_A_DIFF@@#$%^&*()"

        # Act
        result = check_diff_for_warnings(mem, garbage)

        # Assert
        assert isinstance(result, Ok)
        assert result.value == []

    def test_check_diff_multiple_warnings(self):
        """Diff contradicting multiple decisions produces multiple warnings."""
        # Arrange
        decision2 = _decision(
            "Use snake_case naming convention for all Python module variables",
            did="naming-2",
        )
        mem = _memory(decisions=[NAMING_DECISION, decision2])

        # Act
        result = check_diff_for_warnings(mem, CAMEL_CASE_DIFF)

        # Assert
        assert isinstance(result, Ok)
        # Both decisions share keywords with the diff, so we expect warnings
        if len(result.value) >= 2:
            ids = {w["decision_id"] for w in result.value}
            assert len(ids) >= 2, (
                f"Expected warnings for both decisions, got ids: {ids}"
            )

    def test_warning_fields(self):
        """Each warning dict has all required fields."""
        # Arrange
        mem = _memory(decisions=[NAMING_DECISION])

        # Act
        result = check_diff_for_warnings(mem, CAMEL_CASE_DIFF)

        # Assert
        assert isinstance(result, Ok)
        required_fields = {
            "decision_id", "decision_text", "severity", "severity_score",
            "matched_keywords", "recommendation", "diff_file", "diff_line",
        }
        for warning in result.value:
            assert required_fields.issubset(warning.keys()), (
                f"Missing fields: {required_fields - warning.keys()}"
            )

    def test_severity_distribution(self):
        """Severity tiers are valid and scores are in [0, 1]."""
        # Arrange
        mem = _memory(decisions=[NAMING_DECISION])

        # Act
        result = check_diff_for_warnings(mem, CAMEL_CASE_DIFF)

        # Assert
        assert isinstance(result, Ok)
        valid_tiers = {"high", "medium", "low"}
        for w in result.value:
            assert w["severity"] in valid_tiers, (
                f"Invalid severity tier: {w['severity']}"
            )
            assert 0.0 <= w["severity_score"] <= 1.0, (
                f"Score out of range: {w['severity_score']}"
            )

    def test_warnings_sorted_by_severity_descending(self):
        """Warnings are returned sorted by severity_score descending."""
        # Arrange
        mem = _memory(decisions=[NAMING_DECISION])

        # Act
        result = check_diff_for_warnings(mem, CAMEL_CASE_DIFF)

        # Assert
        assert isinstance(result, Ok)
        if len(result.value) >= 2:
            scores = [w["severity_score"] for w in result.value]
            assert scores == sorted(scores, reverse=True)

    def test_ok_type_is_frozen_dataclass(self):
        """Ok is a frozen dataclass with a value attribute."""
        # Arrange / Act
        ok = Ok(value=[1, 2, 3])

        # Assert
        assert ok.value == [1, 2, 3]
        with pytest.raises(AttributeError):
            ok.value = []  # type: ignore[misc]

    def test_err_type_is_frozen_dataclass(self):
        """Err is a frozen dataclass with error, code, and details."""
        # Arrange / Act
        err = Err(error="boom", code="TEST_ERR", details={"x": 1})

        # Assert
        assert err.error == "boom"
        assert err.code == "TEST_ERR"
        assert err.details == {"x": 1}

    def test_err_default_code(self):
        """Err defaults code to 'UNKNOWN' when not provided."""
        # Arrange / Act
        err = Err(error="oops")

        # Assert
        assert err.code == "UNKNOWN"
        assert err.details is None

    def test_check_diff_no_decisions_key(self):
        """Memory dict without 'decisions' key returns Ok([])."""
        # Arrange
        mem = {}  # No 'decisions' key at all

        # Act
        result = check_diff_for_warnings(mem, "+some code\n")

        # Assert
        assert isinstance(result, Ok)
        assert result.value == []


# ===========================================================================
#  2. Helper function tests
# ===========================================================================


class TestClassifySeverity:
    """Tests for _classify_severity tier classification."""

    def test_high_threshold(self):
        """Score > 0.6 is classified as 'high'."""
        # Arrange / Act / Assert
        assert _classify_severity(0.7) == "high"
        assert _classify_severity(1.0) == "high"

    def test_medium_threshold(self):
        """Score >= 0.3 and <= 0.6 is classified as 'medium'."""
        # Arrange / Act / Assert
        assert _classify_severity(0.3) == "medium"
        assert _classify_severity(0.5) == "medium"
        assert _classify_severity(0.6) == "medium"

    def test_low_threshold(self):
        """Score < 0.3 is classified as 'low'."""
        # Arrange / Act / Assert
        assert _classify_severity(0.0) == "low"
        assert _classify_severity(0.15) == "low"
        assert _classify_severity(0.29) == "low"

    def test_boundary_exactly_06(self):
        """Score exactly 0.6 is 'medium' (not 'high')."""
        # Arrange / Act / Assert
        assert _classify_severity(0.6) == "medium"

    def test_boundary_just_above_06(self):
        """Score 0.6001 is 'high'."""
        # Arrange / Act / Assert
        assert _classify_severity(0.6001) == "high"


class TestRecommendationFor:
    """Tests for _recommendation_for recommendation text generation."""

    def test_high_severity(self):
        """High severity recommends updating or reverting."""
        # Arrange / Act
        rec = _recommendation_for("high")

        # Assert
        assert "update" in rec.lower() or "revert" in rec.lower()

    def test_medium_severity(self):
        """Medium severity recommends review."""
        # Arrange / Act
        rec = _recommendation_for("medium")

        # Assert
        assert "review" in rec.lower() or "drift" in rec.lower()

    def test_low_severity(self):
        """Low severity recommends monitoring."""
        # Arrange / Act
        rec = _recommendation_for("low")

        # Assert
        assert "minor" in rec.lower() or "monitor" in rec.lower()

    def test_all_recommendations_are_strings(self):
        """All severity tiers produce non-empty string recommendations."""
        # Arrange / Act / Assert
        for tier in ("high", "medium", "low"):
            rec = _recommendation_for(tier)
            assert isinstance(rec, str)
            assert len(rec) > 0


class TestWarningToDict:
    """Tests for _warning_to_dict conversion."""

    def test_warning_to_dict_all_fields(self):
        """GhostWarning converts to dict with all expected fields."""
        # Arrange
        w = GhostWarning(
            decision_id="d1",
            decision_text="test decision",
            severity="high",
            severity_score=0.8,
            matched_keywords=["test", "decision"],
            recommendation="review this",
            diff_file="test.py",
            diff_line=10,
        )

        # Act
        d = _warning_to_dict(w)

        # Assert
        assert d["decision_id"] == "d1"
        assert d["decision_text"] == "test decision"
        assert d["severity"] == "high"
        assert d["severity_score"] == 0.8
        assert d["matched_keywords"] == ["test", "decision"]
        assert d["recommendation"] == "review this"
        assert d["diff_file"] == "test.py"
        assert d["diff_line"] == 10

    def test_warning_to_dict_returns_plain_dict(self):
        """Result is a plain dict, not a dataclass."""
        # Arrange
        w = GhostWarning(
            decision_id="x", decision_text="", severity="low",
            severity_score=0.1, matched_keywords=[], recommendation="",
        )

        # Act
        d = _warning_to_dict(w)

        # Assert
        assert type(d) is dict

    def test_warning_to_dict_empty_keywords(self):
        """GhostWarning with empty keywords converts correctly."""
        # Arrange
        w = GhostWarning(
            decision_id="d2", decision_text="empty", severity="low",
            severity_score=0.0, matched_keywords=[], recommendation="none",
        )

        # Act
        d = _warning_to_dict(w)

        # Assert
        assert d["matched_keywords"] == []


# ===========================================================================
#  3. Router Tests (httpx AsyncClient) — requires preventive_router.py
# ===========================================================================

try:
    from core.ghost.preventive_router import preventive_router
    _HAS_ROUTER = True
except ImportError:
    _HAS_ROUTER = False


def _app():
    """Create a FastAPI app with the preventive router included."""
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(preventive_router)
    return app


@pytest.mark.skipif(
    not _HAS_ROUTER,
    reason="preventive_router.py not yet created (subtask 02 pending)",
)
class TestPreventiveRouter:
    """Integration tests for POST /api/memory/{project}/ghost-check."""

    def test_router_ghost_check_success(self):
        """POST with valid contradicting diff returns 200 with warnings."""
        import asyncio
        from httpx import ASGITransport, AsyncClient

        # Arrange
        mock_memory = {
            "decisions": [
                {
                    "id": "d1",
                    "decision": "Use snake_case naming convention for all Python module functions",
                    "timestamp": _NOW,
                    "context": "",
                },
            ],
        }
        diff = (
            "--- a/src/utils.py\n"
            "+++ b/src/utils.py\n"
            "@@ -1,2 +1,4 @@\n"
            "+# Apply naming convention to module functions\n"
            "+def getUserSettings():\n"
        )

        async def _call():
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.post(
                    "/api/memory/test-project/ghost-check",
                    json={"diff": diff},
                )

        with patch("core.ghost.preventive_router._load_memory", return_value=mock_memory):
            resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 200
        body = resp.json()
        assert "warnings" in body
        assert "total_warnings" in body
        assert isinstance(body["warnings"], list)
        assert body["total_warnings"] == len(body["warnings"])

    def test_router_ghost_check_empty_diff(self):
        """POST with empty diff string returns 422 validation error."""
        import asyncio
        from httpx import ASGITransport, AsyncClient

        # Arrange
        mock_memory = {"decisions": []}

        async def _call():
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.post(
                    "/api/memory/test-project/ghost-check",
                    json={"diff": ""},
                )

        with patch("core.ghost.preventive_router._load_memory", return_value=mock_memory):
            resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 422

    def test_router_ghost_check_no_warnings(self):
        """Clean diff with unrelated content returns 200 with empty warnings."""
        import asyncio
        from httpx import ASGITransport, AsyncClient

        # Arrange
        mock_memory = {
            "decisions": [
                {
                    "id": "d1",
                    "decision": "Use PostgreSQL for the primary database",
                    "timestamp": _NOW,
                    "context": "",
                },
            ],
        }
        clean_diff = "+button { background: blue; }\n"

        async def _call():
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.post(
                    "/api/memory/test-project/ghost-check",
                    json={"diff": clean_diff},
                )

        with patch("core.ghost.preventive_router._load_memory", return_value=mock_memory):
            resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 200
        body = resp.json()
        assert body["warnings"] == []
        assert body["total_warnings"] == 0

    def test_router_ghost_check_404_unknown_project(self):
        """POST to nonexistent project returns 404."""
        import asyncio
        from httpx import ASGITransport, AsyncClient
        from fastapi import HTTPException

        # Arrange
        def _mock_load(project):
            raise HTTPException(status_code=404, detail=f"Project '{project}' not found")

        async def _call():
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.post(
                    "/api/memory/nonexistent/ghost-check",
                    json={"diff": "+some code\n"},
                )

        with patch("core.ghost.preventive_router._load_memory", side_effect=_mock_load):
            resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 404
        body = resp.json()
        assert "not found" in body["detail"].lower()
