"""Tests for core.search_router — Memory Search API."""

import pytest
from core.search_router import search_memory, _tokenize, _keyword_score


def _decision(text, ts="2026-01-01T00:00:00Z", context=""):
    return {"decision": text, "timestamp": ts, "context": context}


def _memory(decisions=None, sessions=None, patterns=None):
    return {
        "decisions": decisions or [],
        "session_history": sessions or [],
        "patterns": patterns or [],
    }


class TestTokenize:
    def test_basic(self):
        tokens = _tokenize("What did we decide about auth?")
        assert "decide" in tokens
        assert "auth" in tokens
        assert "what" not in tokens  # stopword

    def test_empty(self):
        assert _tokenize("") == set()

    def test_stopwords(self):
        tokens = _tokenize("the a an is are")
        assert tokens == set()


class TestKeywordScore:
    def test_full_match(self):
        score = _keyword_score({"fastapi", "backend"}, "Use FastAPI for backend")
        assert score == 1.0

    def test_partial_match(self):
        score = _keyword_score({"fastapi", "docker"}, "Use FastAPI for backend")
        assert score == 0.5

    def test_no_match(self):
        score = _keyword_score({"docker", "kubernetes"}, "Use FastAPI for backend")
        assert score == 0.0

    def test_empty_query(self):
        assert _keyword_score(set(), "anything") == 0.0


class TestSearchMemory:
    def test_finds_decisions(self):
        memory = _memory(decisions=[
            _decision("Use FastAPI for the backend"),
            _decision("Use React for frontend"),
        ])
        results = search_memory(memory, "FastAPI backend")
        assert len(results) >= 1
        assert results[0]["type"] == "decision"

    def test_finds_sessions(self):
        memory = _memory(sessions=[
            {"summary": "Set up authentication with JWT", "date": "2026-01-01"},
        ])
        results = search_memory(memory, "authentication JWT")
        assert len(results) >= 1
        assert results[0]["type"] == "session"

    def test_finds_patterns(self):
        memory = _memory(patterns=[
            {"name": "category:backend", "count": 5, "last_seen": "2026-01-01"},
        ])
        results = search_memory(memory, "backend")
        assert len(results) >= 1
        assert results[0]["type"] == "pattern"

    def test_empty_query(self):
        results = search_memory(_memory(), "")
        assert results == []

    def test_no_match(self):
        memory = _memory(decisions=[_decision("Use FastAPI")])
        results = search_memory(memory, "kubernetes docker")
        assert results == []

    def test_limit(self):
        memory = _memory(decisions=[_decision(f"Decision {i}") for i in range(20)])
        results = search_memory(memory, "decision", limit=5)
        assert len(results) <= 5

    def test_sorted_by_score(self):
        memory = _memory(decisions=[
            _decision("Use FastAPI for backend API"),
            _decision("Something unrelated"),
        ])
        results = search_memory(memory, "FastAPI API backend")
        if len(results) >= 2:
            assert results[0]["score"] >= results[1]["score"]
