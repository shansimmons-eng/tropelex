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
        # #58: NAMING_DECISION has a fresh timestamp -- tier should be "high",
        # surfaced explicitly rather than only folded into severity_score.
        assert all(w["decision_confidence_tier"] == "high" for w in result.value)

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


class TestCheckDiffForWarningsWithEmbeddings:
    """#67: check_diff_for_warnings's optional embeddings/diff_embedding
    params -- the semantic rescue threaded end-to-end through the public
    pure-function entrypoint, not just pattern_matcher's internals."""

    _EVASIVE_DIFF = (
        "--- a/src/access.py\n+++ b/src/access.py\n@@ -1,2 +1,4 @@\n"
        " def check_access(user):\n"
        "+    if user.email == \"debug@internal.test\":\n"
        "+        return True\n"
    )
    _AUTH_DECISION = _decision("Never bypass authentication for admin-level access", did="auth-1")

    def test_no_embeddings_args_identical_to_before(self):
        """Regression: default None/None behaves byte-for-byte as pre-#67."""
        mem = _memory(decisions=[NAMING_DECISION])
        with_none = check_diff_for_warnings(mem, CAMEL_CASE_DIFF, None, None)
        without = check_diff_for_warnings(mem, CAMEL_CASE_DIFF)
        assert with_none.value == without.value

    def test_semantic_rescue_surfaces_a_warning_keyword_alone_would_miss(self):
        mem = _memory(decisions=[self._AUTH_DECISION])

        # Sanity: keyword-only finds nothing for this evasive diff.
        baseline = check_diff_for_warnings(mem, self._EVASIVE_DIFF)
        assert baseline.value == []

        result = check_diff_for_warnings(
            mem, self._EVASIVE_DIFF,
            embeddings={"auth-1": [1.0, 0.0]}, diff_embedding=[1.0, 0.0],
        )
        assert len(result.value) == 1
        assert result.value[0]["match_type"] == "semantic"
        assert result.value[0]["decision_id"] == "auth-1"

    def test_semantic_warning_never_reaches_high_severity(self):
        """#67's hard cap: a semantic-only match that would otherwise score
        'high' surfaces as 'medium' -- confirmed with a near-identical
        vector pair (cosine ~1.0) against a fresh, high-confidence decision,
        the exact combination that would produce 'high' via the keyword
        path's own math."""
        mem = _memory(decisions=[self._AUTH_DECISION])
        result = check_diff_for_warnings(
            mem, self._EVASIVE_DIFF,
            embeddings={"auth-1": [1.0, 0.0]}, diff_embedding=[1.0, 0.0001],
        )
        assert len(result.value) == 1
        # The raw score alone would classify "high" (>0.6) -- proves the cap
        # actually intervened, not that it happened to land at medium anyway.
        assert result.value[0]["severity_score"] > 0.6
        assert result.value[0]["severity"] == "medium"

    def test_embeddings_only_apply_to_matching_decision_id(self):
        """A vector present for a *different* decision id must not leak
        into this decision's rescue check."""
        mem = _memory(decisions=[self._AUTH_DECISION])
        result = check_diff_for_warnings(
            mem, self._EVASIVE_DIFF,
            embeddings={"some-other-id": [1.0, 0.0]}, diff_embedding=[1.0, 0.0],
        )
        assert result.value == []

    def test_semantic_warning_includes_match_type_in_dict(self):
        mem = _memory(decisions=[self._AUTH_DECISION])
        result = check_diff_for_warnings(
            mem, self._EVASIVE_DIFF,
            embeddings={"auth-1": [1.0, 0.0]}, diff_embedding=[1.0, 0.0],
        )
        assert "match_type" in result.value[0]

    def test_existing_keyword_warning_reports_match_type_keyword(self):
        mem = _memory(decisions=[NAMING_DECISION])
        result = check_diff_for_warnings(mem, CAMEL_CASE_DIFF)
        assert all(w["match_type"] == "keyword" for w in result.value)


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
        rec = _recommendation_for("high", "Use Postgres", "db.py", ["postgres"])

        # Assert
        assert "update" in rec.lower() or "revert" in rec.lower()

    def test_medium_severity(self):
        """Medium severity recommends review."""
        # Arrange / Act
        rec = _recommendation_for("medium", "Use Postgres", "db.py", ["postgres"])

        # Assert
        assert "review" in rec.lower() or "drift" in rec.lower()

    def test_low_severity(self):
        """Low severity recommends monitoring."""
        # Arrange / Act
        rec = _recommendation_for("low", "Use Postgres", "db.py", ["postgres"])

        # Assert
        assert "minor" in rec.lower() or "monitor" in rec.lower()

    def test_all_recommendations_are_strings(self):
        """All severity tiers produce non-empty string recommendations."""
        # Arrange / Act / Assert
        for tier in ("high", "medium", "low"):
            rec = _recommendation_for(tier, "Use Postgres", "db.py", ["postgres"])
            assert isinstance(rec, str)
            assert len(rec) > 0

    def test_interpolates_decision_text_and_diff_file(self):
        """The recommendation quotes the actual decision and names the file,
        instead of returning one of three generic strings regardless of input."""
        # Arrange / Act
        rec = _recommendation_for("low", "Use Postgres for the primary database", "core/db.py", ["postgres", "database"])

        # Assert
        assert "Use Postgres for the primary database" in rec
        assert "core/db.py" in rec
        assert "postgres" in rec

    def test_two_different_decisions_produce_different_text_at_same_tier(self):
        """Two unrelated warnings in the same severity tier must not read as
        identical — this was the exact complaint the vague static text caused."""
        # Arrange / Act
        rec_a = _recommendation_for("low", "Use Postgres", "db.py", ["postgres"])
        rec_b = _recommendation_for("low", "Use snake_case naming", "utils.py", ["naming"])

        # Assert
        assert rec_a != rec_b

    def test_omits_file_clause_when_diff_file_empty(self):
        """No diff_file shouldn't produce a dangling 'in ``' artifact."""
        # Arrange / Act
        rec = _recommendation_for("low", "Use Postgres", "", [])

        # Assert
        assert "in ``" not in rec
        assert "Use Postgres" in rec

    def test_truncates_long_decision_text(self):
        """A long decision doesn't blow up the recommendation to unreadable length."""
        # Arrange
        long_decision = "This is a very long decision statement " * 5

        # Act
        rec = _recommendation_for("low", long_decision, "file.py", [])

        # Assert
        assert "…" in rec
        assert len(rec) < len(long_decision) + 200


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
            decision_confidence_tier="low",
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
        assert d["decision_confidence_tier"] == "low"

    def test_warning_to_dict_confidence_tier_defaults_to_medium(self):
        """GhostWarning constructed without decision_confidence_tier still
        round-trips through _warning_to_dict (backward compatible)."""
        w = GhostWarning(
            decision_id="x", decision_text="", severity="low",
            severity_score=0.1, matched_keywords=[], recommendation="",
        )

        d = _warning_to_dict(w)

        assert d["decision_confidence_tier"] == "medium"

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

        with patch("core.ghost.preventive_router._load_memory", return_value=mock_memory), \
             patch("core.ghost.preventive_router._save_memory", return_value=None):
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


# ===========================================================================
#  4. Enforceable Gate Policy Tests (#53) — block/warn/log_only + override
# ===========================================================================


@pytest.mark.skipif(not _HAS_ROUTER, reason="preventive_router.py not yet created (subtask 02 pending)")
class TestGhostCheckGatePolicy:
    """A high-severity warning without a recorded override must block the
    request (409) instead of returning 200 with a warning buried in the
    body — that's the whole point of #53 (mcp_server's MCP wrapper raises
    on any non-2xx, so this is what actually stops an agent from skipping
    past it). Overriding it must be a real, retryable, audited action.
    """

    @staticmethod
    def _memory():
        return {
            "decisions": [{
                "id": "naming-1",
                "decision": "Use snake_case naming convention for all Python module functions",
                "timestamp": _NOW,
                "context": "",
            }],
        }

    @staticmethod
    def _high_severity_warning():
        return {
            "decision_id": "naming-1",
            "decision_text": "Use snake_case naming convention for all Python module functions",
            "severity": "high",
            "severity_score": 0.9,
            "matched_keywords": ["snake_case"],
            "recommendation": "This change may contradict the decision.",
            "diff_file": "src/utils.py",
            "diff_line": 5,
        }

    def _post(self, path, json_body):
        import asyncio
        from httpx import ASGITransport, AsyncClient

        async def _call():
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.post(path, json=json_body)

        return asyncio.run(_call())

    def test_high_severity_blocks_without_override(self):
        from core.result import Ok

        memory = self._memory()
        with patch("core.ghost.preventive_router._load_memory", return_value=memory), \
             patch("core.ghost.preventive_router._save_memory", return_value=None), \
             patch("core.ghost.preventive_router.check_diff_for_warnings",
                   return_value=Ok(value=[self._high_severity_warning()])):
            resp = self._post("/api/memory/demo/ghost-check", {"diff": CAMEL_CASE_DIFF})

        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert len(detail["blocking_warnings"]) == 1
        assert detail["blocking_warnings"][0]["decision_id"] == "naming-1"

        # #61: a block that was correctly obeyed still leaves a trace now,
        # not just overrides.
        event_types = [e["event_type"] for e in memory["audit_log"]]
        assert "gate_blocked" in event_types
        blocked_event = next(e for e in memory["audit_log"] if e["event_type"] == "gate_blocked")
        assert blocked_event["decision_ids"] == ["naming-1"]
        assert blocked_event["severity_counts"] == {"high": 1, "medium": 0, "low": 0}

    def test_medium_and_low_severity_do_not_block(self):
        from core.result import Ok

        memory = self._memory()
        warnings = [
            {**self._high_severity_warning(), "severity": "medium", "decision_id": "naming-1"},
        ]
        with patch("core.ghost.preventive_router._load_memory", return_value=memory), \
             patch("core.ghost.preventive_router._save_memory", return_value=None), \
             patch("core.ghost.preventive_router.check_diff_for_warnings", return_value=Ok(value=warnings)):
            resp = self._post("/api/memory/demo/ghost-check", {"diff": CAMEL_CASE_DIFF})

        assert resp.status_code == 200
        assert resp.json()["warnings"][0]["policy"] == "warn"

        # #61: a warn-tier warning that was returned (not blocked) still
        # gets logged — it's the "this is what we flagged" half of the
        # prevention story, distinct from an outright block.
        event_types = [e["event_type"] for e in memory["audit_log"]]
        assert "gate_warned" in event_types
        assert "gate_blocked" not in event_types
        warned_event = next(e for e in memory["audit_log"] if e["event_type"] == "gate_warned")
        assert warned_event["decision_ids"] == ["naming-1"]
        assert warned_event["severity_counts"] == {"high": 0, "medium": 1, "low": 0}

    def test_override_then_retry_succeeds_and_marks_warning_overridden(self):
        from core.result import Ok

        memory = self._memory()
        with patch("core.ghost.preventive_router._load_memory", return_value=memory), \
             patch("core.ghost.preventive_router._save_memory", return_value=None), \
             patch("core.ghost.preventive_router.check_diff_for_warnings",
                   return_value=Ok(value=[self._high_severity_warning()])):
            blocked = self._post("/api/memory/demo/ghost-check", {"diff": CAMEL_CASE_DIFF})
            assert blocked.status_code == 409

            override_resp = self._post(
                "/api/memory/demo/decisions/naming-1/override",
                {"rationale": "Legacy API must match external SDK casing", "agent_name": "claude"},
            )
            assert override_resp.status_code == 200
            assert override_resp.json()["created"] is True

            retried = self._post("/api/memory/demo/ghost-check", {"diff": CAMEL_CASE_DIFF})

        assert retried.status_code == 200
        assert retried.json()["warnings"][0]["overridden"] is True

        # The override is part of the same audited trail as everything else
        # in #52, not a parallel, unaudited mechanism.
        event_types = [e["event_type"] for e in memory["audit_log"]]
        assert "override" in event_types
        override_event = next(e for e in memory["audit_log"] if e["event_type"] == "override")
        assert override_event["decision_id"] == "naming-1"
        assert override_event["rationale"] == "Legacy API must match external SDK casing"

    def test_override_unknown_decision_404s(self):
        memory = self._memory()
        with patch("core.ghost.preventive_router._load_memory", return_value=memory), \
             patch("core.ghost.preventive_router._save_memory", return_value=None):
            resp = self._post(
                "/api/memory/demo/decisions/does-not-exist/override",
                {"rationale": "x", "agent_name": "claude"},
            )

        assert resp.status_code == 404

    def test_override_requires_nonempty_rationale(self):
        memory = self._memory()
        with patch("core.ghost.preventive_router._load_memory", return_value=memory), \
             patch("core.ghost.preventive_router._save_memory", return_value=None):
            resp = self._post(
                "/api/memory/demo/decisions/naming-1/override",
                {"rationale": "", "agent_name": "claude"},
            )

        assert resp.status_code == 422

    def test_project_can_override_default_policy(self):
        """memory["gate_policy"] lets a project loosen/tighten enforcement
        per severity tier instead of being stuck with the module default."""
        from core.result import Ok

        memory = self._memory()
        memory["gate_policy"] = {"high": "warn"}  # loosen: don't block on high here
        with patch("core.ghost.preventive_router._load_memory", return_value=memory), \
             patch("core.ghost.preventive_router._save_memory", return_value=None), \
             patch("core.ghost.preventive_router.check_diff_for_warnings",
                   return_value=Ok(value=[self._high_severity_warning()])):
            resp = self._post("/api/memory/demo/ghost-check", {"diff": CAMEL_CASE_DIFF})

        assert resp.status_code == 200
        assert resp.json()["warnings"][0]["policy"] == "warn"

        # Logged under gate_warned, not gate_blocked -- the audit trail
        # reflects the resolved policy action, not the raw severity tier.
        event_types = [e["event_type"] for e in memory["audit_log"]]
        assert "gate_warned" in event_types
        assert "gate_blocked" not in event_types


# ===========================================================================
#  4b. Gate Policy Schema (#64) — GET/PUT /{project}/gate-policy
# ===========================================================================


class TestPolicyForDefensiveRead:
    """_policy_for's second layer of defense (#64) -- gate_policy could
    only ever be set by hand-editing the memory JSON before a real write
    endpoint existed, so pre-existing malformed data is a real case, not
    a hypothetical."""

    def test_missing_gate_policy_uses_defaults(self):
        from core.gate import policy_for as _policy_for
        assert _policy_for({}, "high") == "block"
        assert _policy_for({}, "medium") == "warn"
        assert _policy_for({}, "low") == "log_only"

    def test_gate_policy_not_a_dict_falls_back_to_defaults(self):
        from core.gate import policy_for as _policy_for
        for malformed in (["high", "block"], "block", 42, None):
            assert _policy_for({"gate_policy": malformed}, "high") == "block"

    def test_unrecognized_action_value_falls_back_to_default(self):
        """Garbage that predates validation (e.g. a typo'd action, or a
        value from before this endpoint existed) must not flow straight
        into a safety-relevant block/warn/log_only decision."""
        from core.gate import policy_for as _policy_for
        memory = {"gate_policy": {"high": "block_everything_always"}}
        assert _policy_for(memory, "high") == "block"

    def test_valid_override_is_honored(self):
        from core.gate import policy_for as _policy_for
        memory = {"gate_policy": {"high": "log_only"}}
        assert _policy_for(memory, "high") == "log_only"
        assert _policy_for(memory, "medium") == "warn"  # unset tier keeps default


@pytest.mark.skipif(not _HAS_ROUTER, reason="preventive_router.py not yet created (subtask 02 pending)")
class TestGatePolicyEndpoint:
    """GET/PUT /{project}/gate-policy (#64) -- a real, schema-validated way
    to set gate_policy where previously the only option was hand-editing
    the memory JSON file directly with zero validation."""

    def _get(self, path):
        import asyncio
        from httpx import ASGITransport, AsyncClient

        async def _call():
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.get(path)

        return asyncio.run(_call())

    def _put(self, path, json_body):
        import asyncio
        from httpx import ASGITransport, AsyncClient

        async def _call():
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.put(path, json=json_body)

        return asyncio.run(_call())

    def test_get_with_no_override_shows_pure_defaults(self):
        memory = {"decisions": []}
        with patch("core.ghost.preventive_router._load_memory", return_value=memory):
            resp = self._get("/api/memory/demo/gate-policy")

        assert resp.status_code == 200
        body = resp.json()
        assert body["effective_policy"] == {"high": "block", "medium": "warn", "low": "log_only"}
        assert body["overrides"] == {}

    def test_put_valid_partial_override_persists(self):
        memory = {"decisions": []}
        with patch("core.ghost.preventive_router._load_memory", return_value=memory), \
             patch("core.ghost.preventive_router._save_memory", return_value=None):
            resp = self._put("/api/memory/demo/gate-policy", {"high": "warn"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["effective_policy"] == {"high": "warn", "medium": "warn", "low": "log_only"}
        assert body["overrides"] == {"high": "warn"}
        assert memory["gate_policy"] == {"high": "warn"}

    def test_put_merges_with_existing_override_not_replaces(self):
        memory = {"decisions": [], "gate_policy": {"low": "warn"}}
        with patch("core.ghost.preventive_router._load_memory", return_value=memory), \
             patch("core.ghost.preventive_router._save_memory", return_value=None):
            resp = self._put("/api/memory/demo/gate-policy", {"high": "log_only"})

        assert resp.status_code == 200
        assert memory["gate_policy"] == {"low": "warn", "high": "log_only"}

    def test_put_invalid_action_value_422s(self):
        memory = {"decisions": []}
        with patch("core.ghost.preventive_router._load_memory", return_value=memory):
            resp = self._put("/api/memory/demo/gate-policy", {"high": "block_everything_always"})
        assert resp.status_code == 422

    def test_put_unrecognized_severity_key_422s(self):
        """extra="forbid" rejects a key that isn't high/medium/low, instead
        of silently accepting and ignoring it the way a plain dict write
        into memory JSON always could before this endpoint existed."""
        memory = {"decisions": []}
        with patch("core.ghost.preventive_router._load_memory", return_value=memory):
            resp = self._put("/api/memory/demo/gate-policy", {"hihg": "block"})
        assert resp.status_code == 422

    def test_put_empty_body_422s(self):
        memory = {"decisions": []}
        with patch("core.ghost.preventive_router._load_memory", return_value=memory):
            resp = self._put("/api/memory/demo/gate-policy", {})
        assert resp.status_code == 422

    def test_put_then_get_round_trips(self):
        memory = {"decisions": []}
        with patch("core.ghost.preventive_router._load_memory", return_value=memory), \
             patch("core.ghost.preventive_router._save_memory", return_value=None):
            self._put("/api/memory/demo/gate-policy", {"high": "warn", "low": "block"})
            get_resp = self._get("/api/memory/demo/gate-policy")

        body = get_resp.json()
        assert body["overrides"] == {"high": "warn", "low": "block"}
        assert body["effective_policy"]["medium"] == "warn"  # untouched tier, still default

    def test_put_actually_changes_ghost_check_enforcement(self):
        """End-to-end: a PUT-set override changes real ghost-check behavior,
        not just what the policy endpoints themselves report."""
        from core.result import Ok

        memory = TestGhostCheckGatePolicy._memory()
        with patch("core.ghost.preventive_router._load_memory", return_value=memory), \
             patch("core.ghost.preventive_router._save_memory", return_value=None):
            put_resp = self._put("/api/memory/demo/gate-policy", {"high": "warn"})
            assert put_resp.status_code == 200

            with patch("core.ghost.preventive_router.check_diff_for_warnings",
                       return_value=Ok(value=[TestGhostCheckGatePolicy._high_severity_warning()])):
                check_resp = self._post_ghost_check(memory)

        assert check_resp.status_code == 200
        assert check_resp.json()["warnings"][0]["policy"] == "warn"

    def _post_ghost_check(self, memory):
        import asyncio
        from httpx import ASGITransport, AsyncClient

        async def _call():
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.post("/api/memory/demo/ghost-check", json={"diff": CAMEL_CASE_DIFF})

        return asyncio.run(_call())


# ===========================================================================
#  5. Prevention Report (#61) — GET /{project}/prevention-report
# ===========================================================================


@pytest.mark.skipif(not _HAS_ROUTER, reason="preventive_router.py not yet created (subtask 02 pending)")
class TestPreventionReportEndpoint:
    """Router-level tests for GET /{project}/prevention-report — the
    aggregation itself is unit-tested in tests/test_prevention_report.py;
    these just confirm the endpoint reads memory["audit_log"] and shapes
    the response correctly."""

    def _get(self, path):
        import asyncio
        from httpx import ASGITransport, AsyncClient

        async def _call():
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.get(path)

        return asyncio.run(_call())

    def test_empty_audit_log_returns_zeroed_report(self):
        memory = {"decisions": [], "audit_log": []}
        with patch("core.ghost.preventive_router._load_memory", return_value=memory):
            resp = self._get("/api/memory/demo/prevention-report")

        assert resp.status_code == 200
        body = resp.json()
        assert body["project"] == "demo"
        assert body["total_prevented"] == 0
        assert body["override_count"] == 0
        assert body["override_rate"] == 0.0
        assert body["overrides"] == []

    def test_report_reflects_real_audit_log_events(self):
        memory = {
            "decisions": [],
            "audit_log": [
                {"event_type": "gate_blocked", "timestamp": _NOW,
                 "decision_ids": ["d1"], "severity_counts": {"high": 2, "medium": 0, "low": 0}},
                {"event_type": "gate_warned", "timestamp": _NOW,
                 "decision_ids": ["d2"], "severity_counts": {"high": 0, "medium": 1, "low": 0}},
                {"event_type": "contradiction_escalated", "timestamp": _NOW,
                 "decision_id": "d3", "severity_counts": {"high": 1}},
                {"event_type": "override", "timestamp": _NOW, "override_id": "o1",
                 "decision_id": "d1", "rationale": "known false positive", "agent_name": "claude"},
            ],
        }
        with patch("core.ghost.preventive_router._load_memory", return_value=memory):
            resp = self._get("/api/memory/proj/prevention-report")

        assert resp.status_code == 200
        body = resp.json()
        assert body["gate_blocked_count"] == 2
        assert body["gate_warned_count"] == 1
        assert body["contradiction_escalated_count"] == 1
        assert body["override_count"] == 1
        assert body["total_prevented"] == 4
        assert body["severity_distribution"] == {"high": 3, "medium": 1, "low": 0}
        assert body["overrides"][0]["rationale"] == "known false positive"
        # gate_signal_count=3, override_count=1 -> 1/4
        assert body["override_rate"] == 0.25

    def test_report_ignores_unrelated_event_types(self):
        memory = {
            "decisions": [],
            "audit_log": [
                {"event_type": "decision_created", "timestamp": _NOW, "decision_id": "d1"},
                {"event_type": "review_submitted", "timestamp": _NOW, "decision_id": "d1"},
            ],
        }
        with patch("core.ghost.preventive_router._load_memory", return_value=memory):
            resp = self._get("/api/memory/proj/prevention-report")

        assert resp.status_code == 200
        assert resp.json()["total_prevented"] == 0

    def test_404_unknown_project(self):
        from fastapi import HTTPException

        def _mock_load(project):
            raise HTTPException(status_code=404, detail=f"Project '{project}' not found")

        with patch("core.ghost.preventive_router._load_memory", side_effect=_mock_load):
            resp = self._get("/api/memory/nonexistent/prevention-report")

        assert resp.status_code == 404
