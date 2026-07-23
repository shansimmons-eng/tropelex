"""Tests for the synthesis driver — combined research pipeline."""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "core" / "last30days"))

from synthesize_run import (
    _brave_search,
    _academic_search,
    _fetch_url,
    _extract_readable_text,
    _format_web_evidence,
    _gather_web_research,
    _llm_config,
    _extract,
    _EVIDENCE_RE,
)


# ─── Brave Search ───────────────────────────────────────────────────────


class TestBraveSearch:
    def test_returns_results_on_success(self):
        """Brave search returns parsed results on 200 response."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"web":{"results":[{"title":"Test","url":"https://example.com","description":"A test result"}]}}'
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            results = _brave_search("test query", "fake-key", count=1)
            assert len(results) == 1
            assert results[0]["title"] == "Test"
            assert results[0]["url"] == "https://example.com"

    def test_returns_empty_on_failure(self):
        """Brave search returns empty list on network error."""
        with patch("urllib.request.urlopen", side_effect=Exception("network error")):
            results = _brave_search("test", "fake-key")
            assert results == []


# ─── Academic Search (Semantic Scholar) ─────────────────────────────────


class TestAcademicSearch:
    def test_returns_papers_on_success(self):
        """Academic search returns parsed papers on 200 response."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "data": [
                {
                    "title": "Test Paper",
                    "year": 2026,
                    "abstract": "This is a test abstract.",
                    "url": "https://arxiv.org/abs/12345",
                    "citationCount": 42,
                }
            ]
        }).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            papers = _academic_search("test query", limit=1)
            assert len(papers) == 1
            assert papers[0]["title"] == "Test Paper"
            assert papers[0]["citations"] == 42

    def test_returns_empty_on_failure(self):
        """Academic search returns empty list on error."""
        with patch("urllib.request.urlopen", side_effect=Exception("rate limited")):
            papers = _academic_search("test")
            assert papers == []


# ─── Page extraction ────────────────────────────────────────────────────


class TestPageExtraction:
    def test_extracts_readable_text(self):
        """HTML extraction strips tags, scripts, and collapses whitespace."""
        html = """
        <html><head><style>body { color: red; }</style></head>
        <body>
            <h1>Title</h1>
            <p>Hello world</p>
            <script>alert('xss')</script>
            <p>Second paragraph</p>
        </body></html>
        """
        text = _extract_readable_text(html)
        assert "alert" not in text, "Script content should be stripped"
        assert "color: red" not in text, "Style content should be stripped"
        assert "Title" in text
        assert "Hello world" in text
        assert "Second paragraph" in text

    def test_fetch_url_returns_none_for_non_html(self):
        """fetch_url returns None for non-HTML content types."""
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "image/png"}
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = _fetch_url("https://example.com/image.png")
            assert result is None


# ─── Evidence formatting ────────────────────────────────────────────────


class TestFormatWebEvidence:
    def test_formats_brave_results(self):
        """Brave results are formatted with title, URL, description."""
        brave = [{"title": "Test", "url": "https://example.com", "description": "A test page"}]
        result = _format_web_evidence(brave, [], {})
        assert "WEB SEARCH RESULTS" in result
        assert "Test" in result
        assert "https://example.com" in result

    def test_formats_academic_papers(self):
        """Academic papers are formatted with title, year, citations."""
        papers = [{"title": "Test Paper", "year": 2026, "abstract": "Test abstract", "url": "https://arxiv.org/abs/123", "citations": 10}]
        result = _format_web_evidence([], papers, {})
        assert "ACADEMIC PAPERS" in result
        assert "Test Paper" in result
        assert "2026" in result

    def test_formats_page_content(self):
        """Page content is formatted with title and extracted text."""
        brave = [{"title": "Page", "url": "https://example.com", "description": "desc"}]
        pages = {0: "Full page content here"}
        result = _format_web_evidence(brave, [], pages)
        assert "FULL PAGE CONTENT" in result
        assert "Full page content here" in result

    def test_empty_inputs_returns_empty_string(self):
        """Empty inputs produce empty output."""
        result = _format_web_evidence([], [], {})
        assert result.strip() == ""


# ─── LLM config resolution ─────────────────────────────────────────────


class TestLLMConfig:
    def test_openai_priority(self):
        """OpenAI key takes priority over xAI."""
        config = {"OPENAI_API_KEY": "sk-test", "XAI_API_KEY": "xai-test"}
        result = _llm_config(config)
        assert result is not None
        assert "openai.com" in result[0]
        assert result[1] == "sk-test"

    def test_xai_fallback(self):
        """xAI key used when OpenAI not available."""
        config = {"XAI_API_KEY": "xai-test"}
        result = _llm_config(config)
        assert result is not None
        assert "x.ai" in result[0]

    def test_no_keys_returns_none(self):
        """No keys configured returns None."""
        config = {}
        result = _llm_config(config)
        assert result is None


# ─── Evidence extraction ────────────────────────────────────────────────


class TestEvidenceExtraction:
    def test_extracts_evidence_block(self):
        """Evidence block is extracted from HTML comment markers."""
        text = "before\n<!-- EVIDENCE FOR SYNTHESIS: read this -->\nactual evidence\n<!-- END EVIDENCE FOR SYNTHESIS -->\nafter"
        result = _extract(_EVIDENCE_RE, text)
        assert "actual evidence" in result

    def test_returns_empty_when_no_markers(self):
        """Returns empty string when markers not found."""
        result = _extract(_EVIDENCE_RE, "no markers here")
        assert result == ""


# Need json for the academic search mock
import json
