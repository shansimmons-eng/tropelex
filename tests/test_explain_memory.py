"""
Tests for Explainable Memory — core.explain module.

Covers:
  - Explainer unit tests (keyword matching, causal chains, supersession,
    downstream impact, provenance, source citations, NL answer generation,
    full explain_why integration)
  - Router integration tests (httpx AsyncClient)

All tests follow AAA pattern, use realistic mock data, and are fully
independent with no shared state.
"""

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

import pytest

from core.explain.explainer import (
    ExplanationReport,
    _build_causal_chain,
    _build_source_citations,
    _build_supersession_chain,
    _compute_downstream_impact,
    _extract_provenance,
    _find_best_matching_decision,
    _generate_natural_language_answer,
    explain_why,
)
from core.decision_tree import DecisionTree


# ---------------------------------------------------------------------------
#  Fixtures — realistic decision data with causal chains
# ---------------------------------------------------------------------------

def _ts(days_offset: int = 0) -> str:
    """Return an ISO timestamp offset from a fixed base date."""
    base = datetime(2026, 6, 1, tzinfo=timezone.utc)
    from datetime import timedelta
    return (base + timedelta(days=days_offset)).isoformat()


# Root decision: chose PostgreSQL over SQLite
DECISION_ROOT: dict[str, Any] = {
    "id": "dec_pg_root",
    "decision": "Use PostgreSQL for the main database",
    "context": "SQLite cannot handle concurrent writes at scale",
    "author": "alice",
    "timestamp": _ts(0),
    "source": "manual",
}

# Follow-up: added connection pooling because of PostgreSQL
DECISION_POOLING: dict[str, Any] = {
    "id": "dec_pooling",
    "decision": "Add pgBouncer connection pooling",
    "context": "Because PostgreSQL connections are expensive",
    "author": "bob",
    "timestamp": _ts(10),
    "source": "git",
}

# Supersession: replaced pgBouncer with built-in pooling
DECISION_POOLING_V2: dict[str, Any] = {
    "id": "dec_pooling_v2",
    "decision": "Replace pgBouncer with built-in connection pooling",
    "context": "PostgreSQL 16 added native connection pooling",
    "author": "alice",
    "timestamp": _ts(30),
    "source": "git",
}

# Unrelated decision for negative testing
DECISION_UNRELATED: dict[str, Any] = {
    "id": "dec_ui_theme",
    "decision": "Switch frontend to dark mode theme",
    "context": "User preference survey",
    "author": "charlie",
    "timestamp": _ts(5),
    "source": "manual",
}


def _build_tree_with_chain() -> DecisionTree:
    """Build a DecisionTree with a causal chain:
    PostgreSQL → pgBouncer → pgBouncer v2 (supersession).
    """
    tree = DecisionTree()

    # Manually add nodes and edges to have full control over the graph
    tree.nodes["dec_pg_root"] = {
        "id": "dec_pg_root",
        "decision": DECISION_ROOT["decision"],
        "context": DECISION_ROOT["context"],
        "rationale": "",
        "timestamp": DECISION_ROOT["timestamp"],
        "source": "manual",
        "categories": [],
        "is_revert": False,
        "reverts": None,
        "edges": [],
    }
    tree.nodes["dec_pooling"] = {
        "id": "dec_pooling",
        "decision": DECISION_POOLING["decision"],
        "context": DECISION_POOLING["context"],
        "rationale": "",
        "timestamp": DECISION_POOLING["timestamp"],
        "source": "git",
        "categories": [],
        "is_revert": False,
        "reverts": None,
        "edges": [],
    }
    tree.nodes["dec_pooling_v2"] = {
        "id": "dec_pooling_v2",
        "decision": DECISION_POOLING_V2["decision"],
        "context": DECISION_POOLING_V2["context"],
        "rationale": "",
        "timestamp": DECISION_POOLING_V2["timestamp"],
        "source": "git",
        "categories": [],
        "is_revert": False,
        "reverts": None,
        "edges": [],
    }

    # Edge: pooling caused by root (PostgreSQL)
    edge_pooling_caused = {
        "source": "dec_pooling",
        "target": "dec_pg_root",
        "relationship": "caused_by",
        "created_at": _ts(10),
    }
    tree.edges.append(edge_pooling_caused)
    tree.nodes["dec_pooling"]["edges"].append(edge_pooling_caused)

    # Edge: pooling_v2 supersedes pooling
    edge_v2_supersedes = {
        "source": "dec_pooling_v2",
        "target": "dec_pooling",
        "relationship": "supersedes",
        "created_at": _ts(30),
    }
    tree.edges.append(edge_v2_supersedes)
    tree.nodes["dec_pooling_v2"]["edges"].append(edge_v2_supersedes)

    return tree


def _memory_with_chain() -> dict[str, Any]:
    """Memory dict matching the tree chain, with git history and sessions."""
    return {
        "decisions": [DECISION_ROOT, DECISION_POOLING, DECISION_POOLING_V2],
        "git_history": [
            {
                "message": "feat: add pgBouncer connection pooling",
                "date": _ts(10),
            },
            {
                "message": "refactor: replace pgBouncer with native pooling",
                "date": _ts(30),
            },
            {
                "message": "chore: update README",
                "date": _ts(15),
            },
        ],
        "session_history": [
            {
                "summary": "Discussed PostgreSQL connection pooling strategy",
                "timestamp": _ts(12),
            },
            {
                "summary": "Set up CI/CD pipeline",
                "timestamp": _ts(20),
            },
        ],
    }


# ===========================================================================
#  1. Explainer Tests
# ===========================================================================


class TestFindBestMatchingDecision:
    """Tests for _find_best_matching_decision keyword-overlap matcher."""

    def test_find_best_matching_decision_returns_best_match(self):
        """Keyword overlap selects the PostgreSQL decision over unrelated ones."""
        # Arrange
        decisions = [DECISION_ROOT, DECISION_POOLING, DECISION_UNRELATED]
        question = "Why did we choose PostgreSQL for the database?"

        # Act
        best = _find_best_matching_decision(question, decisions)

        # Assert
        assert best is not None
        assert best["id"] == "dec_pg_root"

    def test_find_best_matching_decision_returns_none_for_no_match(self):
        """Returns None when no decision shares keywords with the question."""
        # Arrange
        decisions = [DECISION_UNRELATED]
        question = "Why did we choose Kubernetes for deployment?"

        # Act
        best = _find_best_matching_decision(question, decisions)

        # Assert
        assert best is None


class TestBuildCausalChain:
    """Tests for _build_causal_chain ancestor traversal."""

    def test_build_causal_chain_returns_ancestors(self):
        """Walking ancestors of the pooling decision returns the root PostgreSQL decision."""
        # Arrange
        tree = _build_tree_with_chain()

        # Act
        chain = _build_causal_chain("dec_pooling", tree)

        # Assert
        assert len(chain) >= 1
        ancestor_ids = [c["decision"]["id"] for c in chain]
        assert "dec_pg_root" in ancestor_ids

    def test_build_causal_chain_empty_for_no_ancestors(self):
        """Root decisions with no incoming edges return an empty chain."""
        # Arrange
        tree = _build_tree_with_chain()

        # Act
        chain = _build_causal_chain("dec_pg_root", tree)

        # Assert
        assert chain == []


class TestBuildSupersessionChain:
    """Tests for _build_supersession_chain forward traversal."""

    def test_build_supersession_chain_returns_descendants(self):
        """The pooling decision is superseded by pooling_v2."""
        # Arrange
        tree = _build_tree_with_chain()

        # Act
        supersessions = _build_supersession_chain("dec_pooling", tree)

        # Assert
        assert len(supersessions) == 1
        assert supersessions[0]["decision"]["id"] == "dec_pooling_v2"
        assert supersessions[0]["relationship"] == "supersedes"

    def test_build_supersession_chain_empty_for_no_supersessions(self):
        """A decision that has never been superseded returns an empty chain."""
        # Arrange
        tree = _build_tree_with_chain()

        # Act
        supersessions = _build_supersession_chain("dec_pooling_v2", tree)

        # Assert
        assert supersessions == []


class TestComputeDownstreamImpact:
    """Tests for _compute_downstream_impact descendant enumeration."""

    def test_compute_downstream_impact_returns_descendants(self):
        """The root PostgreSQL decision has downstream decisions."""
        # Arrange
        tree = _build_tree_with_chain()

        # Act
        impact = _compute_downstream_impact("dec_pg_root", tree)

        # Assert
        assert len(impact) >= 1
        descendant_ids = [d["decision"]["id"] for d in impact]
        assert "dec_pooling" in descendant_ids


class TestExtractProvenance:
    """Tests for _extract_provenance confidence and author extraction."""

    def test_extract_provenance_returns_author_and_timestamp(self):
        """Provenance contains author, timestamp, and confidence fields."""
        # Arrange
        decision = dict(DECISION_ROOT)

        # Act
        provenance = _extract_provenance(decision)

        # Assert
        assert provenance["author"] == "alice"
        assert provenance["timestamp"] == _ts(0)
        assert "confidence_score" in provenance
        assert "confidence_tier" in provenance
        assert provenance["source"] == "manual"


class TestBuildSourceCitations:
    """Tests for _build_source_citations git reference matching."""

    def test_build_source_citations_finds_git_references(self):
        """Git commits mentioning pooling keywords are found as citations."""
        # Arrange
        memory = _memory_with_chain()

        # Act
        citations = _build_source_citations(DECISION_POOLING, memory)

        # Assert
        assert len(citations) >= 1
        types = {c["type"] for c in citations}
        assert "git_commit" in types
        # At least one citation should mention "pgBouncer" or "pooling"
        refs = " ".join(c["reference"] for c in citations)
        assert "pool" in refs.lower() or "pgbouncer" in refs.lower()


class TestGenerateNaturalLanguageAnswer:
    """Tests for _generate_natural_language_answer composition."""

    def test_generate_natural_language_answer_composes_explanation(self):
        """The answer includes the decision text, author, and context."""
        # Arrange
        causal_chain = [
            {"decision": DECISION_ROOT, "relationship": "caused_by", "depth": 1}
        ]
        supersession_chain = [
            {
                "decision": DECISION_POOLING_V2,
                "relationship": "supersedes",
                "timestamp": DECISION_POOLING_V2["timestamp"],
            }
        ]
        downstream_impact = [
            {"decision": DECISION_POOLING_V2, "relationship": "supersedes", "depth": 1}
        ]

        # Act
        answer = _generate_natural_language_answer(
            DECISION_POOLING, causal_chain, supersession_chain, downstream_impact
        )

        # Assert
        assert DECISION_POOLING["decision"] in answer
        assert DECISION_POOLING["author"] in answer
        assert DECISION_ROOT["decision"] in answer  # causal influence
        assert DECISION_POOLING_V2["decision"] in answer  # supersession
        assert "1 downstream decision" in answer


# ===========================================================================
#  2. explain_why Integration Tests
# ===========================================================================


class TestExplainWhyFullReport:
    """Tests for the main explain_why entry point with full chain data."""

    def test_explain_why_full_report(self):
        """A question matching a decision returns a complete ExplanationReport."""
        # Arrange
        memory = _memory_with_chain()
        tree = _build_tree_with_chain()
        question = "Why did we add pgBouncer connection pooling?"

        # Act
        report = explain_why(question, memory, tree)

        # Assert
        assert isinstance(report, ExplanationReport)
        assert report.question == question
        assert report.answer != ""
        assert report.confidence > 0.0
        # Should find a causal chain (pooling caused by root PostgreSQL)
        assert len(report.causal_chain) >= 1
        # Should find provenance
        assert "author" in report.provenance
        assert report.provenance["author"] in ("alice", "bob")
        # Should find source citations from git history
        assert len(report.source_citations) >= 1


class TestExplainWhyEmptyMemory:
    """Tests for explain_why with no decisions in memory."""

    def test_explain_why_empty_memory(self):
        """Empty memory returns a report with a 'no decisions' answer."""
        # Arrange
        memory: dict[str, Any] = {"decisions": []}
        question = "Why did we choose anything?"

        # Act
        report = explain_why(question, memory)

        # Assert
        assert isinstance(report, ExplanationReport)
        assert "no decisions" in report.answer.lower()
        assert report.causal_chain == []
        assert report.supersession_chain == []
        assert report.downstream_impact == []
        assert report.source_citations == []
        assert report.confidence == 0.0


class TestExplainWhyNoMatchingDecision:
    """Tests for explain_when question matches nothing in memory."""

    def test_explain_why_no_matching_decision(self):
        """A question with no keyword overlap returns a 'no match' answer."""
        # Arrange
        memory = {
            "decisions": [DECISION_ROOT],
            "git_history": [],
            "session_history": [],
        }
        question = "Why did we deploy to Mars?"

        # Act
        report = explain_why(question, memory)

        # Assert
        assert isinstance(report, ExplanationReport)
        assert "no matching" in report.answer.lower()
        assert report.causal_chain == []
        assert report.confidence == 0.0


# ===========================================================================
#  3. Router Tests (httpx AsyncClient)
# ===========================================================================


def _app():
    """Create a FastAPI app with the explain router included."""
    from fastapi import FastAPI
    app = FastAPI()
    from core.explain.router import explain_router
    app.include_router(explain_router)
    return app


class TestExplainEndpoint:
    """Integration tests for POST /api/memory/{project}/explain."""

    def test_explain_endpoint_returns_200(self):
        """Valid question against a known project returns 200 with report fields."""
        # Arrange
        mock_memory = _memory_with_chain()

        async def _call():
            from httpx import ASGITransport, AsyncClient
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.post(
                    "/api/memory/test-project/explain",
                    json={"question": "Why did we add pgBouncer connection pooling?"},
                )

        with patch("core.explain.router._load_memory", return_value=mock_memory):
            resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 200
        body = resp.json()
        assert "question" in body
        assert "answer" in body
        assert "causal_chain" in body
        assert "provenance" in body
        assert "supersession_chain" in body
        assert "downstream_impact" in body
        assert "source_citations" in body
        assert "confidence" in body
        assert body["question"] == "Why did we add pgBouncer connection pooling?"

    def test_explain_endpoint_returns_404_for_unknown_project(self):
        """Non-existent project returns 404 with detail message."""
        # Arrange
        from fastapi import HTTPException

        def _mock_load(project: str):
            raise HTTPException(status_code=404, detail=f"Project '{project}' not found")

        async def _call():
            from httpx import ASGITransport, AsyncClient
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                return await client.post(
                    "/api/memory/nonexistent-project/explain",
                    json={"question": "Why did we do X?"},
                )

        with patch("core.explain.router._load_memory", side_effect=_mock_load):
            resp = asyncio.run(_call())

        # Assert
        assert resp.status_code == 404
        body = resp.json()
        assert "not found" in body["detail"].lower()
