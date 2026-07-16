"""Tests for core.impact.analysis — Decision Impact Analysis."""

import pytest
from core.impact.analysis import (
    compute_impact_analysis,
    _extract_reversals,
    _compute_impact_scores,
    _link_decision_metadata,
    _compute_summary,
    _empty_result,
)
from core.decision_tree import DecisionTree


def _decision(text, ts="2026-01-01T00:00:00Z", did=None, edges=None, context=""):
    d = {"decision": text, "timestamp": ts, "context": context}
    if did:
        d["id"] = did
    if edges:
        d["edges"] = edges
    return d


class TestComputeImpactAnalysis:
    def test_empty_memory(self):
        result = compute_impact_analysis({})
        assert result["summary"]["total_decisions"] == 0
        assert result["linked_decisions"] == []

    def test_single_decision(self):
        memory = {"decisions": [_decision("Use FastAPI")]}
        result = compute_impact_analysis(memory)
        assert result["summary"]["total_decisions"] == 1
        assert len(result["linked_decisions"]) == 1
        assert len(result["impact_scores"]) == 1

    def test_with_reversals(self):
        d1 = _decision("Use Flask", did="d1")
        d2 = _decision("Switch to FastAPI", did="d2", edges=[
            {"source": "d2", "target": "d1", "relationship": "supersedes"}
        ])
        memory = {"decisions": [d1, d2]}
        result = compute_impact_analysis(memory)
        assert result["summary"]["reversal_count"] >= 1
        assert result["summary"]["reversal_rate"] > 0


class TestExtractReversals:
    def test_no_reversals(self):
        decisions = [_decision("a"), _decision("b")]
        assert _extract_reversals(decisions) == []

    def test_supersedes(self):
        d1 = _decision("old", did="d1")
        d2 = _decision("new", did="d2", edges=[
            {"source": "d2", "target": "d1", "relationship": "supersedes"}
        ])
        reversals = _extract_reversals([d1, d2])
        assert len(reversals) == 1
        assert reversals[0]["reversal_type"] == "supersedes"

    def test_explicit_reverts(self):
        d1 = _decision("old", did="d1")
        d2 = _decision("revert", did="d2")
        d2["reverts"] = "d1"
        reversals = _extract_reversals([d1, d2])
        assert len(reversals) == 1


class TestComputeImpactScores:
    def test_scores_sorted(self):
        decisions = [_decision("a", did="d1"), _decision("b", did="d2")]
        tree = DecisionTree.from_decisions(decisions)
        scored = [{"decision": "a", "score": 0.9}, {"decision": "b", "score": 0.3}]
        impacts = _compute_impact_scores(decisions, tree, scored)
        assert len(impacts) == 2
        assert impacts[0]["impact_score"] >= impacts[1]["impact_score"]

    def test_reversed_penalty(self):
        d1 = _decision("old", did="d1")
        d2 = _decision("new", did="d2", edges=[
            {"source": "d2", "target": "d1", "relationship": "reverts"}
        ])
        tree = DecisionTree.from_decisions([d1, d2])
        scored = [{"decision": "old", "score": 0.9}, {"decision": "new", "score": 0.9}]
        impacts = _compute_impact_scores([d1, d2], tree, scored)
        # d2 has reversal edge, so should have lower impact
        d2_impact = next(i for i in impacts if i["decision_id"] == "d2")
        d1_impact = next(i for i in impacts if i["decision_id"] == "d1")
        assert d2_impact["impact_score"] <= d1_impact["impact_score"]


class TestLinkDecisionMetadata:
    def test_basic_link(self):
        d = _decision("test", did="d1")
        tree = DecisionTree.from_decisions([d])
        linked = _link_decision_metadata(d, tree)
        assert linked["id"] == "d1"
        assert "edge_count" in linked


class TestSummary:
    def test_empty(self):
        assert _empty_result()["summary"]["total_decisions"] == 0

    def test_with_data(self):
        decisions = [_decision("a")]
        impacts = [{"impact_score": 0.7}]
        summary = _compute_summary(decisions, [], impacts)
        assert summary["total_decisions"] == 1
        assert summary["reversal_rate"] == 0
