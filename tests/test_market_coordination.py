"""Tests for core.market.coordination -- Coordination Drift Detection
(wishlist #43): whether agents' calibration profiles are converging or
diverging from each other over time, distinct from each agent's own
accuracy trend.
"""

from __future__ import annotations

from core.market import CalibrationScore
from core.market.coordination import (
    DRIFT_THRESHOLD,
    compute_agreement,
    score_coordination_drift,
)


def _cal(agent="a", accuracy=0.8, overconfidence=0.0, total=10, correct=8):
    return CalibrationScore(
        agent_name=agent, total_bets=total, correct_bets=correct,
        accuracy=accuracy, overconfidence_index=overconfidence,
    )


def _bet(agent, outcome, confidence=0.8, category="backend"):
    return {
        "agent_name": agent, "resolved": True, "outcome": outcome,
        "confidence": confidence, "category": category,
    }


class TestComputeAgreement:
    def test_identical_profiles_full_agreement(self):
        a = _cal(accuracy=0.8, overconfidence=0.1)
        b = _cal(accuracy=0.8, overconfidence=0.1)
        assert compute_agreement(a, b) == 1.0

    def test_maximally_divergent_zero_agreement(self):
        a = _cal(accuracy=1.0, overconfidence=1.0)
        b = _cal(accuracy=0.0, overconfidence=-1.0)
        assert compute_agreement(a, b) == 0.0

    def test_partial_accuracy_difference(self):
        a = _cal(accuracy=0.8, overconfidence=0.0)
        b = _cal(accuracy=0.6, overconfidence=0.0)
        # accuracy_diff=0.2, overconfidence_diff=0 -> combined=0.1 -> agreement=0.9
        assert compute_agreement(a, b) == 0.9

    def test_symmetric(self):
        a = _cal(accuracy=0.9, overconfidence=0.3)
        b = _cal(accuracy=0.5, overconfidence=-0.2)
        assert compute_agreement(a, b) == compute_agreement(b, a)

    def test_overconfidence_alone_reduces_agreement(self):
        """Same accuracy, but one agent is much more overconfident --
        that's a real behavioral divergence, not full agreement."""
        a = _cal(accuracy=0.8, overconfidence=0.0)
        b = _cal(accuracy=0.8, overconfidence=1.0)
        assert compute_agreement(a, b) < 1.0


class TestScoreCoordinationDrift:
    def test_no_bets_insufficient_data(self):
        result = score_coordination_drift([])
        assert result["drift_detected"] is False
        assert result["eligible_agents"] == []
        assert result["pairs"] == []
        assert "message" in result

    def test_single_agent_insufficient_data(self):
        """One agent can have a valid baseline/recent window on its own,
        but there's nothing to compare it against -- no pairs, no drift."""
        bets = [_bet("claude", "correct") for _ in range(20)]
        result = score_coordination_drift(bets, window=3)
        assert result["drift_detected"] is False
        assert result["eligible_agents"] == ["claude"]
        assert result["pairs"] == []

    def test_not_a_list_treated_as_empty(self):
        result = score_coordination_drift("not a list")
        assert result["drift_detected"] is False
        assert result["pairs"] == []

    def test_malformed_bet_entries_skipped_not_crashed(self):
        bets = [None, "not a dict", 42, {"resolved": True}]  # last one: no agent_name
        result = score_coordination_drift(bets, window=3)
        assert result["eligible_agents"] == []

    def test_unresolved_bets_excluded(self):
        bets = [
            {"agent_name": "claude", "resolved": False, "outcome": None, "confidence": 0.9, "category": "x"}
            for _ in range(20)
        ]
        result = score_coordination_drift(bets, window=3)
        assert result["eligible_agents"] == []

    def test_two_agents_stable_agreement_no_drift(self):
        window = 3
        bets = []
        for agent in ("claude", "gemini"):
            # 6 correct-then-6-correct bets: identical, stable calibration
            for _ in range(window * 2):
                bets.append(_bet(agent, "correct", confidence=0.8))
        result = score_coordination_drift(bets, window=window)
        assert result["eligible_agents"] == ["claude", "gemini"]
        assert len(result["pairs"]) == 1
        pair = result["pairs"][0]
        assert pair["baseline_agreement"] == 1.0
        assert pair["recent_agreement"] == 1.0
        assert pair["drift"] == 0.0
        assert pair["drift_detected"] is False
        assert result["drift_detected"] is False

    def test_declining_agreement_flagged_as_drift(self):
        window = 3
        bets = []
        # claude: consistently accurate throughout
        for _ in range(window * 2):
            bets.append(_bet("claude", "correct", confidence=0.9))
        # gemini: accurate in the baseline window, then goes wrong in the
        # recent window -- diverging from claude over time.
        for _ in range(window):
            bets.append(_bet("gemini", "correct", confidence=0.9))
        for _ in range(window):
            bets.append(_bet("gemini", "incorrect", confidence=0.9))

        result = score_coordination_drift(bets, window=window)
        pair = result["pairs"][0]
        assert pair["baseline_agreement"] == 1.0
        assert pair["recent_agreement"] < pair["baseline_agreement"]
        assert pair["drift"] < 0
        if abs(pair["drift"]) >= DRIFT_THRESHOLD:
            assert pair["drift_detected"] is True
            assert result["drift_detected"] is True

    def test_multiple_agent_pairs_all_scored(self):
        window = 3
        bets = []
        for agent in ("claude", "gemini", "gpt"):
            for _ in range(window * 2):
                bets.append(_bet(agent, "correct", confidence=0.8))
        result = score_coordination_drift(bets, window=window)
        assert len(result["eligible_agents"]) == 3
        # C(3,2) = 3 pairs
        assert len(result["pairs"]) == 3
        pair_names = {(p["agent_a"], p["agent_b"]) for p in result["pairs"]}
        assert pair_names == {("claude", "gemini"), ("claude", "gpt"), ("gemini", "gpt")}

    def test_below_min_bets_per_window_excluded(self):
        """window=2 means MIN_BETS_PER_WINDOW=3 can't be satisfied by a
        window of only 2 bets -- agent should be excluded, not crash."""
        bets = [_bet("claude", "correct") for _ in range(4)]  # window*2=4 total, 2 per half
        result = score_coordination_drift(bets, window=2)
        assert result["eligible_agents"] == []
