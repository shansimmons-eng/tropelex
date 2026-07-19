"""
Tests for PR Bot — unit tests for analyzer.py, comment_builder.py,
and integration tests for router.py.

Analyzes PR diffs against project decisions and generates formatted
PR comments with decision context and ghost warnings.
Uses pytest, AAA pattern, no shared state, all externals mocked.
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from core.prbot import (
    Err,
    Ok,
    PRBotError,
    PRComment,
    PRCommentRequest,
    PRDecision,
    PRGhostWarning,
    ValidationError,
)
from core.prbot.analyzer import (
    PRAnalysis,
    analyze_pr_diff,
    compute_pr_relevance,
    find_relevant_decisions,
)
from core.prbot.comment_builder import (
    build_pr_comment,
    format_decision,
    format_warning,
    generate_comment_summary,
)


# ---------------------------------------------------------------------------
#  Helpers — realistic mock data
# ---------------------------------------------------------------------------

_NOW = datetime.now(timezone.utc).isoformat()


def _decision(text, did="dec-1", ts=None, context=""):
    """Create a decision dict matching the project memory schema."""
    return {"id": did, "decision": text, "timestamp": ts or _NOW, "context": context}


def _memory(decisions=None):
    """Create a memory dict for the PR bot."""
    return {"decisions": decisions or []}


def _pr_decision(
    did="dec-1",
    text="some decision",
    confidence=0.8,
    relevance=0.5,
    impact=0.0,
    relationship="direct",
):
    """Create a PRDecision dataclass for comment builder tests."""
    return PRDecision(
        decision_id=did,
        decision_text=text,
        confidence=confidence,
        relevance_score=relevance,
        impact_score=impact,
        relationship=relationship,
    )


def _ghost_warning(
    did="dec-1",
    severity="medium",
    keywords=None,
    recommendation="Review this change",
):
    """Create a PRGhostWarning dataclass for comment builder tests."""
    return PRGhostWarning(
        decision_id=did,
        severity=severity,
        matched_keywords=keywords or ["test"],
        recommendation=recommendation,
    )


# Naming decision — keyword "naming" overlaps with naming-related diffs
NAMING_DECISION = _decision(
    "Use snake_case naming convention for all Python module functions",
    did="naming-1",
)

# Diff that matches the naming decision (shares keywords: naming, convention, module, functions)
MATCHING_DIFF = """\
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
#  1. analyzer.py — find_relevant_decisions
# ===========================================================================


class TestFindRelevantDecisions:
    """Tests for find_relevant_decisions — keyword-based decision matching."""

    def test_empty_decisions_returns_empty(self):
        """No decisions in memory returns empty list."""
        # Arrange
        mem = _memory(decisions=[])
        diff = "+def new_function(): pass\n"

        # Act
        result = find_relevant_decisions(mem, diff)

        # Assert
        assert result == []

    def test_empty_diff_and_title_returns_empty(self):
        """Empty diff and empty title returns empty list."""
        # Arrange
        mem = _memory(decisions=[NAMING_DECISION])

        # Act
        result = find_relevant_decisions(mem, "", "")

        # Assert
        assert result == []

    def test_no_keyword_match_returns_empty(self):
        """Diff with no keyword overlap returns empty list."""
        # Arrange
        mem = _memory(decisions=[NAMING_DECISION])

        # Act
        result = find_relevant_decisions(mem, UNRELATED_DIFF)

        # Assert
        assert result == []

    def test_keyword_match_returns_decisions(self):
        """Diff with keyword overlap returns matching decisions."""
        # Arrange
        mem = _memory(decisions=[NAMING_DECISION])

        # Act
        result = find_relevant_decisions(mem, MATCHING_DIFF)

        # Assert
        assert len(result) >= 1
        assert any(d.decision_id == "naming-1" for d in result)

    def test_relevance_score_positive(self):
        """Matched decisions have positive relevance_score."""
        # Arrange
        mem = _memory(decisions=[NAMING_DECISION])

        # Act
        result = find_relevant_decisions(mem, MATCHING_DIFF)

        # Assert
        assert all(d.relevance_score > 0 for d in result)

    def test_sorted_by_relevance_descending(self):
        """Results are sorted by relevance_score descending."""
        # Arrange
        decision2 = _decision(
            "Use naming convention for Python module variables",
            did="naming-2",
        )
        mem = _memory(decisions=[NAMING_DECISION, decision2])

        # Act
        result = find_relevant_decisions(mem, MATCHING_DIFF)

        # Assert
        if len(result) >= 2:
            scores = [d.relevance_score for d in result]
            assert scores == sorted(scores, reverse=True)

    def test_pr_title_contributes_keywords(self):
        """PR title keywords contribute to matching."""
        # Arrange
        mem = _memory(decisions=[NAMING_DECISION])

        # Act
        result = find_relevant_decisions(mem, "", "Refactor naming convention in module")

        # Assert
        assert len(result) >= 1
        assert any(d.decision_id == "naming-1" for d in result)

    def test_no_decisions_key_in_memory(self):
        """Memory dict without 'decisions' key returns empty list."""
        # Arrange
        mem = {}
        diff = "+def new_function(): pass\n"

        # Act
        result = find_relevant_decisions(mem, diff)

        # Assert
        assert result == []

    def test_decision_with_no_extractable_keywords(self):
        """Decision text with only stopwords returns empty list."""
        # Arrange
        short_decision = _decision("the a is are", did="stop-1")
        mem = _memory(decisions=[short_decision])

        # Act
        result = find_relevant_decisions(mem, MATCHING_DIFF)

        # Assert
        assert result == []


# ===========================================================================
#  2. analyzer.py — compute_pr_relevance
# ===========================================================================


class TestComputePRRelevance:
    """Tests for compute_pr_relevance — weighted relevance scoring."""

    def test_empty_inputs_returns_zero(self):
        """No warnings and no decisions returns 0.0."""
        # Arrange / Act
        result = compute_pr_relevance([], [])

        # Assert
        assert result == 0.0

    def test_high_severity_ghost_warning(self):
        """High severity ghost warning contributes up to 0.5."""
        # Arrange
        warnings = [_ghost_warning(severity="high")]

        # Act
        result = compute_pr_relevance(warnings, [])

        # Assert
        assert result > 0.0
        assert result <= 0.5

    def test_decision_relevance_contribution(self):
        """Decision relevance contributes up to 0.5."""
        # Arrange
        decisions = [_pr_decision(relevance=0.8)]

        # Act
        result = compute_pr_relevance([], decisions)

        # Assert
        assert result > 0.0
        assert result <= 0.5

    def test_combined_score_capped_at_one(self):
        """Combined ghost + decision score is capped at 1.0."""
        # Arrange
        warnings = [_ghost_warning(severity="high")]
        decisions = [_pr_decision(relevance=1.0)]

        # Act
        result = compute_pr_relevance(warnings, decisions)

        # Assert
        assert result <= 1.0

    def test_low_severity_ghost(self):
        """Low severity ghost warning contributes less than high."""
        # Arrange
        high_warnings = [_ghost_warning(severity="high")]
        low_warnings = [_ghost_warning(severity="low")]

        # Act
        high_score = compute_pr_relevance(high_warnings, [])
        low_score = compute_pr_relevance(low_warnings, [])

        # Assert
        assert high_score > low_score

    def test_multiple_ghost_warnings_averaged(self):
        """Multiple ghost warnings are averaged, not summed."""
        # Arrange
        warnings = [
            _ghost_warning(severity="high"),
            _ghost_warning(severity="low"),
        ]

        # Act
        result = compute_pr_relevance(warnings, [])

        # Assert
        # Average of high(1.0) and low(0.3) = 0.65, * 0.5 = 0.325
        assert 0.0 < result < 0.5

    def test_unknown_severity_defaults_low(self):
        """Unknown severity tier defaults to low weight (0.3)."""
        # Arrange
        warnings = [_ghost_warning(severity="unknown_tier")]

        # Act
        result = compute_pr_relevance(warnings, [])

        # Assert
        # 0.3 / 1 * 0.5 = 0.15
        assert abs(result - 0.15) < 0.01


# ===========================================================================
#  3. analyzer.py — analyze_pr_diff
# ===========================================================================


class TestAnalyzePRDiff:
    """Tests for analyze_pr_diff — the main analysis entry point."""

    def test_empty_diff_returns_err(self):
        """Empty diff with no title returns Err with VALIDATION_ERROR."""
        # Arrange
        mem = _memory(decisions=[NAMING_DECISION])

        # Act
        result = analyze_pr_diff(mem, "", "", "")

        # Assert
        assert isinstance(result, Err)
        assert result.code == "VALIDATION_ERROR"

    def test_empty_decisions_returns_ok_empty(self):
        """No decisions returns Ok with empty warnings and decisions."""
        # Arrange
        mem = _memory(decisions=[])
        diff = "+def new_function(): pass\n"

        # Act
        result = analyze_pr_diff(mem, diff)

        # Assert
        assert isinstance(result, Ok)
        assert result.value.ghost_warnings == []
        assert result.value.relevant_decisions == []

    def test_matching_diff_returns_analysis(self):
        """Diff matching decisions returns PRAnalysis with results."""
        # Arrange
        mem = _memory(decisions=[NAMING_DECISION])

        # Act
        result = analyze_pr_diff(mem, MATCHING_DIFF, "Refactor naming")

        # Assert
        assert isinstance(result, Ok)
        analysis = result.value
        assert isinstance(analysis, PRAnalysis)
        assert len(analysis.relevant_decisions) >= 1
        assert analysis.relevance_score >= 0.0

    def test_unrelated_diff_returns_empty_analysis(self):
        """Diff with no keyword overlap returns empty analysis."""
        # Arrange
        mem = _memory(decisions=[NAMING_DECISION])

        # Act
        result = analyze_pr_diff(mem, UNRELATED_DIFF, "CSS changes")

        # Assert
        assert isinstance(result, Ok)
        assert result.value.relevant_decisions == []

    def test_ghost_warnings_populated(self):
        """Ghost warnings are populated when diff contradicts decisions."""
        # Arrange
        mem = _memory(decisions=[NAMING_DECISION])

        # Act
        result = analyze_pr_diff(mem, MATCHING_DIFF)

        # Assert
        assert isinstance(result, Ok)
        # Ghost warnings come from check_diff_for_warnings
        assert isinstance(result.value.ghost_warnings, list)

    def test_pr_title_and_body_combined(self):
        """PR title and body are combined for keyword extraction."""
        # Arrange
        mem = _memory(decisions=[NAMING_DECISION])

        # Act
        result = analyze_pr_diff(
            mem,
            "+pass\n",
            "Update naming",
            "Refactor module functions to use convention",
        )

        # Assert
        assert isinstance(result, Ok)

    def test_relevance_score_is_float(self):
        """Relevance score is always a float between 0 and 1."""
        # Arrange
        mem = _memory(decisions=[NAMING_DECISION])

        # Act
        result = analyze_pr_diff(mem, MATCHING_DIFF, "Refactor naming")

        # Assert
        assert isinstance(result, Ok)
        assert isinstance(result.value.relevance_score, float)
        assert 0.0 <= result.value.relevance_score <= 1.0

    def test_only_title_no_diff_is_valid(self):
        """A PR with only a title (no diff) is valid input."""
        # Arrange
        mem = _memory(decisions=[NAMING_DECISION])

        # Act
        result = analyze_pr_diff(mem, "", "Use naming convention in module")

        # Assert
        assert isinstance(result, Ok)


# ===========================================================================
#  4. comment_builder.py — format_decision
# ===========================================================================


class TestFormatDecision:
    """Tests for format_decision — single decision markdown formatting."""

    def test_contains_decision_id(self):
        """Formatted output contains the decision ID."""
        # Arrange
        d = _pr_decision(did="my-dec-42")

        # Act
        result = format_decision(d)

        # Assert
        assert "my-dec-42" in result

    def test_contains_decision_text(self):
        """Formatted output contains the decision text."""
        # Arrange
        d = _pr_decision(text="Use PostgreSQL for all databases")

        # Act
        result = format_decision(d)

        # Assert
        assert "Use PostgreSQL for all databases" in result

    def test_contains_confidence(self):
        """Formatted output contains the confidence value."""
        # Arrange
        d = _pr_decision(confidence=0.95)

        # Act
        result = format_decision(d)

        # Assert
        assert "0.95" in result

    def test_high_impact_label(self):
        """Impact score >= 0.7 shows 'high' label."""
        # Arrange
        d = _pr_decision(impact=0.8)

        # Act
        result = format_decision(d)

        # Assert
        assert "high" in result

    def test_medium_impact_label(self):
        """Impact score >= 0.4 and < 0.7 shows 'medium' label."""
        # Arrange
        d = _pr_decision(impact=0.5)

        # Act
        result = format_decision(d)

        # Assert
        assert "medium" in result

    def test_low_impact_label(self):
        """Impact score < 0.4 shows 'low' label."""
        # Arrange
        d = _pr_decision(impact=0.1)

        # Act
        result = format_decision(d)

        # Assert
        assert "low" in result

    def test_contains_relationship(self):
        """Formatted output contains the relationship type."""
        # Arrange
        d = _pr_decision(relationship="ancestor")

        # Act
        result = format_decision(d)

        # Assert
        assert "ancestor" in result

    def test_starts_with_bullet(self):
        """Formatted output starts with a bullet point."""
        # Arrange
        d = _pr_decision()

        # Act
        result = format_decision(d)

        # Assert
        assert result.startswith("•")


# ===========================================================================
#  5. comment_builder.py — format_warning
# ===========================================================================


class TestFormatWarning:
    """Tests for format_warning — single ghost warning markdown formatting."""

    def test_contains_severity(self):
        """Formatted output contains the severity label."""
        # Arrange
        w = _ghost_warning(severity="high")

        # Act
        result = format_warning(w)

        # Assert
        assert "high" in result

    def test_contains_recommendation(self):
        """Formatted output contains the recommendation text."""
        # Arrange
        w = _ghost_warning(recommendation="Consider updating the decision")

        # Act
        result = format_warning(w)

        # Assert
        assert "Consider updating the decision" in result

    def test_starts_with_warning_emoji(self):
        """Formatted output starts with warning emoji."""
        # Arrange
        w = _ghost_warning()

        # Act
        result = format_warning(w)

        # Assert
        assert result.startswith("⚠️")

    def test_contains_severity_brackets(self):
        """Formatted output wraps severity in brackets."""
        # Arrange
        w = _ghost_warning(severity="medium")

        # Act
        result = format_warning(w)

        # Assert
        assert "[medium]" in result


# ===========================================================================
#  6. comment_builder.py — generate_comment_summary
# ===========================================================================


class TestGenerateCommentSummary:
    """Tests for generate_comment_summary — one-line summary text."""

    def test_no_decisions_no_warnings(self):
        """Empty inputs produces fallback summary."""
        # Arrange / Act
        result = generate_comment_summary([], [])

        # Assert
        assert "No relevant decisions" in result

    def test_single_decision(self):
        """Single decision uses singular 'decision'."""
        # Arrange
        decisions = [_pr_decision()]

        # Act
        result = generate_comment_summary(decisions, [])

        # Assert
        assert "1 relevant decision found" in result

    def test_multiple_decisions(self):
        """Multiple decisions uses plural 'decisions'."""
        # Arrange
        decisions = [_pr_decision(), _pr_decision(did="dec-2")]

        # Act
        result = generate_comment_summary(decisions, [])

        # Assert
        assert "2 relevant decisions found" in result

    def test_single_warning(self):
        """Single warning uses singular 'warning'."""
        # Arrange
        warnings = [_ghost_warning()]

        # Act
        result = generate_comment_summary([], warnings)

        # Assert
        assert "1 ghost warning detected" in result

    def test_multiple_warnings(self):
        """Multiple warnings uses plural 'warnings'."""
        # Arrange
        warnings = [_ghost_warning(), _ghost_warning(did="dec-2")]

        # Act
        result = generate_comment_summary([], warnings)

        # Assert
        assert "2 ghost warnings detected" in result

    def test_both_decisions_and_warnings(self):
        """Both decisions and warnings produces combined summary."""
        # Arrange
        decisions = [_pr_decision()]
        warnings = [_ghost_warning()]

        # Act
        result = generate_comment_summary(decisions, warnings)

        # Assert
        assert "decision" in result
        assert "warning" in result


# ===========================================================================
#  7. comment_builder.py — build_pr_comment
# ===========================================================================


class TestBuildPRComment:
    """Tests for build_pr_comment — full markdown comment assembly."""

    def test_returns_ok(self):
        """build_pr_comment always returns Ok(PRComment)."""
        # Arrange
        analysis = PRAnalysis(
            ghost_warnings=[],
            relevant_decisions=[],
            relevance_score=0.0,
        )

        # Act
        result = build_pr_comment(analysis)

        # Assert
        assert isinstance(result, Ok)
        assert isinstance(result.value, PRComment)

    def test_contains_header(self):
        """Comment body contains the Tropelex header."""
        # Arrange
        analysis = PRAnalysis([], [], 0.0)

        # Act
        result = build_pr_comment(analysis)

        # Assert
        assert "Tropelex" in result.value.body
        assert "Decision Context" in result.value.body

    def test_contains_project_name(self):
        """Comment body includes project name when provided."""
        # Arrange
        analysis = PRAnalysis([], [], 0.0)

        # Act
        result = build_pr_comment(analysis, project="my-project")

        # Assert
        assert "my-project" in result.value.body

    def test_with_decisions_section(self):
        """Comment body includes Relevant Decisions section."""
        # Arrange
        decisions = [_pr_decision(text="Use PostgreSQL")]
        analysis = PRAnalysis([], decisions, 0.5)

        # Act
        result = build_pr_comment(analysis)

        # Assert
        assert "Relevant Decisions" in result.value.body
        assert "PostgreSQL" in result.value.body

    def test_with_warnings_section(self):
        """Comment body includes Ghost Warnings section."""
        # Arrange
        warnings = [_ghost_warning(recommendation="Review this")]
        analysis = PRAnalysis(warnings, [], 0.3)

        # Act
        result = build_pr_comment(analysis)

        # Assert
        assert "Ghost Warnings" in result.value.body
        assert "Review this" in result.value.body

    def test_with_both_sections(self):
        """Comment body includes both sections when both present."""
        # Arrange
        decisions = [_pr_decision()]
        warnings = [_ghost_warning()]
        analysis = PRAnalysis(warnings, decisions, 0.7)

        # Act
        result = build_pr_comment(analysis)

        # Assert
        assert "Relevant Decisions" in result.value.body
        assert "Ghost Warnings" in result.value.body

    def test_no_sections_when_empty(self):
        """Comment body omits sections when no decisions or warnings."""
        # Arrange
        analysis = PRAnalysis([], [], 0.0)

        # Act
        result = build_pr_comment(analysis)

        # Assert
        assert "Relevant Decisions" not in result.value.body
        assert "Ghost Warnings" not in result.value.body

    def test_decision_count(self):
        """PRComment.decision_count matches number of decisions."""
        # Arrange
        decisions = [_pr_decision(), _pr_decision(did="d2")]
        analysis = PRAnalysis([], decisions, 0.5)

        # Act
        result = build_pr_comment(analysis)

        # Assert
        assert result.value.decision_count == 2

    def test_warning_count(self):
        """PRComment.warning_count matches number of warnings."""
        # Arrange
        warnings = [_ghost_warning(), _ghost_warning(did="d2")]
        analysis = PRAnalysis(warnings, [], 0.3)

        # Act
        result = build_pr_comment(analysis)

        # Assert
        assert result.value.warning_count == 2

    def test_relevance_score_preserved(self):
        """PRComment.relevance_score matches analysis input."""
        # Arrange
        analysis = PRAnalysis([], [], 0.42)

        # Act
        result = build_pr_comment(analysis)

        # Assert
        assert result.value.relevance_score == 0.42

    def test_summary_line_present(self):
        """Comment body contains the summary line with relevance score."""
        # Arrange
        analysis = PRAnalysis([], [], 0.25)

        # Act
        result = build_pr_comment(analysis)

        # Assert
        assert "relevance: 0.25" in result.value.body


# ===========================================================================
#  8. PRBotError / ValidationError
# ===========================================================================


class TestExceptions:
    """Tests for PRBotError and ValidationError exception classes."""

    def test_prbot_error_has_code(self):
        """PRBotError stores code and details."""
        # Arrange / Act
        err = PRBotError("boom", code="TEST_ERR", details={"x": 1})

        # Assert
        assert str(err) == "boom"
        assert err.code == "TEST_ERR"
        assert err.details == {"x": 1}

    def test_prbot_error_default_code(self):
        """PRBotError defaults code to UNKNOWN."""
        # Arrange / Act
        err = PRBotError("oops")

        # Assert
        assert err.code == "UNKNOWN"
        assert err.details == {}

    def test_validation_error_has_code(self):
        """ValidationError stores code and details."""
        # Arrange / Act
        err = ValidationError("bad input", code="VALIDATION_ERROR", details={"field": "diff"})

        # Assert
        assert str(err) == "bad input"
        assert err.code == "VALIDATION_ERROR"
        assert err.details == {"field": "diff"}

    def test_validation_error_default_code(self):
        """ValidationError defaults code to VALIDATION_ERROR."""
        # Arrange / Act
        err = ValidationError("missing field")

        # Assert
        assert err.code == "VALIDATION_ERROR"


# ===========================================================================
#  9. Router integration tests (FastAPI + httpx)
# ===========================================================================


try:
    from core.prbot.router import prbot_router, _serialize_comment
    _HAS_ROUTER = True
except ImportError:
    _HAS_ROUTER = False


def _app():
    """Create a FastAPI app with the prbot router included."""
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(prbot_router)
    return app


@pytest.mark.skipif(not _HAS_ROUTER, reason="prbot router not available")
class TestPRBotRouter:
    """Integration tests for POST /api/memory/{project}/pr-comment."""

    def test_router_pr_comment_success(self):
        """POST with valid diff returns 200 with PR comment body."""
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
            from httpx import ASGITransport, AsyncClient
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.post(
                    "/api/memory/test-project/pr-comment",
                    json={"diff": diff, "pr_title": "Refactor naming"},
                )

        with patch("core.prbot.router._require_project_exists"):
            with patch("core.prbot.router._load_memory", return_value=mock_memory):
                resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 200
        body = resp.json()
        assert "body" in body
        assert "Tropelex" in body["body"]
        assert "relevance_score" in body
        assert "decision_count" in body
        assert "warning_count" in body

    def test_router_pr_comment_empty_diff(self):
        """POST with empty diff string returns 422 validation error."""
        # Arrange / Act
        async def _call():
            from httpx import ASGITransport, AsyncClient
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.post(
                    "/api/memory/test-project/pr-comment",
                    json={"diff": ""},
                )

        resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 422

    def test_router_pr_comment_missing_project(self):
        """POST to nonexistent project returns 404."""
        # Arrange
        from fastapi import HTTPException

        async def _call():
            from httpx import ASGITransport, AsyncClient
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.post(
                    "/api/memory/nonexistent/pr-comment",
                    json={"diff": "+some code\n"},
                )

        with patch(
            "core.prbot.router._require_project_exists",
            side_effect=HTTPException(status_code=404, detail="Project 'nonexistent' not found"),
        ):
            resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 404
        body = resp.json()
        assert "not found" in body["detail"].lower()

    def test_router_preview_success(self):
        """POST preview returns markdown and relevance score."""
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
            from httpx import ASGITransport, AsyncClient
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.post(
                    "/api/memory/test-project/pr-comment/preview",
                    json={"diff": diff, "pr_title": "Refactor naming"},
                )

        with patch("core.prbot.router._require_project_exists"):
            with patch("core.prbot.router._load_memory", return_value=mock_memory):
                resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 200
        body = resp.json()
        assert "markdown" in body
        assert "Tropelex" in body["markdown"]
        assert "relevance_score" in body
        assert isinstance(body["relevance_score"], float)

    def test_router_preview_empty_diff(self):
        """POST preview with empty diff returns 422."""
        # Arrange / Act
        async def _call():
            from httpx import ASGITransport, AsyncClient
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.post(
                    "/api/memory/test-project/pr-comment/preview",
                    json={"diff": ""},
                )

        resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 422

    def test_router_preview_missing_project(self):
        """POST preview to nonexistent project returns 404."""
        # Arrange
        from fastapi import HTTPException

        async def _call():
            from httpx import ASGITransport, AsyncClient
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.post(
                    "/api/memory/nonexistent/pr-comment/preview",
                    json={"diff": "+some code\n"},
                )

        with patch(
            "core.prbot.router._require_project_exists",
            side_effect=HTTPException(status_code=404, detail="Project 'nonexistent' not found"),
        ):
            resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 404

    def test_router_memory_load_error(self):
        """POST when memory load fails returns 500."""
        # Arrange
        async def _call():
            from httpx import ASGITransport, AsyncClient
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.post(
                    "/api/memory/test-project/pr-comment",
                    json={"diff": "+some code\n"},
                )

        with patch("core.prbot.router._require_project_exists"):
            with patch(
                "core.prbot.router._load_memory",
                side_effect=Exception("disk failure"),
            ):
                resp = asyncio.run(_call())

        # Assert — FastAPI returns 500 for unhandled exceptions
        assert resp.status_code == 500


# ===========================================================================
#  10. _serialize_comment helper
# ===========================================================================


@pytest.mark.skipif(not _HAS_ROUTER, reason="prbot router not available")
class TestSerializeComment:
    """Tests for _serialize_comment — dataclass to dict conversion."""

    def test_serialize_empty_comment(self):
        """Empty PRComment serializes to dict with zero counts."""
        # Arrange
        comment = PRComment(
            body="test",
            decisions_mentioned=[],
            ghost_warnings=[],
            relevance_score=0.0,
            decision_count=0,
            warning_count=0,
        )

        # Act
        result = _serialize_comment(comment)

        # Assert
        assert result["body"] == "test"
        assert result["decisions_mentioned"] == []
        assert result["ghost_warnings"] == []
        assert result["relevance_score"] == 0.0
        assert result["decision_count"] == 0
        assert result["warning_count"] == 0

    def test_serialize_with_decisions(self):
        """PRComment with decisions serializes decision fields."""
        # Arrange
        d = _pr_decision(did="d1", text="Use PostgreSQL", confidence=0.9, relevance=0.7)
        comment = PRComment(
            body="test",
            decisions_mentioned=[d],
            ghost_warnings=[],
            relevance_score=0.5,
            decision_count=1,
            warning_count=0,
        )

        # Act
        result = _serialize_comment(comment)

        # Assert
        assert len(result["decisions_mentioned"]) == 1
        assert result["decisions_mentioned"][0]["decision_id"] == "d1"
        assert result["decisions_mentioned"][0]["confidence"] == 0.9

    def test_serialize_with_warnings(self):
        """PRComment with warnings serializes warning fields."""
        # Arrange
        w = _ghost_warning(did="d1", severity="high", keywords=["test", "warn"])
        comment = PRComment(
            body="test",
            decisions_mentioned=[],
            ghost_warnings=[w],
            relevance_score=0.3,
            decision_count=0,
            warning_count=1,
        )

        # Act
        result = _serialize_comment(comment)

        # Assert
        assert len(result["ghost_warnings"]) == 1
        assert result["ghost_warnings"][0]["severity"] == "high"
        assert result["ghost_warnings"][0]["matched_keywords"] == ["test", "warn"]


# ===========================================================================
#  11. PR dataclass tests
# ===========================================================================


class TestDataclasses:
    """Tests for PR dataclass types — frozen, field access."""

    def test_pr_decision_frozen(self):
        """PRDecision is frozen (immutable)."""
        # Arrange
        d = _pr_decision()

        # Act / Assert
        with pytest.raises(AttributeError):
            d.decision_id = "changed"  # type: ignore[misc]

    def test_pr_ghost_warning_frozen(self):
        """PRGhostWarning is frozen (immutable)."""
        # Arrange
        w = _ghost_warning()

        # Act / Assert
        with pytest.raises(AttributeError):
            w.severity = "changed"  # type: ignore[misc]

    def test_pr_comment_frozen(self):
        """PRComment is frozen (immutable)."""
        # Arrange
        c = PRComment(
            body="test",
            decisions_mentioned=[],
            ghost_warnings=[],
            relevance_score=0.0,
            decision_count=0,
            warning_count=0,
        )

        # Act / Assert
        with pytest.raises(AttributeError):
            c.body = "changed"  # type: ignore[misc]

    def test_pr_comment_request_defaults(self):
        """PRCommentRequest has empty defaults for title and body."""
        # Arrange / Act
        req = PRCommentRequest(diff="some diff")

        # Assert
        assert req.diff == "some diff"
        assert req.pr_title == ""
        assert req.pr_body == ""

    def test_ok_err_types(self):
        """Ok and Err are frozen dataclasses with correct fields."""
        # Arrange / Act
        ok = Ok(value="test")
        err = Err(error="boom", code="ERR")

        # Assert
        assert ok.value == "test"
        assert err.error == "boom"
        assert err.code == "ERR"
        with pytest.raises(AttributeError):
            ok.value = "changed"  # type: ignore[misc]
