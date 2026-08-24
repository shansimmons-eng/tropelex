"""Tests for core/safety_budget.py (wishlist #73-4): per-agent cumulative
risk-score total from overrides, gate blocks/warnings, and high-risk
decisions captured. Pure-function tests -- no HTTP, no MemoryManager.
"""

from __future__ import annotations

from core.safety_budget import (
    OVERRIDE_WEIGHT,
    compute_safety_budget,
    most_recent_eligible_decision,
)


class TestComputeSafetyBudget:
    def test_empty_memory_scores_zero(self):
        result = compute_safety_budget({}, "Claude")
        assert result["score"] == 0.0
        assert result["over_threshold"] is False

    def test_override_for_matching_agent_counted(self):
        memory = {"audit_log": [
            {"event_type": "override", "agent_name": "Claude"},
            {"event_type": "override", "agent_name": "Gemini"},
        ]}
        result = compute_safety_budget(memory, "Claude")
        assert result["breakdown"]["overrides"]["count"] == 1
        assert result["score"] == OVERRIDE_WEIGHT

    def test_gate_blocked_weighted_by_severity(self):
        memory = {"audit_log": [
            {
                "event_type": "gate_blocked", "agent_name": "Claude",
                "severity_counts": {"high": 2, "medium": 1, "low": 0},
            },
        ]}
        result = compute_safety_budget(memory, "Claude")
        # 2*3.0 + 1*2.0 = 8.0
        assert result["breakdown"]["gate_blocked"]["score"] == 8.0
        assert result["score"] == 8.0

    def test_gate_warned_weighted_lower_than_gate_blocked(self):
        blocked_memory = {"audit_log": [
            {"event_type": "gate_blocked", "agent_name": "Claude", "severity_counts": {"high": 1}},
        ]}
        warned_memory = {"audit_log": [
            {"event_type": "gate_warned", "agent_name": "Claude", "severity_counts": {"high": 1}},
        ]}
        blocked_score = compute_safety_budget(blocked_memory, "Claude")["score"]
        warned_score = compute_safety_budget(warned_memory, "Claude")["score"]
        assert warned_score < blocked_score

    def test_events_for_other_agents_not_counted(self):
        memory = {"audit_log": [
            {"event_type": "gate_blocked", "agent_name": "Gemini", "severity_counts": {"high": 5}},
        ]}
        result = compute_safety_budget(memory, "Claude")
        assert result["score"] == 0.0

    def test_high_risk_decision_counted(self):
        memory = {"decisions": [
            {"agent_name": "Claude", "safety_metadata": {"risk_level": "high"}},
            {"agent_name": "Claude", "safety_metadata": {"risk_level": "low"}},
            {"agent_name": "Gemini", "safety_metadata": {"risk_level": "high"}},
        ]}
        result = compute_safety_budget(memory, "Claude")
        assert result["breakdown"]["high_risk_decisions"]["count"] == 1

    def test_medium_risk_decision_weighted_lower_than_high(self):
        memory = {"decisions": [{"agent_name": "Claude", "safety_metadata": {"risk_level": "medium"}}]}
        result = compute_safety_budget(memory, "Claude")
        assert 0 < result["score"] < 2.0

    def test_over_threshold_flips_true_once_score_crosses_it(self):
        memory = {"audit_log": [
            {"event_type": "override", "agent_name": "Claude"} for _ in range(10)
        ]}
        result = compute_safety_budget(memory, "Claude", threshold=5.0)
        assert result["over_threshold"] is True

    def test_malformed_audit_log_and_decisions_do_not_raise(self):
        memory = {"audit_log": ["garbage", None, {}], "decisions": ["garbage", None, {}]}
        result = compute_safety_budget(memory, "Claude")
        assert result["score"] == 0.0

    def test_severity_counts_with_non_numeric_values_degrade_to_zero(self):
        memory = {"audit_log": [
            {"event_type": "gate_blocked", "agent_name": "Claude", "severity_counts": {"high": "not-a-number"}},
        ]}
        result = compute_safety_budget(memory, "Claude")
        assert result["score"] == 0.0


class TestMostRecentEligibleDecision:
    def test_picks_the_latest_timestamp(self):
        decisions = [
            {"id": "a", "agent_name": "Claude", "timestamp": "2026-01-01T00:00:00+00:00"},
            {"id": "b", "agent_name": "Claude", "timestamp": "2026-01-03T00:00:00+00:00"},
            {"id": "c", "agent_name": "Claude", "timestamp": "2026-01-02T00:00:00+00:00"},
        ]
        result = most_recent_eligible_decision(decisions, "Claude")
        assert result["id"] == "b"

    def test_excludes_already_flagged_for_review(self):
        decisions = [
            {"id": "a", "agent_name": "Claude", "timestamp": "2026-01-01T00:00:00+00:00",
             "safety_metadata": {"requires_review": True}},
        ]
        assert most_recent_eligible_decision(decisions, "Claude") is None

    def test_excludes_already_reviewed(self):
        decisions = [
            {"id": "a", "agent_name": "Claude", "timestamp": "2026-01-01T00:00:00+00:00",
             "safety_reviews": [{"reviewer": "shan"}]},
        ]
        assert most_recent_eligible_decision(decisions, "Claude") is None

    def test_excludes_other_agents(self):
        decisions = [{"id": "a", "agent_name": "Gemini", "timestamp": "2026-01-01T00:00:00+00:00"}]
        assert most_recent_eligible_decision(decisions, "Claude") is None

    def test_no_decisions_returns_none(self):
        assert most_recent_eligible_decision([], "Claude") is None
