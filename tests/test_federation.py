"""
Tests for Federation — anonymizer and aggregator pure functions.
Covers: hash_project_name, extract_structural_stats, anonymize_project,
        aggregate_benchmarks, compute_percentiles, compare_to_aggregate.
"""

import pytest
from core.federation.anonymizer import (
    anonymize_project,
    extract_structural_stats,
    hash_project_name,
)
from core.federation.aggregator import (
    aggregate_benchmarks,
    compare_to_aggregate,
    compute_percentiles,
)
from core.federation import AnonymizedStats, Ok, Err


# ── hash_project_name ──────────────────────────────────────────────────────

class TestHashProjectName:
    def test_deterministic(self):
        assert hash_project_name("my-project") == hash_project_name("my-project")

    def test_different_names_different_hashes(self):
        assert hash_project_name("a") != hash_project_name("b")

    def test_returns_16_chars(self):
        result = hash_project_name("test")
        assert len(result) == 16


# ── extract_structural_stats ───────────────────────────────────────────────

class TestExtractStructuralStats:
    def test_empty_memory(self):
        result = extract_structural_stats({})
        assert result["decision_count"] == 0
        assert result["reversal_rate"] == 0.0
        assert result["avg_confidence"] == 0.5

    def test_decision_count(self):
        memory = {"decisions": [{"decision": "a"}, {"decision": "b"}]}
        result = extract_structural_stats(memory)
        assert result["decision_count"] == 2

    def test_reversal_rate(self):
        memory = {
            "decisions": [
                {"decision": "Revert previous choice"},
                {"decision": "Use FastAPI"},
            ]
        }
        result = extract_structural_stats(memory)
        assert result["reversal_rate"] == 0.5

    def test_avg_confidence(self):
        memory = {
            "decisions": [
                {"decision": "a", "confidence": {"score": 0.8}},
                {"decision": "b", "confidence": {"score": 0.6}},
            ]
        }
        result = extract_structural_stats(memory)
        assert result["avg_confidence"] == pytest.approx(0.7, abs=0.01)

    def test_category_distribution(self):
        memory = {
            "patterns": [
                {"name": "backend:fastapi", "count": 5},
                {"name": "frontend:react", "count": 3},
            ]
        }
        result = extract_structural_stats(memory)
        assert result["category_distribution"]["backend"] == 5
        assert result["category_distribution"]["frontend"] == 3

    def test_tech_stack_filters_non_strings(self):
        memory = {"tech_stack": ["Python", 123, "FastAPI"]}
        result = extract_structural_stats(memory)
        assert "Python" in result["tech_stack"]
        assert "FastAPI" in result["tech_stack"]
        assert 123 not in result["tech_stack"]

    def test_no_decisions_perfect_safety_score(self):
        result = extract_structural_stats({})
        assert result["avg_safety_score"] == 1.0
        assert result["risk_level_distribution"] == {}

    def test_all_low_risk_perfect_safety_score(self):
        memory = {"decisions": [
            {"decision": "a", "safety_metadata": {"risk_level": "low"}},
            {"decision": "b", "safety_metadata": {"risk_level": "low"}},
        ]}
        result = extract_structural_stats(memory)
        assert result["avg_safety_score"] == 1.0
        assert result["risk_level_distribution"] == {"low": 2}

    def test_critical_risk_lowers_safety_score(self):
        memory = {"decisions": [
            {"decision": "a", "safety_metadata": {"risk_level": "critical"}},
        ]}
        result = extract_structural_stats(memory)
        assert result["avg_safety_score"] == 0.0
        assert result["risk_level_distribution"] == {"critical": 1}

    def test_missing_safety_metadata_defaults_to_low(self):
        memory = {"decisions": [{"decision": "a"}]}
        result = extract_structural_stats(memory)
        assert result["avg_safety_score"] == 1.0
        assert result["risk_level_distribution"] == {"low": 1}


# ── anonymize_project ─────────────────────────────────────────────────────

class TestAnonymizeProject:
    def test_basic_anonymization(self):
        memory = {
            "project_name": "my-secret-project",
            "decisions": [{"decision": "Use FastAPI", "confidence": {"score": 0.8}}],
            "tech_stack": ["Python", "FastAPI"],
        }
        result = anonymize_project(memory)
        assert isinstance(result, Ok)
        stats = result.value
        assert stats.project_hash == hash_project_name("my-secret-project")
        assert stats.decision_count == 1
        assert "Python" in stats.tech_stack

    def test_rejects_non_dict(self):
        result = anonymize_project("not a dict")
        assert isinstance(result, Err)
        assert result.code == "VALIDATION_ERROR"

    def test_rejects_missing_project_name(self):
        result = anonymize_project({"decisions": []})
        assert isinstance(result, Err)


# ── aggregate_benchmarks ──────────────────────────────────────────────────

class TestAggregateBenchmarks:
    def _stats(self, name, count=10, rev=0.1, conf=0.7):
        return AnonymizedStats(
            project_hash=hash_project_name(name),
            tech_stack=["Python"],
            decision_count=count,
            reversal_rate=rev,
            avg_confidence=conf,
            category_distribution={},
        )

    def test_basic_aggregation(self):
        stats = [self._stats("a", count=10), self._stats("b", count=20)]
        result = aggregate_benchmarks(stats)
        assert isinstance(result, Ok)
        assert result.value.decision_count == 30

    def test_averages_reversal_and_confidence(self):
        stats = [self._stats("a", rev=0.1), self._stats("b", rev=0.3)]
        result = aggregate_benchmarks(stats)
        assert result.value.reversal_rate == pytest.approx(0.2, abs=0.01)

    def test_empty_list(self):
        result = aggregate_benchmarks([])
        assert isinstance(result, Err)

    def test_merge_tech_stacks(self):
        s1 = AnonymizedStats(project_hash="a", tech_stack=["Python"],
                             decision_count=1, reversal_rate=0, avg_confidence=0.5,
                             category_distribution={})
        s2 = AnonymizedStats(project_hash="b", tech_stack=["Go"],
                             decision_count=1, reversal_rate=0, avg_confidence=0.5,
                             category_distribution={})
        result = aggregate_benchmarks([s1, s2])
        assert "Go" in result.value.tech_stack
        assert "Python" in result.value.tech_stack

    def test_averages_safety_score(self):
        s1 = AnonymizedStats(project_hash="a", tech_stack=[], decision_count=1,
                             reversal_rate=0, avg_confidence=0.5, category_distribution={},
                             avg_safety_score=1.0)
        s2 = AnonymizedStats(project_hash="b", tech_stack=[], decision_count=1,
                             reversal_rate=0, avg_confidence=0.5, category_distribution={},
                             avg_safety_score=0.6)
        result = aggregate_benchmarks([s1, s2])
        assert result.value.avg_safety_score == pytest.approx(0.8, abs=0.01)

    def test_merges_risk_level_distribution(self):
        s1 = AnonymizedStats(project_hash="a", tech_stack=[], decision_count=1,
                             reversal_rate=0, avg_confidence=0.5, category_distribution={},
                             risk_level_distribution={"low": 3, "high": 1})
        s2 = AnonymizedStats(project_hash="b", tech_stack=[], decision_count=1,
                             reversal_rate=0, avg_confidence=0.5, category_distribution={},
                             risk_level_distribution={"low": 2, "critical": 1})
        result = aggregate_benchmarks([s1, s2])
        assert result.value.risk_level_distribution == {"low": 5, "high": 1, "critical": 1}


# ── compute_percentiles ───────────────────────────────────────────────────

class TestComputePercentiles:
    def test_project_at_top(self):
        stats = [
            AnonymizedStats(project_hash="a", tech_stack=[], decision_count=5,
                            reversal_rate=0.1, avg_confidence=0.5, category_distribution={}),
            AnonymizedStats(project_hash="b", tech_stack=[], decision_count=10,
                            reversal_rate=0.2, avg_confidence=0.6, category_distribution={}),
        ]
        project = AnonymizedStats(project_hash="p", tech_stack=[], decision_count=15,
                                   reversal_rate=0.3, avg_confidence=0.7, category_distribution={})
        result = compute_percentiles(stats, project)
        assert isinstance(result, Ok)
        assert result.value["decision_count"] == 100.0

    def test_empty_stats(self):
        project = AnonymizedStats(project_hash="p", tech_stack=[], decision_count=10,
                                   reversal_rate=0.1, avg_confidence=0.5, category_distribution={})
        result = compute_percentiles([], project)
        assert isinstance(result, Err)


# ── compare_to_aggregate ──────────────────────────────────────────────────

class TestCompareToAggregate:
    def test_deviation_calculation(self):
        project = AnonymizedStats(project_hash="p", tech_stack=[], decision_count=20,
                                   reversal_rate=0.2, avg_confidence=0.8, category_distribution={})
        aggregate = AnonymizedStats(project_hash="agg", tech_stack=[], decision_count=10,
                                     reversal_rate=0.1, avg_confidence=0.5, category_distribution={})
        result = compare_to_aggregate(project, aggregate)
        assert isinstance(result, Ok)
        assert result.value.deviation["decision_count"] == pytest.approx(1.0, abs=0.01)
        assert result.value.deviation["avg_confidence"] == pytest.approx(0.6, abs=0.01)
