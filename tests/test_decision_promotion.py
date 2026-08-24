"""Tests for core/decision_promotion.py (wishlist #82) -- candidate decision
extraction from research reports, with computed (not LLM-invented)
confidence. Mocks core.llm.chat the same way tests/test_session_insights.py
does for #19.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from core.decision_promotion import (
    _compute_confidence,
    _parse_candidates,
    extract_candidate_decisions,
)


def _citation(id="c1", url="https://example.com/a", source_type="web_researcher_mcp"):
    return {"id": id, "url": url, "title": "Example", "source_type": source_type}


class TestComputeConfidence:
    def test_no_citations_is_zero(self):
        assert _compute_confidence([]) == 0.0

    def test_one_citation_is_low(self):
        score = _compute_confidence([_citation()])
        assert 0.0 < score < 0.5

    def test_four_or_more_citations_saturates_count_component(self):
        cites = [_citation(id=str(i), url=f"https://example.com/{i}") for i in range(5)]
        score = _compute_confidence(cites)
        assert score >= 0.9

    def test_source_type_diversity_boosts_score(self):
        same_type = [_citation(id="1", url="https://a.com"), _citation(id="2", url="https://b.com")]
        diverse_type = [
            _citation(id="1", url="https://a.com", source_type="web_researcher_mcp"),
            _citation(id="2", url="https://b.com", source_type="google_deep_research"),
        ]
        assert _compute_confidence(diverse_type) > _compute_confidence(same_type)

    def test_never_exceeds_one(self):
        cites = [_citation(id=str(i), url=f"https://x.com/{i}", source_type=f"type{i % 2}") for i in range(20)]
        assert _compute_confidence(cites) <= 1.0


class TestParseCandidates:
    def _citations_by_url(self):
        return {
            "https://example.com/a": {"id": "c1", "url": "https://example.com/a", "source_type": "web_researcher_mcp"},
            "https://example.com/b": {"id": "c2", "url": "https://example.com/b", "source_type": "google_deep_research"},
        }

    def test_valid_response_parses(self):
        raw = json.dumps([{
            "decision": "Use Postgres for the primary database",
            "context": "Better relational support for the data model",
            "supporting_citation_urls": ["https://example.com/a", "https://example.com/b"],
        }])
        result = _parse_candidates(raw, self._citations_by_url())
        assert len(result) == 1
        assert result[0]["decision"] == "Use Postgres for the primary database"
        assert set(result[0]["citation_ids"]) == {"c1", "c2"}
        assert result[0]["confidence"] > 0

    def test_malformed_json_returns_empty(self):
        assert _parse_candidates("not json at all {{{", self._citations_by_url()) == []

    def test_non_list_json_returns_empty(self):
        assert _parse_candidates(json.dumps({"decision": "not a list"}), self._citations_by_url()) == []

    def test_empty_array_returns_empty(self):
        assert _parse_candidates("[]", self._citations_by_url()) == []

    def test_drops_items_missing_decision_text(self):
        raw = json.dumps([{"context": "no decision field"}, {"decision": ""}])
        assert _parse_candidates(raw, self._citations_by_url()) == []

    def test_invented_citation_url_is_dropped_not_trusted(self):
        raw = json.dumps([{
            "decision": "Some decision",
            "context": "",
            "supporting_citation_urls": ["https://not-a-real-citation.com"],
        }])
        result = _parse_candidates(raw, self._citations_by_url())
        assert len(result) == 1
        assert result[0]["citation_ids"] == []
        assert result[0]["confidence"] == 0.0

    def test_non_dict_items_in_array_are_skipped(self):
        raw = json.dumps(["just a string", {"decision": "real one", "supporting_citation_urls": []}])
        result = _parse_candidates(raw, self._citations_by_url())
        assert len(result) == 1
        assert result[0]["decision"] == "real one"


class TestExtractCandidateDecisions:
    @pytest.mark.asyncio
    async def test_empty_report_returns_empty_without_calling_llm(self):
        with patch("core.llm.chat", new=AsyncMock(return_value="[]")) as mock_chat:
            result = await extract_candidate_decisions("", [_citation()])
        assert result == []
        mock_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_llm_backend_returns_empty(self):
        with patch("core.llm.chat", new=AsyncMock(return_value=None)):
            result = await extract_candidate_decisions("Some report text", [_citation()])
        assert result == []

    @pytest.mark.asyncio
    async def test_successful_extraction(self):
        raw = json.dumps([{
            "decision": "Use SQLite for local dev",
            "context": "Simpler setup",
            "supporting_citation_urls": ["https://example.com/a"],
        }])
        with patch("core.llm.chat", new=AsyncMock(return_value=raw)):
            result = await extract_candidate_decisions(
                "A report recommending SQLite for local development.",
                [_citation(id="c1", url="https://example.com/a")],
            )
        assert len(result) == 1
        assert result[0]["citation_ids"] == ["c1"]

    @pytest.mark.asyncio
    async def test_passes_project_through_to_llm_chat(self):
        mock_chat = AsyncMock(return_value="[]")
        with patch("core.llm.chat", new=mock_chat):
            await extract_candidate_decisions("report text", [_citation()], project="my-project")
        assert mock_chat.call_args.kwargs["project"] == "my-project"
