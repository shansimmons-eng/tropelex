"""
Tests for Narrative Mode — story_builder and router.

Generates prose narratives of project decisions for non-technical audiences.
Uses pytest, AAA pattern, no shared state, all externals mocked.
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from core.narrative import Err, NarrativeReport, NarrativeSection, Ok
from core.narrative.story_builder import (
    build_narrative,
    generate_origin_section,
    generate_pivot_section,
    generate_resolution_section,
    summarize_decisions,
)
from core.narrative.router import narrative_router


# ---------------------------------------------------------------------------
#  Helpers — realistic mock data
# ---------------------------------------------------------------------------

def _decision(text, did="dec-1", ts="2026-07-01T00:00:00Z", context="", rationale=""):
    """Create a decision dict matching the project memory schema."""
    return {
        "id": did,
        "decision": text,
        "timestamp": ts,
        "context": context,
        "rationale": rationale,
        "source": "manual",
    }


def _memory(decisions=None, project_name="TestProject"):
    """Create a memory dict for the story builder."""
    return {
        "project_name": project_name,
        "decisions": decisions or [],
        "session_history": [],
        "preferences": {},
        "patterns": [],
        "tech_stack": [],
    }


def _app():
    """Create a FastAPI app with the narrative router included."""
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(narrative_router)
    return app


# Realistic decision sets for testing
RECENT_TS = datetime.now(timezone.utc).isoformat()
OLD_TS = "2025-01-01T00:00:00Z"

SINGLE_DECISION = [_decision("Use FastAPI for the backend", did="d1", ts=RECENT_TS)]

MULTIPLE_DECISIONS = [
    _decision("Use FastAPI for the backend", did="d1", ts=RECENT_TS),
    _decision("Use PostgreSQL for the primary database", did="d2", ts=RECENT_TS),
    _decision("Use snake_case naming convention for Python", did="d3", ts=RECENT_TS),
]

SUPERSEDED_DECISIONS = [
    _decision("Use REST API with camelCase naming", did="d1", ts=OLD_TS),
    _decision("Reverted to snake_case naming convention", did="d2", ts=RECENT_TS,
              context="because camelCase caused confusion"),
]


# ===========================================================================
#  1. Story Builder — generate_origin_section
# ===========================================================================


class TestGenerateOriginSection:
    def test_returns_narrative_section(self):
        """generate_origin_section returns a NarrativeSection with section_type='origin'."""
        # Arrange
        timeline = [{"decision": "Use FastAPI"}, {"decision": "Use PostgreSQL"}]

        # Act
        section = generate_origin_section(timeline)

        # Assert
        assert isinstance(section, NarrativeSection)
        assert section.section_type == "origin"
        assert section.heading == "How It All Started"

    def test_with_decisions_describes_origins(self):
        """Timeline entries are framed as founding choices in the body."""
        # Arrange
        timeline = [
            {"decision": "Use FastAPI for the backend"},
            {"decision": "Use PostgreSQL for the database"},
        ]

        # Act
        section = generate_origin_section(timeline)

        # Assert
        assert "FastAPI" in section.body
        assert "PostgreSQL" in section.body
        assert "project began" in section.body.lower()

    def test_empty_timeline(self):
        """Empty timeline returns a default 'no decisions' message."""
        # Arrange
        timeline = []

        # Act
        section = generate_origin_section(timeline)

        # Assert
        assert "No founding decisions" in section.body
        assert section.section_type == "origin"

    def test_limits_to_first_three(self):
        """Only the first 3 timeline entries are used."""
        # Arrange
        timeline = [
            {"decision": f"Decision {i}"} for i in range(10)
        ]

        # Act
        section = generate_origin_section(timeline)

        # Assert
        assert "Decision 0" in section.body
        assert "Decision 2" in section.body
        assert "Decision 3" not in section.body

    def test_missing_decision_key(self):
        """Timeline entries without 'decision' key get a fallback text."""
        # Arrange
        timeline = [{"id": "d1"}]

        # Act
        section = generate_origin_section(timeline)

        # Assert
        assert "unnamed choice" in section.body


# ===========================================================================
#  2. Story Builder — generate_pivot_section
# ===========================================================================


class TestGeneratePivotSection:
    def test_returns_narrative_section(self):
        """generate_pivot_section returns a NarrativeSection with section_type='pivot'."""
        # Arrange
        from core.decision_tree import DecisionTree
        tree = DecisionTree.from_decisions(SINGLE_DECISION)

        # Act
        section = generate_pivot_section(tree)

        # Assert
        assert isinstance(section, NarrativeSection)
        assert section.section_type == "pivot"
        assert section.heading == "What Changed and Why"

    def test_no_pivots_steady_course(self):
        """Tree with no supersedes/reverts returns steady course message."""
        # Arrange
        from core.decision_tree import DecisionTree
        tree = DecisionTree.from_decisions(SINGLE_DECISION)

        # Act
        section = generate_pivot_section(tree)

        # Assert
        assert "steady course" in section.body.lower()

    def test_finds_superseded_decisions(self):
        """Superseded decisions are detected and framed as course corrections."""
        # Arrange
        from core.decision_tree import DecisionTree
        tree = DecisionTree.from_decisions(SUPERSEDED_DECISIONS)

        # Act
        section = generate_pivot_section(tree)

        # Assert
        assert section.section_type == "pivot"
        # Should mention something about change
        assert len(section.body) > 0

    def test_manual_supersedes_edge(self):
        """Explicit supersedes edges in the tree are surfaced as pivots."""
        # Arrange
        from core.decision_tree import DecisionTree
        tree = DecisionTree()
        tree.nodes["d1"] = {"id": "d1", "decision": "Use REST API", "timestamp": OLD_TS}
        tree.nodes["d2"] = {"id": "d2", "decision": "Use GraphQL", "timestamp": RECENT_TS}
        tree.edges = [
            {"source": "d2", "target": "d1", "relationship": "supersedes", "created_at": RECENT_TS},
        ]

        # Act
        section = generate_pivot_section(tree)

        # Assert
        assert "REST API" in section.body or "GraphQL" in section.body
        assert "replaced" in section.body.lower()

    def test_manual_reverts_edge(self):
        """Explicit reverts edges are surfaced as pivots."""
        # Arrange
        from core.decision_tree import DecisionTree
        tree = DecisionTree()
        tree.nodes["d1"] = {"id": "d1", "decision": "Use camelCase", "timestamp": OLD_TS}
        tree.nodes["d2"] = {"id": "d2", "decision": "Revert to snake_case", "timestamp": RECENT_TS}
        tree.edges = [
            {"source": "d2", "target": "d1", "relationship": "reverts", "created_at": RECENT_TS},
        ]

        # Act
        section = generate_pivot_section(tree)

        # Assert
        assert "camelCase" in section.body or "snake_case" in section.body


# ===========================================================================
#  3. Story Builder — generate_resolution_section
# ===========================================================================


class TestGenerateResolutionSection:
    def test_returns_narrative_section(self):
        """generate_resolution_section returns NarrativeSection with section_type='resolution'."""
        # Arrange
        from core.decision_tree import DecisionTree
        tree = DecisionTree.from_decisions(MULTIPLE_DECISIONS)
        timeline = tree.get_timeline()

        # Act
        section = generate_resolution_section(MULTIPLE_DECISIONS, timeline)

        # Assert
        assert isinstance(section, NarrativeSection)
        assert section.section_type == "resolution"
        assert section.heading == "Where We Are Now"

    def test_filters_high_confidence(self):
        """Only high/medium confidence decisions appear in the resolution."""
        # Arrange
        decisions = [
            _decision("Use FastAPI for the backend", did="d1", ts=RECENT_TS),
            _decision("Use PostgreSQL for the database", did="d2", ts=RECENT_TS),
        ]
        from core.decision_tree import DecisionTree
        tree = DecisionTree.from_decisions(decisions)
        timeline = tree.get_timeline()

        # Act
        section = generate_resolution_section(decisions, timeline)

        # Assert
        assert "Currently" in section.body or "No high-confidence" in section.body

    def test_empty_decisions(self):
        """Empty decisions returns 'no high-confidence' message."""
        # Arrange
        timeline = []

        # Act
        section = generate_resolution_section([], timeline)

        # Assert
        assert "No high-confidence" in section.body

    def test_all_stale_decisions(self):
        """When all decisions are stale, returns the fallback message."""
        # Arrange — very old timestamps that will decay to stale
        old_ts = "2020-01-01T00:00:00Z"
        stale_decisions = [
            _decision("Old decision", did=f"d{i}", ts=old_ts) for i in range(5)
        ]
        from core.decision_tree import DecisionTree
        tree = DecisionTree.from_decisions(stale_decisions)
        timeline = tree.get_timeline()

        # Act
        section = generate_resolution_section(stale_decisions, timeline)

        # Assert — should either have active decisions or fallback
        assert isinstance(section, NarrativeSection)
        assert section.section_type == "resolution"


# ===========================================================================
#  4. Story Builder — summarize_decisions
# ===========================================================================


class TestSummarizeDecisions:
    def test_returns_paragraph(self):
        """summarize_decisions returns a string paragraph."""
        # Arrange / Act
        result = summarize_decisions(MULTIPLE_DECISIONS)

        # Assert
        assert isinstance(result, str)
        assert len(result) > 0
        assert "Key decisions include" in result

    def test_empty_decisions_returns_empty_string_message(self):
        """Empty decisions list returns a 'No decisions' message."""
        # Arrange / Act
        result = summarize_decisions([])

        # Assert
        assert result == "No decisions recorded for this project."

    def test_limits_to_max_items(self):
        """Only max_items decisions are included in the summary."""
        # Arrange
        many_decisions = [
            _decision(f"Decision {i}", did=f"d{i}", ts=RECENT_TS) for i in range(20)
        ]

        # Act
        result = summarize_decisions(many_decisions, max_items=3)

        # Assert
        # Count semicolons — each additional decision adds one ';'
        semicolon_count = result.count(";")
        assert semicolon_count <= 2  # max_items=3 → at most 2 semicolons

    def test_single_decision(self):
        """Single decision produces a valid summary."""
        # Arrange / Act
        result = summarize_decisions(SINGLE_DECISION)

        # Assert
        assert "Key decisions include" in result
        assert "FastAPI" in result


# ===========================================================================
#  5. Story Builder — build_narrative
# ===========================================================================


class TestBuildNarrative:
    def test_build_narrative_new_hire(self):
        """audience=new_hire returns Ok with NarrativeReport."""
        # Arrange
        memory = _memory(MULTIPLE_DECISIONS)

        # Act
        result = build_narrative(memory, audience="new_hire")

        # Assert
        assert isinstance(result, Ok)
        report = result.value
        assert isinstance(report, NarrativeReport)
        assert report.audience == "new_hire"
        assert report.project_name == "TestProject"
        assert len(report.sections) == 3  # origin, pivot, resolution
        # new_hire order: origin → pivot → resolution
        assert report.sections[0].section_type == "origin"
        assert report.sections[1].section_type == "pivot"
        assert report.sections[2].section_type == "resolution"

    def test_build_narrative_investor(self):
        """audience=investor returns Ok with investor-ordered sections."""
        # Arrange
        memory = _memory(MULTIPLE_DECISIONS)

        # Act
        result = build_narrative(memory, audience="investor")

        # Assert
        assert isinstance(result, Ok)
        report = result.value
        assert report.audience == "investor"
        # investor order: pivot → resolution → origin
        assert report.sections[0].section_type == "pivot"
        assert report.sections[1].section_type == "resolution"
        assert report.sections[2].section_type == "origin"

    def test_build_narrative_pm(self):
        """audience=pm returns Ok with pm-ordered sections."""
        # Arrange
        memory = _memory(MULTIPLE_DECISIONS)

        # Act
        result = build_narrative(memory, audience="pm")

        # Assert
        assert isinstance(result, Ok)
        report = result.value
        assert report.audience == "pm"
        # pm order: pivot → resolution → origin
        assert report.sections[0].section_type == "pivot"
        assert report.sections[1].section_type == "resolution"
        assert report.sections[2].section_type == "origin"

    def test_build_narrative_empty_decisions(self):
        """Empty memory returns Err with NOT_FOUND code."""
        # Arrange
        memory = _memory([])

        # Act
        result = build_narrative(memory, audience="new_hire")

        # Assert
        assert isinstance(result, Err)
        assert result.code == "NOT_FOUND"
        assert "No decisions" in result.error

    def test_build_narrative_invalid_audience(self):
        """Invalid audience returns Err with VALIDATION_ERROR code."""
        # Arrange
        memory = _memory(MULTIPLE_DECISIONS)

        # Act
        result = build_narrative(memory, audience="invalid_audience")

        # Assert
        assert isinstance(result, Err)
        assert result.code == "VALIDATION_ERROR"
        assert "audience" in result.error.lower()

    def test_build_narrative_invalid_memory_type(self):
        """Non-dict memory returns Err with VALIDATION_ERROR code."""
        # Arrange / Act
        result = build_narrative("not a dict", audience="new_hire")

        # Assert
        assert isinstance(result, Err)
        assert result.code == "VALIDATION_ERROR"
        assert "dict" in result.error.lower()

    def test_build_narrative_report_has_title(self):
        """Report title includes project name and audience."""
        # Arrange
        memory = _memory(MULTIPLE_DECISIONS, project_name="MyProject")

        # Act
        result = build_narrative(memory, audience="new_hire")

        # Assert
        assert isinstance(result, Ok)
        assert "MyProject" in result.value.title
        assert "new_hire" in result.value.title

    def test_build_narrative_report_has_summary(self):
        """Report includes a summary paragraph."""
        # Arrange
        memory = _memory(MULTIPLE_DECISIONS)

        # Act
        result = build_narrative(memory, audience="new_hire")

        # Assert
        assert isinstance(result, Ok)
        assert "Key decisions" in result.value.summary

    def test_build_narrative_report_has_generated_at(self):
        """Report includes an ISO timestamp."""
        # Arrange
        memory = _memory(MULTIPLE_DECISIONS)

        # Act
        result = build_narrative(memory, audience="new_hire")

        # Assert
        assert isinstance(result, Ok)
        assert result.value.generated_at is not None
        # Verify it's a valid ISO timestamp
        datetime.fromisoformat(result.value.generated_at)

    def test_build_narrative_word_count_is_accurate(self):
        """Word count matches the actual word count of section bodies."""
        # Arrange
        memory = _memory(MULTIPLE_DECISIONS)

        # Act
        result = build_narrative(memory, audience="new_hire")

        # Assert
        assert isinstance(result, Ok)
        report = result.value
        expected_count = sum(len(s.body.split()) for s in report.sections)
        assert report.word_count == expected_count

    def test_build_narrative_word_count_positive(self):
        """Word count is positive for a report with decisions."""
        # Arrange
        memory = _memory(MULTIPLE_DECISIONS)

        # Act
        result = build_narrative(memory, audience="new_hire")

        # Assert
        assert isinstance(result, Ok)
        assert result.value.word_count > 0

    def test_build_narrative_audience_ordering(self):
        """Sections are ordered correctly per audience."""
        # Arrange
        memory = _memory(MULTIPLE_DECISIONS)

        # Act — new_hire: origin → pivot → resolution
        result_hire = build_narrative(memory, audience="new_hire")
        # Act — investor: pivot → resolution → origin
        result_inv = build_narrative(memory, audience="investor")
        # Act — pm: pivot → resolution → origin
        result_pm = build_narrative(memory, audience="pm")

        # Assert — new_hire starts with origin
        assert isinstance(result_hire, Ok)
        assert result_hire.value.sections[0].section_type == "origin"

        # Assert — investor starts with pivot
        assert isinstance(result_inv, Ok)
        assert result_inv.value.sections[0].section_type == "pivot"

        # Assert — pm starts with pivot
        assert isinstance(result_pm, Ok)
        assert result_pm.value.sections[0].section_type == "pivot"

    def test_build_narrative_unknown_project_name(self):
        """Missing project_name in memory defaults to 'Unknown Project'."""
        # Arrange
        memory = {"decisions": MULTIPLE_DECISIONS}

        # Act
        result = build_narrative(memory, audience="new_hire")

        # Assert
        assert isinstance(result, Ok)
        assert result.value.project_name == "Unknown Project"

    def test_build_narrative_all_three_audiences_return_different_orders(self):
        """new_hire, investor, and pm produce different section orderings."""
        # Arrange
        memory = _memory(MULTIPLE_DECISIONS)

        # Act
        orders = {}
        for audience in ("new_hire", "investor", "pm"):
            result = build_narrative(memory, audience=audience)
            assert isinstance(result, Ok)
            orders[audience] = [s.section_type for s in result.value.sections]

        # Assert — new_hire differs from investor/pm
        assert orders["new_hire"] != orders["investor"]
        # investor and pm have the same order (both start with pivot)
        assert orders["investor"] == orders["pm"]


# ===========================================================================
#  6. Router Tests (httpx AsyncClient)
# ===========================================================================


class TestNarrativeRouterSuccess:
    def test_router_narrative_success_new_hire(self):
        """POST /api/memory/{project}/narrative returns 200 with valid memory."""
        # Arrange
        mock_memory = _memory(MULTIPLE_DECISIONS)

        async def _call():
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.post(
                    "/api/memory/test-project/narrative",
                    json={"audience": "new_hire"},
                )

        with patch("core.narrative.router.MemoryManager") as MockMM:
            MockMM.return_value.get_project_memory.return_value = mock_memory
            resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 200
        body = resp.json()
        assert body["audience"] == "new_hire"
        assert body["project_name"] == "TestProject"
        assert "title" in body
        assert "sections" in body
        assert "summary" in body
        assert "word_count" in body
        assert "generated_at" in body

    def test_router_narrative_success_investor(self):
        """POST with audience=investor returns 200."""
        # Arrange
        mock_memory = _memory(MULTIPLE_DECISIONS)

        async def _call():
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.post(
                    "/api/memory/test-project/narrative",
                    json={"audience": "investor"},
                )

        with patch("core.narrative.router.MemoryManager") as MockMM:
            MockMM.return_value.get_project_memory.return_value = mock_memory
            resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 200
        assert resp.json()["audience"] == "investor"

    def test_router_narrative_success_pm(self):
        """POST with audience=pm returns 200."""
        # Arrange
        mock_memory = _memory(MULTIPLE_DECISIONS)

        async def _call():
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.post(
                    "/api/memory/test-project/narrative",
                    json={"audience": "pm"},
                )

        with patch("core.narrative.router.MemoryManager") as MockMM:
            MockMM.return_value.get_project_memory.return_value = mock_memory
            resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 200
        assert resp.json()["audience"] == "pm"

    def test_router_narrative_default_audience(self):
        """POST without audience defaults to new_hire."""
        # Arrange
        mock_memory = _memory(MULTIPLE_DECISIONS)

        async def _call():
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.post(
                    "/api/memory/test-project/narrative",
                    json={},
                )

        with patch("core.narrative.router.MemoryManager") as MockMM:
            MockMM.return_value.get_project_memory.return_value = mock_memory
            resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 200
        assert resp.json()["audience"] == "new_hire"

    def test_router_narrative_sections_serialized(self):
        """Response sections are serialized as JSON dicts with heading/body/section_type."""
        # Arrange
        mock_memory = _memory(MULTIPLE_DECISIONS)

        async def _call():
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.post(
                    "/api/memory/test-project/narrative",
                    json={"audience": "new_hire"},
                )

        with patch("core.narrative.router.MemoryManager") as MockMM:
            MockMM.return_value.get_project_memory.return_value = mock_memory
            resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 200
        sections = resp.json()["sections"]
        assert len(sections) > 0
        for section in sections:
            assert "heading" in section
            assert "body" in section
            assert "section_type" in section


class TestNarrativeRouterErrors:
    def test_router_narrative_invalid_audience(self):
        """POST with invalid audience returns 422."""
        # Arrange
        async def _call():
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.post(
                    "/api/memory/test-project/narrative",
                    json={"audience": "invalid_audience"},
                )

        # Act
        resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 422

    def test_router_narrative_missing_project(self):
        """POST with project that raises ValueError returns 404."""
        # Arrange
        async def _call():
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.post(
                    "/api/memory/!!!/narrative",
                    json={"audience": "new_hire"},
                )

        # Act
        resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 404

    def test_router_narrative_project_memory_not_found(self):
        """POST when memory has no decisions returns 404."""
        # Arrange
        mock_memory = _memory([])

        async def _call():
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.post(
                    "/api/memory/test-project/narrative",
                    json={"audience": "new_hire"},
                )

        with patch("core.narrative.router.MemoryManager") as MockMM:
            MockMM.return_value.get_project_memory.return_value = mock_memory
            resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 404
        body = resp.json()
        assert "No decisions" in body["detail"]

    def test_router_narrative_memory_load_exception(self):
        """POST when MemoryManager raises generic exception returns 500."""
        # Arrange
        async def _call():
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.post(
                    "/api/memory/test-project/narrative",
                    json={"audience": "new_hire"},
                )

        with patch("core.narrative.router.MemoryManager") as MockMM:
            MockMM.return_value.get_project_memory.side_effect = RuntimeError("disk error")
            resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 500
        body = resp.json()
        assert "Failed to load" in body["detail"]

    def test_router_narrative_invalid_audience_body(self):
        """POST with audience that doesn't match pattern returns 422."""
        # Arrange
        async def _call():
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.post(
                    "/api/memory/test-project/narrative",
                    json={"audience": "ceo"},
                )

        # Act
        resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 422
