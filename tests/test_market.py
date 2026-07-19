"""
Tests for Decision Market — calibration pure functions.
Covers: record_bet, resolve_bet, compute_calibration, compute_leaderboard.
"""

import pytest
from core.market.calibration import (
    compute_calibration,
    compute_leaderboard,
    record_bet,
    resolve_bet,
)
from core.market import Ok, Err


# ── record_bet ──────────────────────────────────────────────────────────────

class TestRecordBet:
    def test_appends_bet_to_empty_list(self):
        bet = {
            "id": "b1",
            "decision_id": "d1",
            "agent_name": "agent1",
            "confidence": 0.8,
            "category": "architecture",
        }
        result = record_bet([], bet)
        assert isinstance(result, Ok)
        assert len(result.value) == 1
        assert result.value[0]["id"] == "b1"
        assert result.value[0]["resolved"] is False
        assert result.value[0]["outcome"] is None
        assert "placed_at" in result.value[0]

    def test_appends_to_existing_list(self):
        existing = [{"id": "b0", "decision_id": "d0", "agent_name": "a",
                      "confidence": 0.5, "category": "x"}]
        bet = {"id": "b1", "decision_id": "d1", "agent_name": "a",
               "confidence": 0.9, "category": "x"}
        result = record_bet(existing, bet)
        assert isinstance(result, Ok)
        assert len(result.value) == 2

    def test_returns_new_list_not_mutating_original(self):
        existing = [{"id": "b0", "decision_id": "d0", "agent_name": "a",
                      "confidence": 0.5, "category": "x"}]
        bet = {"id": "b1", "decision_id": "d1", "agent_name": "a",
               "confidence": 0.9, "category": "x"}
        record_bet(existing, bet)
        assert len(existing) == 1  # original unchanged

    def test_validates_confidence_range(self):
        bet = {"id": "b1", "decision_id": "d1", "agent_name": "a",
               "confidence": 1.5, "category": "x"}
        result = record_bet([], bet)
        assert isinstance(result, Err)
        assert result.code == "VALIDATION_ERROR"

    def test_rejects_negative_confidence(self):
        bet = {"id": "b1", "decision_id": "d1", "agent_name": "a",
               "confidence": -0.1, "category": "x"}
        result = record_bet([], bet)
        assert isinstance(result, Err)

    def test_validates_required_fields(self):
        bet = {"id": "b1"}  # missing decision_id, agent_name, confidence, category
        result = record_bet([], bet)
        assert isinstance(result, Err)
        assert result.code == "VALIDATION_ERROR"

    def test_preserves_existing_placed_at(self):
        bet = {"id": "b1", "decision_id": "d1", "agent_name": "a",
               "confidence": 0.7, "category": "x", "placed_at": "2026-01-01"}
        result = record_bet([], bet)
        assert result.value[0]["placed_at"] == "2026-01-01"


# ── resolve_bet ─────────────────────────────────────────────────────────────

class TestResolveBet:
    def test_resolve_correct(self):
        bet = {"id": "b1", "resolved": False, "confidence": 0.8}
        result = resolve_bet(bet, "correct")
        assert isinstance(result, Ok)
        assert result.value["resolved"] is True
        assert result.value["outcome"] == "correct"

    def test_resolve_incorrect(self):
        bet = {"id": "b1", "resolved": False}
        result = resolve_bet(bet, "incorrect")
        assert isinstance(result, Ok)
        assert result.value["outcome"] == "incorrect"

    def test_rejects_already_resolved(self):
        bet = {"id": "b1", "resolved": True, "outcome": "correct"}
        result = resolve_bet(bet, "correct")
        assert isinstance(result, Err)

    def test_rejects_invalid_outcome(self):
        bet = {"id": "b1", "resolved": False}
        result = resolve_bet(bet, "maybe")
        assert isinstance(result, Err)
        assert result.code == "VALIDATION_ERROR"

    def test_does_not_mutate_original(self):
        bet = {"id": "b1", "resolved": False}
        resolve_bet(bet, "correct")
        assert bet["resolved"] is False  # original unchanged


# ── compute_calibration ─────────────────────────────────────────────────────

class TestComputeCalibration:
    def _make_bets(self, agent, outcomes, confidences, categories=None):
        cats = categories or ["arch"] * len(outcomes)
        return [
            {
                "id": f"b{i}",
                "decision_id": f"d{i}",
                "agent_name": agent,
                "confidence": confidences[i],
                "category": cats[i],
                "resolved": True,
                "outcome": outcomes[i],
            }
            for i in range(len(outcomes))
        ]

    def test_basic_calibration(self):
        bets = self._make_bets("agent1", ["correct", "correct", "incorrect"],
                               [0.9, 0.8, 0.7])
        result = compute_calibration(bets, "agent1")
        assert isinstance(result, Ok)
        score = result.value
        assert score.total_bets == 3
        assert score.correct_bets == 2
        assert score.accuracy == pytest.approx(0.667, abs=0.01)

    def test_per_category_scores(self):
        bets = [
            {"id": "b1", "agent_name": "a", "resolved": True,
             "outcome": "correct", "confidence": 0.8, "category": "backend"},
            {"id": "b2", "agent_name": "a", "resolved": True,
             "outcome": "correct", "confidence": 0.7, "category": "backend"},
            {"id": "b3", "agent_name": "a", "resolved": True,
             "outcome": "incorrect", "confidence": 0.6, "category": "frontend"},
        ]
        result = compute_calibration(bets, "a")
        assert isinstance(result, Ok)
        assert result.value.category_scores["backend"] == 1.0
        assert result.value.category_scores["frontend"] == 0.0

    def test_overconfidence_index(self):
        bets = [
            {"id": "b1", "agent_name": "a", "resolved": True,
             "outcome": "incorrect", "confidence": 0.9, "category": "x"},
            {"id": "b2", "agent_name": "a", "resolved": True,
             "outcome": "correct", "confidence": 0.3, "category": "x"},
        ]
        result = compute_calibration(bets, "a")
        assert result.value.overconfidence_index > 0  # high conf on wrong

    def test_no_resolved_bets_for_agent(self):
        bets = [{"id": "b1", "agent_name": "other", "resolved": True,
                 "outcome": "correct", "confidence": 0.8, "category": "x"}]
        result = compute_calibration(bets, "agent1")
        assert isinstance(result, Err)
        assert result.code == "NOT_FOUND"

    def test_filters_unresolved_bets(self):
        bets = [
            {"id": "b1", "agent_name": "a", "resolved": False,
             "outcome": None, "confidence": 0.8, "category": "x"},
            {"id": "b2", "agent_name": "a", "resolved": True,
             "outcome": "correct", "confidence": 0.7, "category": "x"},
        ]
        result = compute_calibration(bets, "a")
        assert result.value.total_bets == 1


# ── compute_leaderboard ────────────────────────────────────────────────────

class TestComputeLeaderboard:
    def test_empty_bets_returns_empty(self):
        result = compute_leaderboard([])
        assert isinstance(result, Ok)
        assert result.value == []

    def test_ranks_by_accuracy(self):
        bets = [
            {"id": "b1", "agent_name": "best", "resolved": True,
             "outcome": "correct", "confidence": 0.9, "category": "x"},
            {"id": "b2", "agent_name": "worst", "resolved": True,
             "outcome": "incorrect", "confidence": 0.8, "category": "x"},
        ]
        result = compute_leaderboard(bets)
        assert isinstance(result, Ok)
        assert result.value[0].agent_name == "best"
        assert result.value[0].accuracy == 1.0

    def test_tiebreak_by_total_bets(self):
        bets = [
            {"id": "b1", "agent_name": "a1", "resolved": True,
             "outcome": "correct", "confidence": 0.8, "category": "x"},
            {"id": "b2", "agent_name": "a2", "resolved": True,
             "outcome": "correct", "confidence": 0.7, "category": "x"},
            {"id": "b3", "agent_name": "a2", "resolved": True,
             "outcome": "correct", "confidence": 0.9, "category": "x"},
        ]
        result = compute_leaderboard(bets)
        assert result.value[0].agent_name == "a2"  # same accuracy, more bets

    def test_includes_categories(self):
        bets = [
            {"id": "b1", "agent_name": "a", "resolved": True,
             "outcome": "correct", "confidence": 0.8, "category": "backend"},
            {"id": "b2", "agent_name": "a", "resolved": True,
             "outcome": "correct", "confidence": 0.7, "category": "frontend"},
        ]
        result = compute_leaderboard(bets)
        assert sorted(result.value[0].categories) == ["backend", "frontend"]
