"""Tests for core.health.dashboard — Memory Health Dashboard."""

import pytest
from core.health.dashboard import (
    aggregate_health_metrics,
    _compute_coverage_gaps,
    _compute_quality_score,
    _generate_recommendations,
    _compute_growth_trends,
)


def _memory(decisions=None, tech_stack=None, sessions=None, patterns=None):
    return {
        "project_name": "test",
        "decisions": decisions or [],
        "tech_stack": tech_stack or [],
        "session_history": sessions or [],
        "patterns": patterns or [],
    }


def _decision(text, ts="2026-01-01T00:00:00Z", context=""):
    return {"decision": text, "timestamp": ts, "context": context}


class TestCoverageGaps:
    def test_all_covered(self):
        decisions = [_decision("Use React for UI"), _decision("Backend in Python")]
        gaps = _compute_coverage_gaps(decisions, ["React", "Python"])
        assert gaps == []

    def test_some_missing(self):
        decisions = [_decision("Use React for UI")]
        gaps = _compute_coverage_gaps(decisions, ["React", "Python", "Docker"])
        assert "Python" in gaps
        assert "Docker" in gaps
        assert "React" not in gaps

    def test_empty_tech_stack(self):
        assert _compute_coverage_gaps([_decision("x")], []) == []

    def test_empty_decisions(self):
        gaps = _compute_coverage_gaps([], ["React"])
        assert gaps == ["React"]


class TestQualityScore:
    def test_empty(self):
        assert _compute_quality_score([]) == 0.0

    def test_single(self):
        scored = [{"score": 0.8}]
        assert _compute_quality_score(scored) == pytest.approx(0.8)

    def test_average(self):
        scored = [{"score": 0.6}, {"score": 0.4}]
        assert _compute_quality_score(scored) == pytest.approx(0.5)


class TestGrowthTrends:
    def test_counts(self):
        memory = _memory(
            decisions=[_decision("a"), _decision("b")],
            sessions=[{"date": "2026-01-01"}],
            patterns=[{"name": "p1"}],
        )
        trends = _compute_growth_trends(memory)
        assert trends["decision_count"] == 2
        assert trends["session_count"] == 1
        assert trends["pattern_count"] == 1


class TestRecommendations:
    def test_stale_recommendation(self):
        recs = _generate_recommendations(
            stale=[{"decision": "old"}], gaps=[], quality=0.8,
            confidence={"by_tier": {"high": 5, "stale": 1}},
        )
        assert any("stale" in r.lower() for r in recs)

    def test_gap_recommendation(self):
        recs = _generate_recommendations(
            stale=[], gaps=["Docker"], quality=0.8,
            confidence={"by_tier": {"high": 5, "stale": 0}},
        )
        assert any("Docker" in r for r in recs)

    def test_low_quality(self):
        recs = _generate_recommendations(
            stale=[], gaps=[], quality=0.2,
            confidence={"by_tier": {"high": 1, "stale": 0}},
        )
        assert any("confidence" in r.lower() for r in recs)

    def test_healthy(self):
        recs = _generate_recommendations(
            stale=[], gaps=[], quality=0.9,
            confidence={"by_tier": {"high": 5, "stale": 0}},
        )
        assert any("good" in r.lower() for r in recs)


class TestAggregateHealthMetrics:
    def test_empty_memory(self):
        result = aggregate_health_metrics(_memory())
        assert result["quality_score"] == 0.0
        assert result["stale_decisions"] == []
        assert result["growth_trends"]["decision_count"] == 0

    def test_with_decisions(self):
        decisions = [
            _decision("Use FastAPI", "2026-06-01T00:00:00Z"),
            _decision("Use PostgreSQL", "2026-06-15T00:00:00Z"),
        ]
        memory = _memory(decisions=decisions, tech_stack=["FastAPI", "PostgreSQL"])
        result = aggregate_health_metrics(memory)
        assert result["quality_score"] > 0
        assert result["growth_trends"]["decision_count"] == 2
        assert isinstance(result["recommendations"], list)
        assert "confidence_summary" in result

    def test_result_shape(self):
        result = aggregate_health_metrics(_memory([_decision("x", "2026-06-01T00:00:00Z")]))
        for key in ("stale_decisions", "coverage_gaps", "growth_trends", "quality_score", "recommendations"):
            assert key in result
