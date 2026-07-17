"""
Tests for Ghost Decisions — pattern_matcher, detector, and router.

Detects when code contradicts documented architectural decisions.
Uses pytest, AAA pattern, no shared state, all externals mocked.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from core.ghost.pattern_matcher import (
    MatchResult,
    extract_decision_topics,
    extract_keywords,
    match_decision_to_diff,
    parse_diff_hunks,
    score_ghost_severity,
)
from core.ghost.detector import (
    GhostDecision,
    GhostReport,
    _aggregate_severity_distribution,
    _classify_severity,
    _generate_ghost_recommendation,
    _generate_report_recommendations,
    detect_ghost_decisions,
)
from core.ghost.router import ghost_router


# ---------------------------------------------------------------------------
#  Helpers — realistic mock data
# ---------------------------------------------------------------------------

def _decision(text, did="dec-1", ts="2026-07-01T00:00:00Z", context=""):
    """Create a decision dict matching the project memory schema."""
    return {"id": did, "decision": text, "timestamp": ts, "context": context}


def _memory(decisions=None):
    """Create a memory dict for the detector."""
    return {"decisions": decisions or []}


def _diff_entry(file, diff_text):
    """Create a diff_data entry for the detector."""
    return {"file": file, "diff_text": diff_text}


# Realistic diff: someone added camelCase methods with comments mentioning
# the naming convention — creates natural keyword overlap with decisions
# about naming conventions.
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
+    # Get user settings using new naming convention
+    return self.settings
"""

# Realistic diff: someone deleted snake_case code
DELETE_SNAKE_DIFF = """\
--- a/src/handlers.py
+++ b/src/handlers.py
@@ -5,8 +5,6 @@
 def handle_request():
     pass
 
-def format_response():
-    return {}
 
 def process_input():
     pass
"""


# ===========================================================================
#  1. Pattern Matcher Tests
# ===========================================================================


class TestExtractKeywords:
    def test_extract_keywords_removes_stopwords(self):
        """Stopwords like 'the', 'is', 'are' are filtered out."""
        # Arrange
        text = "The quick brown fox is a very good example"

        # Act
        keywords = extract_keywords(text)

        # Assert
        assert "the" not in keywords
        assert "is" not in keywords
        assert "are" not in keywords
        assert "very" in keywords  # "very" is NOT a stopword — it's kept

    def test_extract_keywords_returns_meaningful_words(self):
        """Useful domain words like 'snake_case', 'fastapi' are kept."""
        # Arrange
        text = "Use snake_case naming convention for the fastapi backend"

        # Act
        keywords = extract_keywords(text)

        # Assert
        assert "snake_case" in keywords
        assert "fastapi" in keywords
        assert "backend" in keywords
        assert "naming" in keywords
        assert "convention" in keywords


class TestParseDiffHunks:
    def test_parse_diff_hunks_parses_additions(self):
        """Lines starting with '+' are parsed as additions."""
        # Arrange
        diff = "+def getUserSettings(self):\n+    return self.settings"

        # Act
        hunks = parse_diff_hunks(diff)

        # Assert
        assert len(hunks) == 2
        assert all(h["is_addition"] for h in hunks)
        assert not any(h["is_deletion"] for h in hunks)
        assert hunks[0]["content"] == "def getUserSettings(self):"
        assert hunks[1]["content"] == "    return self.settings"

    def test_parse_diff_hunks_parses_deletions(self):
        """Lines starting with '-' (not '---') are parsed as deletions."""
        # Arrange
        diff = "-def old_function():\n-    pass"

        # Act
        hunks = parse_diff_hunks(diff)

        # Assert
        assert len(hunks) == 2
        assert all(h["is_deletion"] for h in hunks)
        assert not any(h["is_addition"] for h in hunks)
        assert hunks[0]["content"] == "def old_function():"

    def test_parse_diff_hunks_skips_file_headers(self):
        """'--- a/file' and '+++ b/file' header lines are skipped."""
        # Arrange
        diff = "--- a/src/utils.py\n+++ b/src/utils.py\n+new_line()"

        # Act
        hunks = parse_diff_hunks(diff)

        # Assert
        assert len(hunks) == 1
        assert hunks[0]["is_addition"] is True
        assert hunks[0]["content"] == "new_line()"

    def test_parse_diff_hunks_extracts_line_numbers(self):
        """Hunk headers set the starting line number for subsequent lines."""
        # Arrange
        diff = "@@ -10,4 +10,8 @@\n+added_line()"

        # Act
        hunks = parse_diff_hunks(diff)

        # Assert
        assert len(hunks) == 1
        assert hunks[0]["line_number"] == 10

    def test_parse_diff_full_diff(self):
        """Full realistic diff is parsed correctly."""
        # Arrange / Act
        hunks = parse_diff_hunks(CAMEL_CASE_DIFF)

        # Assert
        additions = [h for h in hunks if h["is_addition"]]
        assert len(additions) >= 3
        # The file header lines should be skipped
        assert not any("+++" in h["content"] or "---" in h["content"] for h in hunks)


class TestMatchDecisionToDiff:
    def test_match_decision_to_diff_finds_matches(self):
        """Decision with overlapping keywords against a diff finds matches."""
        # Arrange
        # Decision and hunk share keywords: "naming", "convention", "module", "functions"
        decision = "Use snake_case naming convention for all Python module functions"
        hunks = [
            {
                "file": "src/utils.py",
                "line_number": 12,
                "content": "# Apply naming convention to module functions",
                "is_addition": True,
                "is_deletion": False,
            },
        ]

        # Act
        matches = match_decision_to_diff(decision, hunks)

        # Assert
        assert len(matches) >= 1
        assert matches[0].diff_file == "src/utils.py"
        assert matches[0].diff_line == 12
        assert matches[0].overlap_score > 0.2
        assert len(matches[0].matched_keywords) > 0

    def test_match_decision_to_diff_no_match_for_unrelated(self):
        """Decision about logging doesn't match a diff about UI styling."""
        # Arrange
        decision = "Use structured logging with JSON format for all services"
        hunks = [
            {
                "file": "src/styles.css",
                "line_number": 5,
                "content": "button { color: red; }",
                "is_addition": True,
                "is_deletion": False,
            },
        ]

        # Act
        matches = match_decision_to_diff(decision, hunks)

        # Assert
        assert len(matches) == 0

    def test_match_decision_to_diff_returns_match_result(self):
        """MatchResult contains all expected fields."""
        # Arrange
        decision = "Use snake_case naming convention for Python modules"
        hunks = [
            {
                "file": "src/api.py",
                "line_number": 3,
                "content": "# naming convention: apply to Python modules",
                "is_addition": True,
                "is_deletion": False,
            },
        ]

        # Act
        matches = match_decision_to_diff(decision, hunks)

        # Assert
        assert len(matches) >= 1
        m = matches[0]
        assert isinstance(m, MatchResult)
        assert m.decision_text == decision
        assert m.diff_file == "src/api.py"
        assert isinstance(m.matched_keywords, list)
        assert m.overlap_score > 0
        assert m.is_addition is True


class TestScoreGhostSeverity:
    def test_score_ghost_severity_high_for_additions(self):
        """Additions get a higher severity multiplier (1.0)."""
        # Arrange
        match = MatchResult(
            decision_text="Use snake_case",
            diff_file="src/utils.py",
            diff_line=10,
            matched_keywords=["snake_case"],
            overlap_score=0.8,
            hunk_snippet="def getUserSettings():",
            is_addition=True,
        )

        # Act
        severity = score_ghost_severity(match, decision_confidence=0.9)

        # Assert
        # overlap(0.8) * confidence(0.9) * multiplier(1.0) = 0.72
        assert severity == pytest.approx(0.72, abs=0.01)
        assert severity > 0.6  # Would be classified as "high"

    def test_score_ghost_severity_low_for_deletions(self):
        """Deletions get a lower severity multiplier (0.5)."""
        # Arrange
        match_addition = MatchResult(
            decision_text="Use snake_case",
            diff_file="src/utils.py",
            diff_line=10,
            matched_keywords=["snake_case"],
            overlap_score=0.8,
            hunk_snippet="def getUserSettings():",
            is_addition=True,
        )
        match_deletion = MatchResult(
            decision_text="Use snake_case",
            diff_file="src/utils.py",
            diff_line=10,
            matched_keywords=["snake_case"],
            overlap_score=0.8,
            hunk_snippet="def old_function():",
            is_addition=False,
        )

        # Act
        severity_add = score_ghost_severity(match_addition, 0.9)
        severity_del = score_ghost_severity(match_deletion, 0.9)

        # Assert
        # Addition: 0.8 * 0.9 * 1.0 = 0.72
        # Deletion: 0.8 * 0.9 * 0.5 = 0.36
        assert severity_add == pytest.approx(0.72, abs=0.01)
        assert severity_del == pytest.approx(0.36, abs=0.01)
        assert severity_add > severity_del

    def test_score_ghost_severity_clamps_confidence(self):
        """Confidence outside [0,1] is clamped before scoring."""
        # Arrange
        match = MatchResult(
            decision_text="test",
            diff_file="test.py",
            diff_line=1,
            matched_keywords=["test"],
            overlap_score=0.5,
            hunk_snippet="test",
            is_addition=True,
        )

        # Act
        severity_high = score_ghost_severity(match, 2.0)
        severity_neg = score_ghost_severity(match, -1.0)

        # Assert — confidence clamped to 1.0 and 0.0
        assert severity_high == pytest.approx(0.5, abs=0.01)
        assert severity_neg == 0.0


class TestExtractDecisionTopics:
    def test_extract_decision_topics_detects_naming_conventions(self):
        """snake_case and camelCase patterns are detected in decision text."""
        # Arrange
        decision = "Use snake_case for all function names, not camelCase"

        # Act
        topics = extract_decision_topics(decision)

        # Assert
        assert "naming:snake_case" in topics
        assert "naming:camelCase" in topics

    def test_extract_decision_topics_detects_pascal_case(self):
        """PascalCase pattern is detected."""
        # Arrange
        decision = "Use PascalCase for class names like MyClass"

        # Act
        topics = extract_decision_topics(decision)

        # Assert
        assert "naming:PascalCase" in topics

    def test_extract_decision_topics_detects_error_handling(self):
        """Error handling patterns like try/except and raise are detected."""
        # Arrange
        decision = "Always use try/except blocks and raise specific exceptions"

        # Act
        topics = extract_decision_topics(decision)

        # Assert
        assert "error_handling:try_except" in topics
        assert "error_handling:raise" in topics

    def test_extract_decision_topics_empty_text(self):
        """Empty text returns no topics."""
        # Arrange / Act
        topics = extract_decision_topics("")

        # Assert
        assert topics == set()


# ===========================================================================
#  2. Detector Tests
# ===========================================================================


class TestClassifySeverity:
    def test_high_threshold(self):
        """Severity > 0.6 is classified as 'high'."""
        assert _classify_severity(0.7) == "high"
        assert _classify_severity(1.0) == "high"

    def test_medium_threshold(self):
        """Severity >= 0.3 and <= 0.6 is classified as 'medium'."""
        assert _classify_severity(0.3) == "medium"
        assert _classify_severity(0.5) == "medium"
        assert _classify_severity(0.6) == "medium"

    def test_low_threshold(self):
        """Severity < 0.3 is classified as 'low'."""
        assert _classify_severity(0.0) == "low"
        assert _classify_severity(0.15) == "low"
        assert _classify_severity(0.29) == "low"


class TestGenerateGhostRecommendation:
    def test_high_severity(self):
        rec = _generate_ghost_recommendation(0.8)
        assert "reverting" in rec.lower() or "updating" in rec.lower() or "review" in rec.lower()

    def test_medium_severity(self):
        rec = _generate_ghost_recommendation(0.4)
        assert "review" in rec.lower() or "intentional" in rec.lower()

    def test_low_severity(self):
        rec = _generate_ghost_recommendation(0.1)
        assert "minor" in rec.lower() or "monitor" in rec.lower() or "drift" in rec.lower()


class TestAggregateSeverityDistribution:
    def test_empty_ghosts(self):
        """Empty ghost list returns all-zero distribution."""
        # Arrange / Act
        dist = _aggregate_severity_distribution([])

        # Assert
        assert dist == {"high": 0, "medium": 0, "low": 0}

    def test_mixed_severities(self):
        """Correctly counts high, medium, and low ghosts."""
        # Arrange
        ghosts = [
            GhostDecision(
                decision_id="d1", decision_text="a", severity=0.8,
                evidence=[], confidence_score=0.9, confidence_tier="high",
                recommendation="",
            ),
            GhostDecision(
                decision_id="d2", decision_text="b", severity=0.4,
                evidence=[], confidence_score=0.6, confidence_tier="medium",
                recommendation="",
            ),
            GhostDecision(
                decision_id="d3", decision_text="c", severity=0.1,
                evidence=[], confidence_score=0.3, confidence_tier="low",
                recommendation="",
            ),
        ]

        # Act
        dist = _aggregate_severity_distribution(ghosts)

        # Assert
        assert dist == {"high": 1, "medium": 1, "low": 1}


class TestGenerateReportRecommendations:
    def test_empty_ghosts(self):
        """No ghosts → no recommendations."""
        # Arrange / Act
        recs = _generate_report_recommendations([])

        # Assert
        assert recs == []

    def test_high_severity_recommendation(self):
        """High-severity ghosts produce an urgent recommendation."""
        # Arrange
        ghosts = [
            GhostDecision(
                decision_id="d1", decision_text="a", severity=0.9,
                evidence=[], confidence_score=0.9, confidence_tier="high",
                recommendation="",
            ),
        ]

        # Act
        recs = _generate_report_recommendations(ghosts)

        # Assert
        assert any("high" in r.lower() for r in recs)
        assert any("immediately" in r.lower() for r in recs)


class TestDetectGhostDecisions:
    def test_detect_ghost_decisions_empty_memory(self):
        """Empty memory returns empty report with zeroed counters."""
        # Arrange
        mem = _memory()
        diffs = [_diff_entry("src/utils.py", CAMEL_CASE_DIFF)]

        # Act
        report = detect_ghost_decisions(mem, diffs)

        # Assert
        assert isinstance(report, GhostReport)
        assert report.ghosts == []
        assert report.total_decisions_checked == 0
        assert report.total_diffs_checked == 1
        assert report.total_ghosts == 0
        assert report.severity_distribution == {"high": 0, "medium": 0, "low": 0}
        assert report.recommendations == []

    def test_detect_ghost_decisions_empty_diffs(self):
        """Empty diffs returns empty report with zeroed counters."""
        # Arrange
        mem = _memory(decisions=[
            _decision("Use snake_case naming convention"),
        ])

        # Act
        report = detect_ghost_decisions(mem, [])

        # Assert
        assert report.ghosts == []
        assert report.total_decisions_checked == 1
        assert report.total_diffs_checked == 0
        assert report.total_ghosts == 0

    def test_detect_ghost_decisions_finds_drift(self):
        """Naming decision + diff with matching keywords produces ghost detections."""
        # Arrange
        now = datetime.now(timezone.utc).isoformat()
        mem = _memory(decisions=[
            _decision(
                "Use snake_case naming convention for all Python module functions",
                did="naming-1",
                ts=now,
            ),
        ])
        # Diff contains a comment with keywords overlapping the decision
        diffs = [_diff_entry("src/utils.py", CAMEL_CASE_DIFF)]

        # Act
        report = detect_ghost_decisions(mem, diffs)

        # Assert
        assert report.total_ghosts >= 1
        assert report.total_decisions_checked == 1
        assert report.total_diffs_checked == 1
        # At least one ghost should reference the naming decision
        assert any(g.decision_id == "naming-1" for g in report.ghosts)

    def test_detect_ghost_decisions_no_drift_clean(self):
        """No overlapping keywords means no ghosts detected."""
        # Arrange
        now = datetime.now(timezone.utc).isoformat()
        mem = _memory(decisions=[
            _decision(
                "Use PostgreSQL for the primary database",
                did="db-1",
                ts=now,
            ),
        ])
        clean_diff = "+button { background: blue; }\n"
        diffs = [_diff_entry("src/styles.css", clean_diff)]

        # Act
        report = detect_ghost_decisions(mem, diffs)

        # Assert
        assert report.total_ghosts == 0
        assert report.severity_distribution == {"high": 0, "medium": 0, "low": 0}

    def test_severity_distribution(self):
        """Severity distribution counts are correct for mixed severities."""
        # Arrange
        now = datetime.now(timezone.utc).isoformat()
        mem = _memory(decisions=[
            _decision(
                "Use snake_case naming convention for all Python module functions",
                did="naming-1",
                ts=now,
            ),
            _decision(
                "Use snake_case naming convention for all Python module variables",
                did="naming-2",
                ts=now,
            ),
        ])
        diffs = [_diff_entry("src/utils.py", CAMEL_CASE_DIFF)]

        # Act
        report = detect_ghost_decisions(mem, diffs)

        # Assert
        total_from_dist = sum(report.severity_distribution.values())
        assert total_from_dist == report.total_ghosts
        # Each tier should be non-negative
        for tier in ("high", "medium", "low"):
            assert report.severity_distribution[tier] >= 0

    def test_report_recommendations(self):
        """Report-level recommendations are generated from ghost severities."""
        # Arrange
        now = datetime.now(timezone.utc).isoformat()
        mem = _memory(decisions=[
            _decision(
                "Use snake_case naming convention for all Python module functions and variables",
                did="naming-1",
                ts=now,
            ),
        ])
        diffs = [_diff_entry("src/utils.py", CAMEL_CASE_DIFF)]

        # Act
        report = detect_ghost_decisions(mem, diffs)

        # Assert
        if report.total_ghosts > 0:
            assert isinstance(report.recommendations, list)
            assert len(report.recommendations) > 0
            # Each recommendation should be a non-empty string
            for rec in report.recommendations:
                assert isinstance(rec, str)
                assert len(rec) > 0

    def test_ghosts_sorted_by_severity(self):
        """Ghosts in the report are sorted by severity descending."""
        # Arrange
        now = datetime.now(timezone.utc).isoformat()
        mem = _memory(decisions=[
            _decision(
                "Use snake_case naming convention for all Python module functions",
                did="naming-1",
                ts=now,
            ),
            _decision(
                "Use snake_case naming convention for all Python module variables",
                did="naming-2",
                ts=now,
            ),
        ])
        diffs = [_diff_entry("src/utils.py", CAMEL_CASE_DIFF)]

        # Act
        report = detect_ghost_decisions(mem, diffs)

        # Assert
        if len(report.ghosts) >= 2:
            severities = [g.severity for g in report.ghosts]
            assert severities == sorted(severities, reverse=True)


# ===========================================================================
#  3. Router Tests (httpx AsyncClient)
# ===========================================================================


def _app():
    """Create a FastAPI app with the ghost router included."""
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(ghost_router)
    return app


class TestGhostDecisionsEndpoint:
    def test_ghost_decisions_endpoint_returns_200(self):
        """GET /api/memory/{project}/ghost-decisions returns 200 with valid memory."""
        import asyncio
        from httpx import ASGITransport, AsyncClient

        # Arrange
        mock_memory = {
            "decisions": [
                {"id": "d1", "decision": "Use snake_case naming", "timestamp": "2026-07-01T00:00:00Z"},
            ],
        }

        async def _call():
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.get("/api/memory/test-project/ghost-decisions")

        with patch("core.ghost.router._load_memory", return_value=mock_memory):
            resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 200
        body = resp.json()
        assert "ghosts" in body
        assert "total_decisions_checked" in body
        assert "total_diffs_checked" in body
        assert "total_ghosts" in body
        assert "severity_distribution" in body
        assert "recommendations" in body

    def test_ghost_decisions_endpoint_returns_404_for_unknown_project(self):
        """GET /api/memory/{project}/ghost-decisions returns 404 for missing project."""
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
                return await client.get("/api/memory/nonexistent-project/ghost-decisions")

        with patch("core.ghost.router._load_memory", side_effect=_mock_load):
            resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 404
        body = resp.json()
        assert "not found" in body["detail"].lower()

    def test_ghost_decisions_endpoint_with_empty_decisions(self):
        """GET /api/memory/{project}/ghost-decisions with empty decisions returns valid report."""
        import asyncio
        from httpx import ASGITransport, AsyncClient

        # Arrange
        mock_memory = {"decisions": []}

        async def _call():
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.get("/api/memory/test-project/ghost-decisions")

        with patch("core.ghost.router._load_memory", return_value=mock_memory):
            resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_ghosts"] == 0
        assert body["ghosts"] == []
