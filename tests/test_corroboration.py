"""
Tests for Corroboration — scorer, orchestrator, and router.

Covers pure scoring functions, orchestration with mocked dependencies,
and HTTP router endpoints. Uses pytest, AAA pattern, no shared state.
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from core.corroboration import (
    CorroborationReport,
    CorroborationStatus,
    Err,
    Ok,
    ResearchFinding,
)
from core.corroboration.scorer import (
    CorroborationResult,
    ResearchFinding as ScorerFinding,
    compute_relevance,
    detect_contradiction_signals,
    detect_outdated_signals,
    score_corroboration,
)
from core.corroboration.corroborator import (
    _find_decision,
    _to_scorer_findings,
    build_research_query,
    corroborate_decision,
    extract_rationale,
)
from core.corroboration.router import corroboration_router


# ---------------------------------------------------------------------------
#  Helpers — realistic mock data
# ---------------------------------------------------------------------------


def _scorer_finding(
    title: str = "Test Finding",
    url: str = "https://example.com/test",
    description: str = "A test finding about Python",
    relevance_score: float = 0.0,
    published_date: str | None = None,
) -> ScorerFinding:
    """Create a scorer ResearchFinding."""
    return ScorerFinding(
        title=title,
        url=url,
        description=description,
        relevance_score=relevance_score,
        published_date=published_date,
    )


def _report_finding(
    title: str = "Test Finding",
    url: str = "https://example.com/test",
    description: str = "A test finding",
    source: str = "web",
    relevance_score: float = 0.5,
) -> ResearchFinding:
    """Create a report ResearchFinding (from __init__.py)."""
    return ResearchFinding(
        title=title,
        url=url,
        description=description,
        source=source,
        relevance_score=relevance_score,
    )


def _search_result(
    title: str = "Test Result",
    url: str = "https://example.com/test",
    description: str = "A test search result",
    source: str = "web",
) -> MagicMock:
    """Create a mock SearchResult."""
    result = MagicMock()
    result.title = title
    result.url = url
    result.description = description
    result.source = source
    return result


def _decision_dict(
    text: str = "Use FastAPI for the web framework",
    did: str = "dec-1",
    rationale: str = "FastAPI is modern and performant for async Python web apps",
    **extra,
) -> dict:
    """Create a decision dict matching project memory schema."""
    d = {"id": did, "decision": text, "rationale": rationale}
    d.update(extra)
    return d


def _memory(decisions: list | None = None) -> dict:
    """Create a memory dict."""
    return {"decisions": decisions or []}


def _mock_memory_manager(memory: dict | None = None) -> MagicMock:
    """Create a mock MemoryManager returning the given memory."""
    mm = MagicMock()
    mm.get_project_memory.return_value = memory or _memory()
    return mm


def _mock_research_tool(results: list | None = None) -> MagicMock:
    """Create a mock ResearchTool returning the given search results."""
    rt = MagicMock()
    rt.research.return_value = results or []
    return rt


# ===========================================================================
#  1. Scorer Tests — Pure Functions
# ===========================================================================


class TestScoreCorroboration:
    """Tests for score_corroboration status and confidence adjustment."""

    def test_score_corroboration_no_findings(self):
        """Empty findings → unverifiable with 0.0 adjustment."""
        # Arrange
        rationale = "Use FastAPI for async web framework"

        # Act
        result = score_corroboration(rationale, [])

        # Assert
        assert result.status == "unverifiable"
        assert result.confidence_adjustment == 0.0
        assert "No research findings" in result.reasoning

    def test_score_corroboration_supported(self):
        """High-relevance findings with no signals → supported with +0.1."""
        # Arrange
        rationale = "Use FastAPI for async Python web framework performance"
        findings = [
            _scorer_finding(
                title="FastAPI async performance guide",
                description="FastAPI is a modern async Python web framework with excellent performance",
            ),
            _scorer_finding(
                title="FastAPI benchmarks",
                description="FastAPI async Python framework benchmarks show great performance results",
            ),
        ]

        # Act
        result = score_corroboration(rationale, findings)

        # Assert
        assert result.status == "supported"
        assert result.confidence_adjustment == 0.1
        assert len(result.evidence_urls) > 0

    def test_score_corroboration_contradicted(self):
        """Contradiction signals (≥2) → contradicted with -0.3."""
        # Arrange
        rationale = "Use FastAPI for async Python web framework"
        findings = [
            _scorer_finding(
                title="FastAPI deprecated in favor of Starlite",
                description="FastAPI async Python framework deprecated in favor of Starlite",
            ),
            _scorer_finding(
                title="Migration away from FastAPI",
                description="FastAPI no longer recommended for async Python, replaced by Starlite",
            ),
        ]

        # Act
        result = score_corroboration(rationale, findings)

        # Assert
        assert result.status == "contradicted"
        assert result.confidence_adjustment == -0.3

    def test_score_corroboration_outdated(self):
        """Outdated signals → outdated with -0.15."""
        # Arrange
        rationale = "Use FastAPI for async Python web framework"
        findings = [
            _scorer_finding(
                title="FastAPI legacy version guide",
                description="FastAPI async Python legacy version migration guide",
            ),
        ]

        # Act
        result = score_corroboration(rationale, findings)

        # Assert
        assert result.status == "outdated"
        assert result.confidence_adjustment == -0.15

    def test_score_corroboration_unverifiable_low_relevance(self):
        """Findings with low relevance (<0.3) → unverifiable."""
        # Arrange
        rationale = "Use FastAPI for async Python web framework"
        findings = [
            _scorer_finding(
                title="Cooking recipes",
                description="Best chocolate cake recipe for dinner parties",
            ),
        ]

        # Act
        result = score_corroboration(rationale, findings)

        # Assert
        assert result.status == "unverifiable"
        assert result.confidence_adjustment == 0.0
        assert "low relevance" in result.reasoning.lower()

    def test_score_corroboration_unverifiable_medium_only(self):
        """Only medium-relevance (≥0.3, <0.5) findings with no signals → unverifiable."""
        # Arrange — rationale and finding share some but not many words
        rationale = "Use FastAPI for async Python web framework performance optimization"
        findings = [
            _scorer_finding(
                title="Random article about cooking",
                description="A guide to making pasta and Italian cuisine at home",
            ),
        ]

        # Act
        result = score_corroboration(rationale, findings)

        # Assert
        assert result.status == "unverifiable"
        assert result.confidence_adjustment == 0.0

    def test_score_corroboration_contradiction_takes_priority_over_outdated(self):
        """When both contradiction and outdated signals exist, contradiction wins."""
        # Arrange
        rationale = "Use FastAPI for async Python web framework"
        findings = [
            _scorer_finding(
                title="FastAPI deprecated legacy guide",
                description="FastAPI async Python framework deprecated, legacy version no longer maintained",
            ),
            _scorer_finding(
                title="Replace FastAPI",
                description="FastAPI async Python replaced by newer framework, not recommended",
            ),
        ]

        # Act
        result = score_corroboration(rationale, findings)

        # Assert
        assert result.status == "contradicted"
        assert result.confidence_adjustment == -0.3


class TestComputeRelevance:
    """Tests for keyword overlap calculation."""

    def test_compute_relevance_full_overlap(self):
        """Identical text → 1.0 relevance."""
        # Arrange
        rationale = "FastAPI async Python web framework"
        finding = _scorer_finding(
            description="FastAPI async Python web framework",
            title="FastAPI async Python web framework",
        )

        # Act
        score = compute_relevance(rationale, finding)

        # Assert
        assert score == 1.0

    def test_compute_relevance_no_overlap(self):
        """Completely different text → 0.0 relevance."""
        # Arrange
        rationale = "FastAPI async Python web framework"
        finding = _scorer_finding(
            description="Cooking chocolate cake recipe",
            title="Best desserts",
        )

        # Act
        score = compute_relevance(rationale, finding)

        # Assert
        assert score == 0.0

    def test_compute_relevance_partial_overlap(self):
        """Partial keyword overlap → proportional score."""
        # Arrange
        rationale = "FastAPI async Python web framework"
        finding = _scorer_finding(
            description="FastAPI is a Python framework",
            title="FastAPI guide",
        )

        # Act
        score = compute_relevance(rationale, finding)

        # Assert
        assert 0.0 < score < 1.0
        # "fastapi", "python", "framework" = 3 out of 5 rationale words
        assert score == pytest.approx(3 / 5)

    def test_compute_relevance_empty_rationale(self):
        """Empty rationale → 0.0 (no words to match)."""
        # Arrange
        finding = _scorer_finding(description="FastAPI Python framework")

        # Act
        score = compute_relevance("", finding)

        # Assert
        assert score == 0.0

    def test_compute_relevance_stopwords_excluded(self):
        """Stopwords are excluded from overlap calculation."""
        # Arrange — rationale is all stopwords after extraction
        rationale = "the is are was were"
        finding = _scorer_finding(description="FastAPI Python framework")

        # Act
        score = compute_relevance(rationale, finding)

        # Assert
        assert score == 0.0


class TestDetectContradictionSignals:
    """Tests for finding contradiction keywords in relevant findings."""

    def test_detect_contradiction_signals_finds_deprecated(self):
        """'deprecated' keyword in relevant finding → signal detected."""
        # Arrange
        rationale = "Use FastAPI for async web framework"
        findings = [
            _scorer_finding(
                description="FastAPI async framework has been deprecated by maintainers",
            ),
        ]

        # Act
        signals = detect_contradiction_signals(rationale, findings)

        # Assert
        assert len(signals) == 1
        assert "deprecated" in signals[0].lower()

    def test_detect_contradiction_signals_finds_replaced_by(self):
        """'replaced by' keyword in relevant finding → signal detected."""
        # Arrange
        rationale = "Use FastAPI for async web framework"
        findings = [
            _scorer_finding(
                description="FastAPI async framework replaced by Starlite",
            ),
        ]

        # Act
        signals = detect_contradiction_signals(rationale, findings)

        # Assert
        assert len(signals) == 1
        assert "replaced by" in signals[0].lower()

    def test_detect_contradiction_signals_skips_irrelevant(self):
        """Findings with no rationale overlap are skipped."""
        # Arrange
        rationale = "Use FastAPI for async web framework"
        findings = [
            _scorer_finding(
                description="Cooking deprecated recipes for chocolate cake",
            ),
        ]

        # Act
        signals = detect_contradiction_signals(rationale, findings)

        # Assert
        assert len(signals) == 0

    def test_detect_contradiction_signals_multiple_keywords(self):
        """Multiple findings with different contradiction keywords."""
        # Arrange
        rationale = "Use FastAPI for async web framework"
        findings = [
            _scorer_finding(
                description="FastAPI async framework deprecated by community",
            ),
            _scorer_finding(
                description="FastAPI async framework no longer recommended for production",
            ),
        ]

        # Act
        signals = detect_contradiction_signals(rationale, findings)

        # Assert
        assert len(signals) == 2

    def test_detect_contradiction_signals_empty_findings(self):
        """No findings → no signals."""
        # Arrange
        rationale = "Use FastAPI for async web framework"

        # Act
        signals = detect_contradiction_signals(rationale, [])

        # Assert
        assert len(signals) == 0

    def test_detect_contradiction_signals_all_keywords(self):
        """All contradiction keywords are detected."""
        # Arrange
        rationale = "Use Redis for caching"
        keywords = [
            "deprecated", "no longer", "replaced by",
            "instead use", "not recommended", "end of life", "sunset",
        ]

        for kw in keywords:
            findings = [_scorer_finding(
                description=f"Redis for caching {kw} now",
            )]

            # Act
            signals = detect_contradiction_signals(rationale, findings)

            # Assert
            assert len(signals) >= 1, f"Keyword '{kw}' not detected"


class TestDetectOutdatedSignals:
    """Tests for finding outdated markers in findings."""

    def test_detect_outdated_signals_legacy_keyword(self):
        """'legacy' keyword → outdated signal."""
        # Arrange
        findings = [
            _scorer_finding(description="This is a legacy version of the library"),
        ]

        # Act
        signals = detect_outdated_signals(findings)

        # Assert
        assert len(signals) == 1
        assert "legacy" in signals[0].lower()

    def test_detect_outdated_signals_old_version_keyword(self):
        """'old version' keyword → outdated signal."""
        # Arrange
        findings = [
            _scorer_finding(description="Documentation for the old version of the tool"),
        ]

        # Act
        signals = detect_outdated_signals(findings)

        # Assert
        assert len(signals) == 1
        assert "old version" in signals[0].lower()

    def test_detect_outdated_signals_old_date(self):
        """Finding published >730 days ago → outdated signal."""
        # Arrange
        findings = [
            _scorer_finding(
                description="FastAPI framework overview",
                published_date="2020-01-01T00:00:00Z",
            ),
        ]

        # Act
        signals = detect_outdated_signals(findings)

        # Assert
        assert len(signals) == 1

    def test_detect_outdated_signals_recent_date_no_keyword(self):
        """Recent finding with no keywords → no signal."""
        # Arrange
        findings = [
            _scorer_finding(
                description="FastAPI framework overview",
                published_date="2026-06-01T00:00:00Z",
            ),
        ]

        # Act
        signals = detect_outdated_signals(findings)

        # Assert
        assert len(signals) == 0

    def test_detect_outdated_signals_empty_findings(self):
        """No findings → no signals."""
        # Act
        signals = detect_outdated_signals([])

        # Assert
        assert len(signals) == 0

    def test_detect_outdated_signals_invalid_date_ignored(self):
        """Invalid date string is ignored gracefully."""
        # Arrange
        findings = [
            _scorer_finding(
                description="Some finding",
                published_date="not-a-date",
            ),
        ]

        # Act
        signals = detect_outdated_signals(findings)

        # Assert
        # Invalid date is ignored, no keyword match → no signal
        assert len(signals) == 0

    def test_detect_outdated_signals_all_keywords(self):
        """All outdated keywords are detected."""
        # Arrange
        keywords = ["legacy", "old version", "previous version", "was used", "formerly"]

        for kw in keywords:
            findings = [_scorer_finding(description=f"This {kw} tool is still referenced")]

            # Act
            signals = detect_outdated_signals(findings)

            # Assert
            assert len(signals) >= 1, f"Keyword '{kw}' not detected"


# ===========================================================================
#  2. Corroborator Tests — Orchestration with Mocks
# ===========================================================================


class TestExtractRationale:
    """Tests for extracting rationale from decision dicts."""

    def test_extract_rationale_with_field(self):
        """Decision with explicit 'rationale' field uses it."""
        # Arrange
        decision = _decision_dict(rationale="FastAPI provides excellent async performance")

        # Act
        result = extract_rationale(decision)

        # Assert
        assert result == "FastAPI provides excellent async performance"

    def test_extract_rationale_uses_reason_field(self):
        """Falls back to 'reason' field if 'rationale' is empty."""
        # Arrange
        decision = {"decision": "Use FastAPI", "reason": "FastAPI has great async support"}

        # Act
        result = extract_rationale(decision)

        # Assert
        assert result == "FastAPI has great async support"

    def test_extract_rationale_uses_context_field(self):
        """Falls back to 'context' field."""
        # Arrange
        decision = {"decision": "Use FastAPI", "context": "Modern async Python framework choice"}

        # Act
        result = extract_rationale(decision)

        # Assert
        assert result == "Modern async Python framework choice"

    def test_extract_rationale_fallback_to_decision(self):
        """No rationale/reason/context → uses 'decision' text."""
        # Arrange
        decision = {"decision": "Use FastAPI for the web framework"}

        # Act
        result = extract_rationale(decision)

        # Assert
        assert result == "Use FastAPI for the web framework"

    def test_extract_rationale_empty(self):
        """Empty decision → empty string."""
        # Arrange
        decision = {}

        # Act
        result = extract_rationale(decision)

        # Assert
        assert result == ""

    def test_extract_rationale_short_rationale_ignored(self):
        """Rationale ≤5 chars is ignored, falls through to next field."""
        # Arrange
        decision = {"decision": "Use FastAPI", "rationale": "good"}

        # Act
        result = extract_rationale(decision)

        # Assert
        assert result == "Use FastAPI"

    def test_extract_rationale_non_string_ignored(self):
        """Non-string rationale field is ignored."""
        # Arrange
        decision = {"decision": "Use FastAPI", "rationale": 42}

        # Act
        result = extract_rationale(decision)

        # Assert
        assert result == "Use FastAPI"


class TestBuildResearchQuery:
    """Tests for search query generation."""

    def test_build_research_query_generates_query(self):
        """Decision + rationale produce a focused search query."""
        # Arrange
        decision = {"decision": "Use FastAPI for the web framework"}
        rationale = "FastAPI is modern and performant for async Python web apps"

        # Act
        query = build_research_query(decision, rationale)

        # Assert
        assert "fastapi" in query.lower()
        assert "async" in query.lower()
        assert "python" in query.lower()
        # Stopwords should be removed
        assert "the" not in query.lower().split()
        assert "for" not in query.lower().split()

    def test_build_research_query_caps_at_15_tokens(self):
        """Query is capped at 15 tokens."""
        # Arrange
        decision = {"decision": " ".join([f"word{i}" for i in range(20)])}
        rationale = " ".join([f"rationale{i}" for i in range(20)])

        # Act
        query = build_research_query(decision, rationale)

        # Assert
        assert len(query.split()) <= 15

    def test_build_research_query_empty_inputs(self):
        """Empty decision and rationale → empty query."""
        # Arrange
        decision = {}
        rationale = ""

        # Act
        query = build_research_query(decision, rationale)

        # Assert
        assert query == ""


class TestFindDecision:
    """Tests for _find_decision lookup."""

    def test_find_decision_by_index(self):
        """Numeric decision_id → index lookup."""
        # Arrange
        memory = _memory(decisions=[
            {"decision": "First decision"},
            {"decision": "Second decision"},
        ])

        # Act
        result = _find_decision(memory, "1")

        # Assert
        assert isinstance(result, Ok)
        assert result.value["decision"] == "Second decision"

    def test_find_decision_by_text_match(self):
        """Non-numeric decision_id → text substring search."""
        # Arrange
        memory = _memory(decisions=[
            {"decision": "Use FastAPI for web"},
            {"decision": "Use Redis for caching"},
        ])

        # Act
        result = _find_decision(memory, "Redis")

        # Assert
        assert isinstance(result, Ok)
        assert "Redis" in result.value["decision"]

    def test_find_decision_not_found(self):
        """Decision not in memory → Err NOT_FOUND."""
        # Arrange
        memory = _memory(decisions=[
            {"decision": "Use FastAPI for web"},
        ])

        # Act
        result = _find_decision(memory, "nonexistent")

        # Assert
        assert isinstance(result, Err)
        assert result.code == "NOT_FOUND"

    def test_find_decision_index_out_of_range(self):
        """Index beyond decisions list → Err NOT_FOUND."""
        # Arrange
        memory = _memory(decisions=[{"decision": "Only decision"}])

        # Act
        result = _find_decision(memory, "5")

        # Assert
        assert isinstance(result, Err)
        assert result.code == "NOT_FOUND"
        assert "out of range" in result.error

    def test_find_decision_empty_decisions(self):
        """No decisions in memory → Err NOT_FOUND."""
        # Arrange
        memory = _memory(decisions=[])

        # Act
        result = _find_decision(memory, "0")

        # Assert
        assert isinstance(result, Err)
        assert result.code == "NOT_FOUND"
        assert "No decisions" in result.error


class TestCorroborateDecision:
    """Tests for the full orchestration pipeline."""

    def test_corroborate_decision_success(self):
        """Happy path: memory found, rationale extracted, research returns results."""
        # Arrange
        decision = _decision_dict(
            text="Use FastAPI for async web",
            rationale="FastAPI provides excellent async Python performance for web apps",
        )
        memory = _memory(decisions=[decision])
        mm = _mock_memory_manager(memory)

        search_results = [
            _search_result(
                title="FastAPI async performance",
                description="FastAPI provides excellent async Python performance for web apps",
                url="https://example.com/fastapi",
                source="web",
            ),
        ]
        rt = _mock_research_tool(search_results)

        # Act
        result = corroborate_decision(
            project="test-project",
            decision_id="0",
            research_tool=rt,
            memory_manager=mm,
        )

        # Assert
        assert isinstance(result, Ok)
        report = result.value
        assert report.decision_id == "0"
        assert report.status in ("supported", "outdated", "contradicted", "unverifiable")
        assert isinstance(report.confidence_adjustment, float)
        assert len(report.research_findings) == 1
        assert report.checked_at  # non-empty ISO timestamp

    def test_corroborate_decision_not_found(self):
        """Missing decision → Err with NOT_FOUND code."""
        # Arrange
        memory = _memory(decisions=[])
        mm = _mock_memory_manager(memory)
        rt = _mock_research_tool()

        # Act
        result = corroborate_decision(
            project="test-project",
            decision_id="nonexistent",
            research_tool=rt,
            memory_manager=mm,
        )

        # Assert
        assert isinstance(result, Err)
        assert result.code == "NOT_FOUND"

    def test_corroborate_decision_unverifiable_empty_rationale(self):
        """Empty rationale → Ok with unverifiable status."""
        # Arrange
        decision = {"id": "d1", "decision": ""}
        memory = _memory(decisions=[decision])
        mm = _mock_memory_manager(memory)
        rt = _mock_research_tool()

        # Act
        result = corroborate_decision(
            project="test-project",
            decision_id="0",
            research_tool=rt,
            memory_manager=mm,
        )

        # Assert
        assert isinstance(result, Ok)
        report = result.value
        assert report.status == CorroborationStatus.unverifiable
        assert report.confidence_adjustment == 0.0
        assert report.research_findings == ()

    def test_corroborate_decision_memory_error(self):
        """MemoryManager raises OSError → Err with MEMORY_ERROR code."""
        # Arrange
        mm = MagicMock()
        mm.get_project_memory.side_effect = OSError("File not found")
        rt = _mock_research_tool()

        # Act
        result = corroborate_decision(
            project="test-project",
            decision_id="0",
            research_tool=rt,
            memory_manager=mm,
        )

        # Assert
        assert isinstance(result, Err)
        assert result.code == "MEMORY_ERROR"
        assert "Failed loading project" in result.error

    def test_corroborate_decision_memory_value_error(self):
        """MemoryManager raises ValueError → Err with MEMORY_ERROR code."""
        # Arrange
        mm = MagicMock()
        mm.get_project_memory.side_effect = ValueError("Invalid project name")
        rt = _mock_research_tool()

        # Act
        result = corroborate_decision(
            project="test-project",
            decision_id="0",
            research_tool=rt,
            memory_manager=mm,
        )

        # Assert
        assert isinstance(result, Err)
        assert result.code == "MEMORY_ERROR"

    def test_corroborate_decision_research_connection_error(self):
        """ResearchTool raises ConnectionError → Err with RESEARCH_ERROR code."""
        # Arrange
        decision = _decision_dict(
            rationale="FastAPI provides excellent async Python performance",
        )
        memory = _memory(decisions=[decision])
        mm = _mock_memory_manager(memory)

        rt = MagicMock()
        rt.research.side_effect = ConnectionError("Network unreachable")

        # Act
        result = corroborate_decision(
            project="test-project",
            decision_id="0",
            research_tool=rt,
            memory_manager=mm,
        )

        # Assert
        assert isinstance(result, Err)
        assert result.code == "RESEARCH_ERROR"
        assert "Research API failed" in result.error

    def test_corroborate_decision_research_timeout_error(self):
        """ResearchTool raises TimeoutError → Err with RESEARCH_ERROR code."""
        # Arrange
        decision = _decision_dict(
            rationale="FastAPI provides excellent async Python performance",
        )
        memory = _memory(decisions=[decision])
        mm = _mock_memory_manager(memory)

        rt = MagicMock()
        rt.research.side_effect = TimeoutError("Request timed out")

        # Act
        result = corroborate_decision(
            project="test-project",
            decision_id="0",
            research_tool=rt,
            memory_manager=mm,
        )

        # Assert
        assert isinstance(result, Err)
        assert result.code == "RESEARCH_ERROR"

    def test_corroborate_decision_research_os_error(self):
        """ResearchTool raises OSError → Err with RESEARCH_ERROR code."""
        # Arrange
        decision = _decision_dict(
            rationale="FastAPI provides excellent async Python performance",
        )
        memory = _memory(decisions=[decision])
        mm = _mock_memory_manager(memory)

        rt = MagicMock()
        rt.research.side_effect = OSError("Disk full")

        # Act
        result = corroborate_decision(
            project="test-project",
            decision_id="0",
            research_tool=rt,
            memory_manager=mm,
        )

        # Assert
        assert isinstance(result, Err)
        assert result.code == "RESEARCH_ERROR"

    def test_corroborate_decision_by_text_match(self):
        """Decision found via text substring → success."""
        # Arrange
        decision = _decision_dict(
            text="Use Redis for caching layer",
            rationale="Redis provides sub-millisecond latency for caching",
        )
        memory = _memory(decisions=[decision])
        mm = _mock_memory_manager(memory)
        rt = _mock_research_tool([_search_result()])

        # Act
        result = corroborate_decision(
            project="test-project",
            decision_id="Redis",
            research_tool=rt,
            memory_manager=mm,
        )

        # Assert
        assert isinstance(result, Ok)
        assert result.value.decision_id == "Redis"


class TestToScorerFindings:
    """Tests for SearchResult → ScorerFinding conversion."""

    def test_to_scorer_findings_converts_correctly(self):
        """SearchResults are converted to scorer-compatible findings."""
        # Arrange
        results = [
            _search_result(title="T1", url="https://u1.com", description="D1"),
            _search_result(title="T2", url="https://u2.com", description="D2"),
        ]

        # Act
        findings = _to_scorer_findings(results)

        # Assert
        assert len(findings) == 2
        assert findings[0].title == "T1"
        assert findings[0].url == "https://u1.com"
        assert findings[0].description == "D1"
        assert findings[1].title == "T2"

    def test_to_scorer_findings_empty(self):
        """Empty results → empty findings."""
        # Act
        findings = _to_scorer_findings([])

        # Assert
        assert findings == []


# ===========================================================================
#  3. Router Tests (httpx AsyncClient)
# ===========================================================================


def _app():
    """Create a FastAPI app with the corroboration router included."""
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(corroboration_router)
    return app


class TestRouterCorroborate:
    """Tests for POST /api/memory/{project}/corroborate."""

    def test_router_corroborate_success(self):
        """POST returns 200 with valid report on success."""
        # Arrange
        from httpx import ASGITransport, AsyncClient

        mock_report = CorroborationReport(
            decision_id="dec-1",
            rationale="FastAPI is modern and performant",
            research_findings=(
                ResearchFinding(
                    title="FastAPI Guide",
                    url="https://example.com",
                    description="FastAPI is modern",
                    source="web",
                    relevance_score=0.8,
                ),
            ),
            status=CorroborationStatus.supported,
            confidence_adjustment=0.1,
            evidence_urls=("https://example.com",),
            checked_at="2026-07-18T00:00:00+00:00",
        )

        async def _call():
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.post(
                    "/api/memory/test-project/corroborate",
                    json={"decision_id": "dec-1"},
                )

        with patch(
            "core.corroboration.router._verify_project_exists",
        ), patch(
            "core.corroboration.router.corroborate_decision",
            return_value=Ok(value=mock_report),
        ):
            resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 200
        body = resp.json()
        assert body["decision_id"] == "dec-1"
        assert body["status"] == "supported"
        assert body["confidence_adjustment"] == 0.1
        assert len(body["research_findings"]) == 1
        assert body["evidence_urls"] == ["https://example.com"]

    def test_router_corroborate_missing_project(self):
        """POST returns 404 when project doesn't exist."""
        # Arrange
        from httpx import ASGITransport, AsyncClient
        from fastapi import HTTPException

        async def _call():
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.post(
                    "/api/memory/nonexistent-project/corroborate",
                    json={"decision_id": "dec-1"},
                )

        with patch(
            "core.corroboration.router._verify_project_exists",
            side_effect=HTTPException(status_code=404, detail="Project 'nonexistent-project' not found"),
        ):
            resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 404
        body = resp.json()
        assert "not found" in body["detail"].lower()

    def test_router_corroborate_empty_id(self):
        """POST returns 422 when decision_id is empty (Pydantic validation)."""
        # Arrange
        from httpx import ASGITransport, AsyncClient

        async def _call():
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.post(
                    "/api/memory/test-project/corroborate",
                    json={"decision_id": ""},
                )

        # Act
        resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 422

    def test_router_corroborate_decision_not_found(self):
        """POST returns 404 when decision not found in memory."""
        # Arrange
        from httpx import ASGITransport, AsyncClient

        async def _call():
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.post(
                    "/api/memory/test-project/corroborate",
                    json={"decision_id": "nonexistent"},
                )

        with patch(
            "core.corroboration.router._verify_project_exists",
        ), patch(
            "core.corroboration.router.corroborate_decision",
            return_value=Err(error="Decision 'nonexistent' not found", code="NOT_FOUND"),
        ):
            resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 404

    def test_router_corroborate_memory_error(self):
        """POST returns 404 when memory loading fails."""
        # Arrange
        from httpx import ASGITransport, AsyncClient

        async def _call():
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.post(
                    "/api/memory/test-project/corroborate",
                    json={"decision_id": "dec-1"},
                )

        with patch(
            "core.corroboration.router._verify_project_exists",
        ), patch(
            "core.corroboration.router.corroborate_decision",
            return_value=Err(error="Failed loading project", code="MEMORY_ERROR"),
        ):
            resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 404

    def test_router_corroborate_research_error(self):
        """POST returns 500 when research API fails."""
        # Arrange
        from httpx import ASGITransport, AsyncClient

        async def _call():
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.post(
                    "/api/memory/test-project/corroborate",
                    json={"decision_id": "dec-1"},
                )

        with patch(
            "core.corroboration.router._verify_project_exists",
        ), patch(
            "core.corroboration.router.corroborate_decision",
            return_value=Err(error="Research API failed", code="RESEARCH_ERROR"),
        ):
            resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 500

    def test_router_corroborate_validation_error(self):
        """POST returns 422 when validation fails."""
        # Arrange
        from httpx import ASGITransport, AsyncClient

        async def _call():
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.post(
                    "/api/memory/test-project/corroborate",
                    json={"decision_id": "dec-1"},
                )

        with patch(
            "core.corroboration.router._verify_project_exists",
        ), patch(
            "core.corroboration.router.corroborate_decision",
            return_value=Err(error="Invalid input", code="VALIDATION_ERROR"),
        ):
            resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 422

    def test_router_corroborate_unknown_error(self):
        """POST returns 500 for unknown error codes."""
        # Arrange
        from httpx import ASGITransport, AsyncClient

        async def _call():
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.post(
                    "/api/memory/test-project/corroborate",
                    json={"decision_id": "dec-1"},
                )

        with patch(
            "core.corroboration.router._verify_project_exists",
        ), patch(
            "core.corroboration.router.corroborate_decision",
            return_value=Err(error="Something broke", code="UNKNOWN"),
        ):
            resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 500

    def test_router_corroborate_missing_body(self):
        """POST returns 422 when request body is missing."""
        # Arrange
        from httpx import ASGITransport, AsyncClient

        async def _call():
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.post("/api/memory/test-project/corroborate")

        # Act
        resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 422


class TestRouterCorroborateBatch:
    """Tests for POST /api/memory/{project}/corroborate/batch."""

    def test_router_batch_success(self):
        """POST batch returns results with summary."""
        # Arrange
        from httpx import ASGITransport, AsyncClient

        mock_report = CorroborationReport(
            decision_id="dec-1",
            rationale="FastAPI is modern",
            research_findings=(),
            status=CorroborationStatus.supported,
            confidence_adjustment=0.1,
            evidence_urls=(),
            checked_at="2026-07-18T00:00:00+00:00",
        )

        async def _call():
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.post(
                    "/api/memory/test-project/corroborate/batch",
                    json={"decision_ids": ["dec-1", "dec-2"]},
                )

        with patch(
            "core.corroboration.router._verify_project_exists",
        ), patch(
            "core.corroboration.router.corroborate_decision",
            return_value=Ok(value=mock_report),
        ):
            resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert len(body["results"]) == 2
        assert "summary" in body
        assert body["summary"]["supported"] == 2
        assert "checked_at" in body

    def test_router_batch_empty_ids(self):
        """POST batch returns 422 when decision_ids is empty."""
        # Arrange
        from httpx import ASGITransport, AsyncClient

        async def _call():
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.post(
                    "/api/memory/test-project/corroborate/batch",
                    json={"decision_ids": []},
                )

        # Act
        resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 422

    def test_router_batch_missing_project(self):
        """POST batch returns 404 when project doesn't exist."""
        # Arrange
        from httpx import ASGITransport, AsyncClient
        from fastapi import HTTPException

        async def _call():
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.post(
                    "/api/memory/nonexistent/corroborate/batch",
                    json={"decision_ids": ["dec-1"]},
                )

        with patch(
            "core.corroboration.router._verify_project_exists",
            side_effect=HTTPException(status_code=404, detail="Project 'nonexistent' not found"),
        ):
            resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 404

    def test_router_batch_partial_failure(self):
        """POST batch handles mixed success/failure results."""
        # Arrange
        from httpx import ASGITransport, AsyncClient

        mock_report = CorroborationReport(
            decision_id="dec-1",
            rationale="Good rationale",
            research_findings=(),
            status=CorroborationStatus.supported,
            confidence_adjustment=0.1,
            evidence_urls=(),
            checked_at="2026-07-18T00:00:00+00:00",
        )

        call_count = 0

        def _side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return Ok(value=mock_report)
            return Err(error="Decision not found", code="NOT_FOUND")

        async def _call():
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.post(
                    "/api/memory/test-project/corroborate/batch",
                    json={"decision_ids": ["dec-1", "dec-999"]},
                )

        with patch(
            "core.corroboration.router._verify_project_exists",
        ), patch(
            "core.corroboration.router.corroborate_decision",
            side_effect=_side_effect,
        ):
            resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert body["summary"]["supported"] == 1
        assert body["summary"]["unverifiable"] == 1
        # Second result should have error field
        assert body["results"][1]["status"] == "unverifiable"
        assert "error" in body["results"][1]

    def test_router_batch_missing_body(self):
        """POST batch returns 422 when request body is missing."""
        # Arrange
        from httpx import ASGITransport, AsyncClient

        async def _call():
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.post("/api/memory/test-project/corroborate/batch")

        # Act
        resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 422
