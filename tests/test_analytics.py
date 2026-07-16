"""Tests for core.analytics — Memory Analytics."""

import pytest
from core.analytics import (
    compute_analytics,
    _compute_usage_rates,
    _compute_growth_timeline,
    _compute_quality_metrics,
    _extract_top_categories,
    _generate_analytics_recommendations,
    _months_span,
    _extract_month,
)


def _decision(text, ts="2026-01-01T00:00:00Z"):
    return {"decision": text, "timestamp": ts, "context": ""}


def _session(summary, date="2026-01-01"):
    return {"summary": summary, "date": date}


def _memory(decisions=None, sessions=None, patterns=None):
    return {
        "decisions": decisions or [],
        "session_history": sessions or [],
        "patterns": patterns or [],
    }


class TestComputeAnalytics:
    def test_empty_memory(self):
        result = compute_analytics(_memory())
        assert result["usage"]["total_decisions"] == 0
        assert result["quality"]["avg_confidence"] == 0

    def test_with_data(self):
        memory = _memory(
            decisions=[_decision("Use FastAPI"), _decision("Use PostgreSQL")],
            sessions=[_session("Setup project")],
            patterns=[{"name": "category:backend", "count": 3}],
        )
        result = compute_analytics(memory)
        assert result["usage"]["total_decisions"] == 2
        assert result["usage"]["total_sessions"] == 1
        assert result["quality"]["avg_confidence"] > 0
        assert isinstance(result["top_categories"], list)
        assert isinstance(result["recommendations"], list)


class TestUsageRates:
    def test_rates(self):
        usage = _compute_usage_rates(
            [_decision("a"), _decision("b")],
            [_session("s1")],
            [{"name": "p1"}],
        )
        assert usage["total_decisions"] == 2
        assert usage["total_sessions"] == 1
        assert usage["total_patterns"] == 1
        assert usage["decisions_per_month"] > 0


class TestGrowthTimeline:
    def test_timeline(self):
        decisions = [_decision("a", "2026-01-15T00:00:00Z"), _decision("b", "2026-02-15T00:00:00Z")]
        sessions = [_session("s1", "2026-01-20")]
        growth = _compute_growth_timeline(decisions, sessions)
        assert len(growth["timeline"]) == 2
        assert growth["total_items"] == 3

    def test_empty(self):
        growth = _compute_growth_timeline([], [])
        assert growth["timeline"] == []
        assert growth["total_items"] == 0


class TestQualityMetrics:
    def test_empty(self):
        q = _compute_quality_metrics([])
        assert q["avg_confidence"] == 0

    def test_with_decisions(self):
        decisions = [_decision("Use FastAPI", "2026-06-01T00:00:00Z")]
        q = _compute_quality_metrics(decisions)
        assert q["avg_confidence"] > 0
        assert "tier_distribution" in q


class TestTopCategories:
    def test_extraction(self):
        decisions = [
            _decision("Use FastAPI for backend"),
            _decision("Use React for frontend"),
            _decision("Backend in Python"),
        ]
        cats = _extract_top_categories(decisions)
        assert len(cats) > 0
        assert any(c["topic"] == "backend" for c in cats)


class TestRecommendations:
    def test_low_decisions(self):
        recs = _generate_analytics_recommendations(
            {"total_decisions": 2, "sessions_per_month": 0, "total_patterns": 0},
            {"avg_confidence": 0.8, "trend": "stable"},
            {"timeline": []},
        )
        assert any("more decisions" in r.lower() for r in recs)

    def test_healthy(self):
        recs = _generate_analytics_recommendations(
            {"total_decisions": 20, "sessions_per_month": 2, "total_patterns": 5},
            {"avg_confidence": 0.8, "trend": "stable"},
            {"timeline": [{"month": "2026-01"}]},
        )
        assert any("healthy" in r.lower() for r in recs)


class TestHelpers:
    def test_extract_month(self):
        assert _extract_month("2026-01-15T00:00:00Z") == "2026-01"
        assert _extract_month("") == ""
        assert _extract_month("invalid") == ""

    def test_months_span(self):
        from datetime import datetime, timezone
        now = datetime(2026, 6, 1, tzinfo=timezone.utc)
        items = [{"timestamp": "2026-01-01T00:00:00Z"}]
        assert _months_span(items, now) > 4
