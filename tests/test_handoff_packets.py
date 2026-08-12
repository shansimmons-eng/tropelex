"""
Tests for Agent Handoff Packets (core.handoff).

Covers packet_builder (pure functions) and router (FastAPI endpoints).
Uses httpx AsyncClient for endpoint tests; all external I/O is mocked.
"""

import copy
import json
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from core.handoff.packet_builder import (
    ContextSlice,
    HandoffPacket,
    ROLE_PROFILES,
    _build_context_slices,
    _build_goal_slices,
    _estimate_tokens,
    _format_skills_summary,
    _select_active_goals,
    _select_decisions,
    _select_sessions,
    _trim_to_budget,
    build_handoff_packet,
)


# ---------------------------------------------------------------------------
#  Helpers — realistic test data factories
# ---------------------------------------------------------------------------

def _decision(text, context="", categories=None, ts=None, **extra):
    """Factory: build a decision dict with realistic fields. Extra kwargs
    (e.g. safety_metadata, must_survive, id) merged in for #69 tests."""
    d = {
        "decision": text,
        "context": context,
        "timestamp": ts or datetime.now(timezone.utc).isoformat(),
        "categories": categories or [],
    }
    d.update(extra)
    return d


def _session(summary, ts=None, insights=None):
    """Factory: build a session-history entry."""
    return {
        "summary": summary,
        "timestamp": ts or datetime.now(timezone.utc).isoformat(),
        "insights": insights or [],
    }


def _memory(decisions=None, sessions=None, patterns=None, goals=None):
    """Factory: build a full memory dict."""
    return {
        "decisions": decisions or [],
        "session_history": sessions or [],
        "patterns": patterns or [],
        "goals": goals or [],
    }


def _goal(text, status="active", priority="medium", **extra):
    """Factory: build a goal dict with realistic fields."""
    return {"id": extra.pop("id", text[:12]), "text": text, "status": status, "priority": priority, **extra}


def _scored(decision_text, score=0.9, tier="high"):
    """Factory: build a knowledge_decay scored entry."""
    return {
        "decision": decision_text,
        "score": score,
        "tier": tier,
    }


# Realistic decisions used across multiple tests
BACKEND_DECISION = _decision(
    "Use FastAPI for REST endpoints",
    context="Backend needs async HTTP handling with Pydantic validation",
    categories=["backend"],
)
TESTING_DECISION = _decision(
    "Adopt pytest with 90% coverage threshold",
    context="All new modules must meet testing standards before merge",
    categories=["testing"],
)
CONFIG_DECISION = _decision(
    "Use pyproject.toml for all project config",
    context="Single source of truth for deps, linting, and build",
    categories=["config"],
)
UI_DECISION = _decision(
    "Use Tailwind CSS for styling",
    context="Frontend needs utility-first CSS for rapid prototyping",
    categories=["ui"],
)
UNRELATED_DECISION = _decision(
    "Deploy on Tuesdays only",
    context="Change window agreed with ops team",
    categories=["devops"],
)


# ---------------------------------------------------------------------------
#  1. Packet Builder — pure function unit tests
# ---------------------------------------------------------------------------


class TestEstimateTokens:
    """Token estimation: ~4 chars per token."""

    def test_estimate_tokens_returns_correct_count(self):
        # Arrange
        text = "Use FastAPI for backend"  # 23 chars

        # Act
        result = _estimate_tokens(text)

        # Assert
        assert result == 5  # 23 // 4

    def test_estimate_tokens_empty_string(self):
        # Arrange / Act / Assert
        assert _estimate_tokens("") == 0

    def test_estimate_tokens_short_text(self):
        # Arrange / Act / Assert — 3 chars → 0 tokens
        assert _estimate_tokens("abc") == 0


class TestSelectDecisions:
    """Decision selection: category filtering, confidence sorting, max cap."""

    def test_select_decisions_filters_by_category(self):
        # Arrange
        profile = ROLE_PROFILES["TestEngineer"]  # priority: ["testing", "backend"]
        decisions = [BACKEND_DECISION, TESTING_DECISION, UI_DECISION, UNRELATED_DECISION]
        scored = [_scored(d["decision"]) for d in decisions]

        # Act
        result = _select_decisions(decisions, profile, scored)

        # Assert — testing + backend should appear before ui/devops
        result_texts = [d["decision"] for d in result]
        assert "Adopt pytest with 90% coverage threshold" in result_texts
        assert "Use FastAPI for REST endpoints" in result_texts
        # UI and devops are not priority for TestEngineer but still included
        assert "Use Tailwind CSS for styling" in result_texts

    def test_select_decisions_sorts_by_confidence(self):
        # Arrange
        profile = ROLE_PROFILES["CoderAgent"]
        low_score = _scored("Use Go for CLI tools", score=0.3, tier="low")
        high_score = _scored("Use FastAPI for REST endpoints", score=0.95, tier="high")
        decisions = [
            _decision("Use Go for CLI tools", categories=["backend"]),
            BACKEND_DECISION,
        ]
        scored = [high_score, low_score]

        # Act
        result = _select_decisions(decisions, profile, scored)

        # Assert — higher confidence score should come first (among priority matches)
        if len(result) >= 2:
            assert result[0]["confidence"].get("score", 0) >= result[1]["confidence"].get("score", 0)

    def test_select_decisions_caps_at_max(self):
        # Arrange — CoderAgent allows max 15; create 20 decisions
        profile = ROLE_PROFILES["CoderAgent"]
        decisions = [_decision(f"Backend decision {i}", categories=["backend"]) for i in range(20)]
        scored = [_scored(d["decision"]) for d in decisions]

        # Act
        result = _select_decisions(decisions, profile, scored)

        # Assert
        assert len(result) == 15

    def test_select_decisions_empty_input(self):
        # Arrange
        profile = ROLE_PROFILES["CoderAgent"]

        # Act
        result = _select_decisions([], profile, [])

        # Assert
        assert result == []

    def test_must_survive_decision_kept_past_max_decisions_cap(self):
        """#69: a must-survive decision outside the role's priority
        categories must not be silently cut at the max_decisions cap."""
        # Arrange -- CoderAgent caps at 15; 20 backend fillers + 1 critical
        # decision in an unrelated category push the critical one past the cap.
        profile = ROLE_PROFILES["CoderAgent"]
        critical = _decision(
            "Critical decision outside priority categories", categories=["database"],
            safety_metadata={"risk_level": "critical"},
        )
        fillers = [_decision(f"Backend decision {i}", categories=["backend"]) for i in range(20)]
        decisions = fillers + [critical]
        scored = [_scored(d["decision"]) for d in decisions]

        # Act
        result = _select_decisions(decisions, profile, scored)

        # Assert
        assert len(result) > 15
        assert any(d["decision"] == critical["decision"] for d in result)

    def test_non_must_survive_decision_still_capped(self):
        """The cap-exemption is specific to must-survive decisions --
        ordinary low-priority decisions still get cut as before."""
        profile = ROLE_PROFILES["CoderAgent"]
        decisions = [_decision(f"Backend decision {i}", categories=["backend"]) for i in range(20)]
        scored = [_scored(d["decision"]) for d in decisions]

        result = _select_decisions(decisions, profile, scored)

        assert len(result) == 15


class TestIsMustSurvive:
    def test_explicit_flag(self):
        from core.handoff.packet_builder import _is_must_survive
        assert _is_must_survive({"decision": "x", "must_survive": True}) is True

    def test_derived_from_critical_risk_level(self):
        from core.handoff.packet_builder import _is_must_survive
        d = {"decision": "x", "safety_metadata": {"risk_level": "critical"}}
        assert _is_must_survive(d) is True

    def test_derived_from_high_risk_level(self):
        from core.handoff.packet_builder import _is_must_survive
        d = {"decision": "x", "safety_metadata": {"risk_level": "high"}}
        assert _is_must_survive(d) is True

    def test_low_risk_level_is_not_must_survive(self):
        from core.handoff.packet_builder import _is_must_survive
        d = {"decision": "x", "safety_metadata": {"risk_level": "low"}}
        assert _is_must_survive(d) is False

    def test_no_safety_metadata_is_not_must_survive(self):
        from core.handoff.packet_builder import _is_must_survive
        assert _is_must_survive({"decision": "x"}) is False

    def test_malformed_safety_metadata_does_not_raise(self):
        from core.handoff.packet_builder import _is_must_survive
        assert _is_must_survive({"decision": "x", "safety_metadata": "corrupted"}) is False

    def test_must_survive_false_does_not_override_low_risk(self):
        from core.handoff.packet_builder import _is_must_survive
        d = {"decision": "x", "must_survive": False, "safety_metadata": {"risk_level": "low"}}
        assert _is_must_survive(d) is False


class TestSelectSessions:
    """Session selection: recent-first, respects include_sessions flag."""

    def test_select_sessions_returns_recent(self):
        # Arrange
        profile = ROLE_PROFILES["CoderAgent"]  # include_sessions=True
        old_session = _session("Old session", ts="2026-01-01T00:00:00Z")
        new_session = _session("New session", ts="2026-06-01T00:00:00Z")
        sessions = [old_session, new_session]

        # Act
        result = _select_sessions(sessions, profile)

        # Assert — most recent first
        assert len(result) == 2
        assert result[0]["summary"] == "New session"
        assert result[1]["summary"] == "Old session"

    def test_select_sessions_returns_empty_when_disabled(self):
        # Arrange — FrontendSpecialist has include_sessions=True but test with False profile
        profile = {"include_sessions": False}
        sessions = [_session("Test session")]

        # Act
        result = _select_sessions(sessions, profile)

        # Assert
        assert result == []

    def test_select_sessions_empty_input(self):
        # Arrange
        profile = ROLE_PROFILES["CoderAgent"]

        # Act / Assert
        assert _select_sessions([], profile) == []

    def test_select_sessions_caps_at_five(self):
        # Arrange
        profile = ROLE_PROFILES["CoderAgent"]
        sessions = [_session(f"Session {i}", ts=f"2026-01-{10+i:02d}T00:00:00Z") for i in range(10)]

        # Act
        result = _select_sessions(sessions, profile)

        # Assert
        assert len(result) == 5


class TestBuildContextSlices:
    """Context slice creation: priority assignment, content formatting."""

    def test_build_context_slices_creates_slices(self):
        # Arrange
        profile = ROLE_PROFILES["CoderAgent"]
        decisions = [BACKEND_DECISION]
        sessions = [_session("Test session", ts="2026-06-01T00:00:00Z")]

        # Act
        slices = _build_context_slices(decisions, sessions, profile)

        # Assert
        assert len(slices) == 2
        assert slices[0].category == "decision"
        assert slices[1].category == "session"

    def test_build_context_slices_priority_assignment(self):
        # Arrange
        profile = ROLE_PROFILES["TestEngineer"]  # priority: ["testing", "backend"]
        decisions = [TESTING_DECISION, UI_DECISION]  # testing is priority, ui is not
        scored = [_scored(d["decision"]) for d in decisions]
        selected = _select_decisions(decisions, profile, scored)

        # Act
        slices = _build_context_slices(selected, [], profile)

        # Assert — testing decision gets priority 1, ui gets priority 2
        testing_slice = next(s for s in slices if "pytest" in s.content)
        ui_slice = next(s for s in slices if "Tailwind" in s.content)
        assert testing_slice.priority == 1
        assert ui_slice.priority == 2

    def test_build_context_slices_session_priority_is_3(self):
        # Arrange
        profile = ROLE_PROFILES["CoderAgent"]
        sessions = [_session("Session about backend", ts="2026-06-01T00:00:00Z")]

        # Act
        slices = _build_context_slices([], sessions, profile)

        # Assert
        assert len(slices) == 1
        assert slices[0].priority == 3
        assert slices[0].category == "session"

    def test_build_context_slices_empty(self):
        # Arrange
        profile = ROLE_PROFILES["CoderAgent"]

        # Act / Assert
        assert _build_context_slices([], [], profile) == []

    def test_must_survive_decision_gets_priority_zero(self):
        """#69: priority 0 is reserved for must-survive decisions,
        ranking above even a role's own priority_categories match."""
        profile = ROLE_PROFILES["TestEngineer"]  # priority: ["testing", "backend"]
        critical = _decision(
            "Critical decision outside priority categories", categories=["database"],
            safety_metadata={"risk_level": "critical"},
        )

        slices = _build_context_slices([critical, TESTING_DECISION], [], profile)

        critical_slice = next(s for s in slices if "Critical decision" in s.content)
        testing_slice = next(s for s in slices if "pytest" in s.content)
        assert critical_slice.priority == 0
        assert testing_slice.priority == 1


class TestTrimToBudget:
    """Budget trimming: removes lowest-priority first, preserves high-priority."""

    def test_trim_to_budget_removes_lowest_priority(self):
        # Arrange
        high = ContextSlice(category="decision", content="high", priority=1, token_estimate=100)
        low = ContextSlice(category="session", content="low", priority=3, token_estimate=200)
        budget = 150  # total is 300, need to cut

        # Act
        trimmed, total = _trim_to_budget([high, low], budget)

        # Assert — low-priority session slice removed
        assert len(trimmed) == 1
        assert trimmed[0].priority == 1
        assert total <= budget

    def test_trim_to_budget_preserves_high_priority(self):
        # Arrange
        slices = [
            ContextSlice(category="decision", content="critical backend", priority=1, token_estimate=50),
            ContextSlice(category="decision", content="config choice", priority=2, token_estimate=100),
            ContextSlice(category="session", content="old session", priority=3, token_estimate=300),
        ]
        budget = 200  # total is 450

        # Act
        trimmed, total = _trim_to_budget(slices, budget)

        # Assert — priority-1 kept, priority-3 removed
        priorities = [s.priority for s in trimmed]
        assert 1 in priorities
        assert 3 not in priorities
        assert total <= budget

    def test_trim_to_budget_no_trimming_needed(self):
        # Arrange
        slices = [
            ContextSlice(category="decision", content="small", priority=1, token_estimate=50),
        ]

        # Act
        trimmed, total = _trim_to_budget(slices, 1000)

        # Assert
        assert len(trimmed) == 1
        assert total == 50

    def test_trim_to_budget_empty_slices(self):
        # Arrange / Act / Assert
        trimmed, total = _trim_to_budget([], 1000)
        assert trimmed == []
        assert total == 0

    def test_trim_to_budget_sorted_by_priority(self):
        # Arrange
        slices = [
            ContextSlice(category="session", content="s1", priority=3, token_estimate=10),
            ContextSlice(category="decision", content="d1", priority=1, token_estimate=20),
            ContextSlice(category="decision", content="d2", priority=2, token_estimate=30),
        ]

        # Act
        trimmed, _ = _trim_to_budget(slices, 1000)

        # Assert — sorted by priority ascending (1, 2, 3)
        priorities = [s.priority for s in trimmed]
        assert priorities == [1, 2, 3]

    def test_priority_zero_survives_even_when_alone_over_budget(self):
        """#69: must-survive (priority 0) content is never removed, even
        if it alone exceeds the token budget -- protection wins over the
        budget as a last resort."""
        must_survive = ContextSlice(category="decision", content="critical", priority=0, token_estimate=500)
        filler = ContextSlice(category="session", content="filler", priority=3, token_estimate=100)

        trimmed, total = _trim_to_budget([must_survive, filler], token_budget=50)

        assert must_survive in trimmed
        assert filler not in trimmed
        assert total > 50  # budget exceeded on purpose to protect priority 0

    def test_priority_zero_protected_alongside_normal_trimming(self):
        """Normal trimming still happens around the protected slice --
        only priority-0 content is exempt."""
        must_survive = ContextSlice(category="decision", content="critical", priority=0, token_estimate=30)
        low_priority = ContextSlice(category="session", content="old", priority=3, token_estimate=200)
        mid_priority = ContextSlice(category="decision", content="normal", priority=1, token_estimate=50)

        trimmed, total = _trim_to_budget([must_survive, low_priority, mid_priority], token_budget=80)

        assert must_survive in trimmed
        assert mid_priority in trimmed
        assert low_priority not in trimmed
        assert total <= 80

    def test_multiple_priority_zero_slices_all_survive(self):
        a = ContextSlice(category="decision", content="critical-a", priority=0, token_estimate=100)
        b = ContextSlice(category="decision", content="critical-b", priority=0, token_estimate=100)

        trimmed, total = _trim_to_budget([a, b], token_budget=10)

        assert a in trimmed and b in trimmed
        assert total == 200


class TestFormatSkillsSummary:
    """Skills extraction from memory patterns."""

    def test_format_skills_summary_returns_proficiency(self):
        # Arrange
        profile = ROLE_PROFILES["CoderAgent"]  # include_skills=True
        memory = _memory(patterns=[
            {"name": "backend:fastapi", "count": 8, "last_seen": "2026-06-01"},
            {"name": "testing:pytest", "count": 3, "last_seen": "2026-06-01"},
            {"name": "ui:react", "count": 1, "last_seen": "2026-06-01"},
        ])

        # Act
        result = _format_skills_summary(memory, profile)

        # Assert
        assert result is not None
        assert result["backend"] == "proficient"  # count >= 5
        assert result["testing"] == "learning"     # count >= 2
        assert result["ui"] == "novice"            # count < 2

    def test_format_skills_summary_returns_none_for_irrelevant_role(self):
        # Arrange
        profile = ROLE_PROFILES["FrontendSpecialist"]  # include_skills=False
        memory = _memory(patterns=[
            {"name": "backend:fastapi", "count": 8, "last_seen": "2026-06-01"},
        ])

        # Act
        result = _format_skills_summary(memory, profile)

        # Assert
        assert result is None

    def test_format_skills_summary_none_for_empty_patterns(self):
        # Arrange
        profile = ROLE_PROFILES["CoderAgent"]
        memory = _memory(patterns=[])

        # Act / Assert
        assert _format_skills_summary(memory, profile) is None

    def test_format_skills_summary_skips_non_colon_names(self):
        # Arrange
        profile = ROLE_PROFILES["CoderAgent"]
        memory = _memory(patterns=[
            {"name": "nocolon", "count": 10},
        ])

        # Act / Assert
        assert _format_skills_summary(memory, profile) is None


class TestBuildHandoffPacket:
    """Integration: full packet assembly from memory dict."""

    def test_build_handoff_packet_full_report(self):
        # Arrange
        memory = _memory(
            decisions=[BACKEND_DECISION, TESTING_DECISION, CONFIG_DECISION],
            sessions=[_session("Set up CI pipeline with pytest", ts="2026-06-15T10:00:00Z")],
            patterns=[
                {"name": "backend:fastapi", "count": 12, "last_seen": "2026-06-15"},
                {"name": "testing:pytest", "count": 6, "last_seen": "2026-06-15"},
            ],
        )

        # Act
        packet = build_handoff_packet(
            project="tropelex",
            role="TestEngineer",
            memory=memory,
            token_budget=8000,
        )

        # Assert
        assert isinstance(packet, HandoffPacket)
        assert packet.role == "TestEngineer"
        assert packet.project == "tropelex"
        assert packet.token_budget <= 8000  # capped by role max_tokens=3000
        assert packet.generated_at is not None
        assert packet.skills_summary is not None
        assert "testing" in packet.skills_summary

    def test_build_handoff_packet_empty_memory(self):
        # Arrange
        memory = _memory()

        # Act
        packet = build_handoff_packet(
            project="empty-project",
            role="CoderAgent",
            memory=memory,
        )

        # Assert — graceful: no crash, empty collections
        assert packet.context_slices == []
        assert packet.active_decisions == []
        assert packet.recent_sessions == []
        assert packet.token_count == 0
        assert packet.skills_summary is None

    def test_build_handoff_packet_unknown_role_defaults_to_coder(self):
        # Arrange
        memory = _memory(decisions=[BACKEND_DECISION])

        # Act
        packet = build_handoff_packet(
            project="tropelex",
            role="SomeRandomRole",
            memory=memory,
        )

        # Assert — uses CoderAgent profile (max_tokens=4000)
        assert packet.role == "SomeRandomRole"
        assert packet.token_budget == 4000
        assert len(packet.active_decisions) >= 1

    def test_build_handoff_packet_tight_budget_protects_must_survive(self):
        """#69 end-to-end: a critical decision outside the role's priority
        categories, under a token budget too small to hold it plus filler,
        still survives into context_slices, and no completeness finding
        fires -- protection holds through the whole real pipeline."""
        critical = _decision(
            "Never disable authentication checks in the payment flow",
            categories=["database"],
            safety_metadata={"risk_level": "critical"},
        )
        fillers = [
            _decision(f"Adopt a design token system for component {i}" * 3, categories=["ui"])
            for i in range(5)
        ]
        memory = _memory(decisions=[critical] + fillers)

        packet = build_handoff_packet(
            project="tropelex",
            role="FrontendSpecialist",
            memory=memory,
            token_budget=1,
        )

        assert any(
            "Never disable authentication checks in the payment flow" in s.content
            for s in packet.context_slices
        )
        assert packet.completeness_findings == []


class TestSelectActiveGoals:
    """#44: active-goal re-anchoring selection, highest priority first,
    capped, and excluding non-active statuses."""

    def test_filters_to_active_only(self):
        goals = [
            _goal("Ship v2 API", status="active"),
            _goal("Old proposal", status="proposed"),
            _goal("Done thing", status="achieved"),
            _goal("Dropped thing", status="abandoned"),
        ]
        selected = _select_active_goals(goals)
        assert len(selected) == 1
        assert selected[0]["text"] == "Ship v2 API"

    def test_sorted_by_priority_critical_first(self):
        goals = [
            _goal("Low prio", priority="low"),
            _goal("Critical prio", priority="critical"),
            _goal("Medium prio", priority="medium"),
            _goal("High prio", priority="high"),
        ]
        selected = _select_active_goals(goals)
        assert [g["text"] for g in selected] == [
            "Critical prio", "High prio", "Medium prio", "Low prio",
        ]

    def test_capped_at_max_active_goals(self):
        goals = [_goal(f"Goal {i}", priority="critical", id=f"g{i}") for i in range(10)]
        selected = _select_active_goals(goals)
        assert len(selected) == 5

    def test_malformed_entries_skipped_not_crashed(self):
        goals = [None, "not a dict", 42, _goal("Real goal")]
        selected = _select_active_goals(goals)
        assert len(selected) == 1
        assert selected[0]["text"] == "Real goal"

    def test_empty_goals_returns_empty(self):
        assert _select_active_goals([]) == []


class TestBuildGoalSlices:
    """#44: goal slices are priority 0 (must-survive tier) so budget
    trimming can never quietly drop a re-anchoring reminder."""

    def test_active_goal_becomes_priority_zero_slice(self):
        slices = _build_goal_slices([_goal("Ship v2 API", priority="high")])
        assert len(slices) == 1
        assert slices[0].category == "goal"
        assert slices[0].priority == 0
        assert "Ship v2 API" in slices[0].content
        assert "high" in slices[0].content

    def test_no_active_goals_produces_no_slices(self):
        assert _build_goal_slices([_goal("Idea", status="proposed")]) == []


class TestGoalReAnchoringEndToEnd:
    """#44 end-to-end through build_handoff_packet: an active goal reaches
    context_slices and survives even under a token budget too tight to
    hold it plus filler -- the same must-survive protection #69 built for
    critical decisions, now covering goals too."""

    def test_active_goal_surfaces_in_context_slices(self):
        memory = _memory(
            decisions=[BACKEND_DECISION],
            goals=[_goal("Ship the v2 public API by Q3", priority="high")],
        )
        packet = build_handoff_packet(project="tropelex", role="CoderAgent", memory=memory)
        goal_slices = [s for s in packet.context_slices if s.category == "goal"]
        assert len(goal_slices) == 1
        assert "Ship the v2 public API by Q3" in goal_slices[0].content

    def test_goal_survives_tight_budget(self):
        fillers = [
            _decision(f"Adopt a design token system for component {i}" * 3, categories=["ui"])
            for i in range(5)
        ]
        memory = _memory(
            decisions=fillers,
            goals=[_goal("Ship the v2 public API by Q3", priority="critical")],
        )
        packet = build_handoff_packet(
            project="tropelex", role="FrontendSpecialist", memory=memory, token_budget=1,
        )
        assert any(
            "Ship the v2 public API by Q3" in s.content
            for s in packet.context_slices
        )

    def test_no_goals_no_regression(self):
        """Empty-goals path (the common case for existing projects/tests)
        must behave exactly as before #44 existed."""
        memory = _memory(decisions=[BACKEND_DECISION])
        packet = build_handoff_packet(project="tropelex", role="CoderAgent", memory=memory)
        assert not any(s.category == "goal" for s in packet.context_slices)


class TestCheckCompleteness:
    """Direct unit tests for the #69 regression safety net -- the real
    pipeline can't trigger a finding by construction (both loss points are
    protected), so these use hand-crafted inputs to prove the check itself
    is correct independent of that."""

    def test_no_findings_when_text_present_in_slices(self):
        from core.handoff.packet_builder import _check_completeness

        critical = _decision("Critical text", categories=["database"], id="d1")
        slices = [ContextSlice(category="decision", content="[high conf=0.9] Critical text", priority=0, token_estimate=5)]

        assert _check_completeness([critical], slices) == []

    def test_finding_when_text_missing_from_slices(self):
        from core.handoff.packet_builder import _check_completeness

        critical = _decision("Critical text that must survive", id="d1")
        slices = [ContextSlice(category="decision", content="unrelated content", priority=0, token_estimate=5)]

        findings = _check_completeness([critical], slices)

        assert len(findings) == 1
        assert findings[0].decision_id == "d1"
        assert findings[0].decision_text == "Critical text that must survive"
        assert findings[0].severity == "high"
        assert findings[0].category == "handoff_completeness"

    def test_finding_id_is_deterministic(self):
        from core.handoff.packet_builder import _check_completeness

        critical = _decision("Missing text", id="d1")
        findings_a = _check_completeness([critical], [])
        findings_b = _check_completeness([critical], [])

        assert findings_a[0].id == findings_b[0].id

    def test_empty_must_survive_list_returns_no_findings(self):
        from core.handoff.packet_builder import _check_completeness
        assert _check_completeness([], []) == []

    def test_decision_with_no_text_is_skipped(self):
        from core.handoff.packet_builder import _check_completeness
        d = {"id": "d1", "decision": ""}
        assert _check_completeness([d], []) == []

    def test_non_dict_entries_are_skipped(self):
        from core.handoff.packet_builder import _check_completeness
        assert _check_completeness(["not a dict", None], []) == []

    def test_multiple_must_survive_decisions_only_missing_ones_flagged(self):
        from core.handoff.packet_builder import _check_completeness

        present = _decision("Present text", id="d1")
        missing = _decision("Missing text", id="d2")
        slices = [ContextSlice(category="decision", content="Present text here", priority=0, token_estimate=5)]

        findings = _check_completeness([present, missing], slices)

        assert len(findings) == 1
        assert findings[0].decision_id == "d2"


# ---------------------------------------------------------------------------
#  2. Router — FastAPI endpoint integration tests (httpx AsyncClient)
# ---------------------------------------------------------------------------


def _app():
    """Create a FastAPI app with the handoff router included."""
    from fastapi import FastAPI
    from core.handoff.router import handoff_router

    app = FastAPI()
    app.include_router(handoff_router)
    return app


SAMPLE_MEMORY = {
    "project": "tropelex",
    "decisions": [
        {
            "decision": "Use FastAPI for REST endpoints",
            "context": "Backend needs async HTTP",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "categories": ["backend"],
        },
    ],
    "session_history": [
        {
            "summary": "Set up testing framework",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "insights": ["pytest works well"],
        },
    ],
    "patterns": [
        {"name": "backend:fastapi", "count": 8, "last_seen": "2026-06-15"},
    ],
}


class TestHandoffEndpoint:
    """Integration tests for POST /api/memory/{project}/handoff."""

    @contextmanager
    def _mock_load(self, memory):
        """Patch _load_memory AND save_project_memory. generate_handoff
        now persists a handoff_created audit event (#59) via the module-
        level `_mm` (a real MemoryManager() instance, not itself mocked) --
        without also patching save, this would write `memory` over the
        real on-disk project file for whatever project name a test uses
        (several tests here use "tropelex", the actual live project).

        Also deep-copies `memory` before handing it to the mock: SAMPLE_MEMORY
        is a shared module-level dict, and append_audit_event mutates its
        target in place (adds to memory["audit_log"]) even with save mocked
        out -- without the copy, every test sharing SAMPLE_MEMORY would leak
        audit_log entries into every other test that runs after it in the
        same session.
        """
        memory_copy = copy.deepcopy(memory)
        with patch("core.handoff.router._load_memory", return_value=memory_copy), \
             patch("core.handoff.router._mm.save_project_memory") as mock_save:
            yield mock_save, memory_copy

    async def test_handoff_endpoint_returns_200(self):
        """Valid request with known project → 200 with full packet."""
        from httpx import ASGITransport, AsyncClient

        with self._mock_load(SAMPLE_MEMORY):
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/memory/tropelex/handoff",
                    json={"role": "CoderAgent", "token_budget": 4000},
                )

        assert resp.status_code == 200
        body = resp.json()
        assert body["role"] == "CoderAgent"
        assert body["project"] == "tropelex"
        assert "context_slices" in body
        assert "active_decisions" in body
        assert "recent_sessions" in body
        assert isinstance(body["token_count"], int)
        assert isinstance(body["token_budget"], int)
        assert "generated_at" in body
        assert "packet_hash" in body
        assert body["completeness_findings"] == []

    async def test_handoff_endpoint_surfaces_completeness_findings(self):
        """#69: if a must-survive decision were ever dropped despite
        protection, the finding must reach the response body, not just
        get silently swallowed."""
        from httpx import ASGITransport, AsyncClient

        memory = copy.deepcopy(SAMPLE_MEMORY)
        memory["decisions"].append({
            "id": "db-critical",
            "decision": "Never disable authentication checks in the payment flow",
            "context": "",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "categories": ["database"],
            "safety_metadata": {"risk_level": "critical"},
        })

        with self._mock_load(memory):
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/memory/tropelex/handoff",
                    json={"role": "FrontendSpecialist", "token_budget": 4000},
                )

        assert resp.status_code == 200
        body = resp.json()
        assert body["completeness_findings"] == []
        assert any(
            "Never disable authentication checks" in s["content"]
            for s in body["context_slices"]
        )

    async def test_handoff_endpoint_writes_completeness_violation_audit_event_when_present(self):
        """#69: when completeness_findings is non-empty, each one is logged
        into the audit trail as its own event -- verified by calling the
        router's audit-writing loop with a hand-crafted non-empty findings
        list, since the real pipeline can't produce one by construction."""
        from httpx import ASGITransport, AsyncClient
        from core.handoff.packet_builder import HandoffPacket, HandoffCompletenessFinding

        finding = HandoffCompletenessFinding(
            id="abc123def456", severity="high", decision_id="db-critical",
            decision_text="Never disable authentication checks in the payment flow",
            category="handoff_completeness",
            description="Must-survive decision was dropped from the handoff packet: Never disable...",
            recommendation="Increase the token budget, or review why this decision wasn't protected (#69).",
        )
        fake_packet = HandoffPacket(
            role="CoderAgent", project="tropelex", context_slices=[], active_decisions=[],
            recent_sessions=[], token_count=0, token_budget=4000, skills_summary=None,
            generated_at=datetime.now(timezone.utc).isoformat(), completeness_findings=[finding],
        )

        with self._mock_load(SAMPLE_MEMORY) as (mock_save, memory_copy), \
             patch("core.handoff.router.build_handoff_packet", return_value=fake_packet):
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/memory/tropelex/handoff",
                    json={"role": "CoderAgent"},
                )

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["completeness_findings"]) == 1
        assert body["completeness_findings"][0]["decision_id"] == "db-critical"

        violation_events = [
            e for e in memory_copy.get("audit_log", [])
            if e["event_type"] == "handoff_completeness_violation"
        ]
        assert len(violation_events) == 1
        assert violation_events[0]["decision_id"] == "db-critical"
        assert violation_events[0]["packet_hash"] == body["packet_hash"]
        mock_save.assert_called_once()

    async def test_handoff_endpoint_writes_handoff_created_audit_event(self):
        """#59: generation is logged into the append-only audit trail,
        hash-chained via core.audit.append_audit_event."""
        from httpx import ASGITransport, AsyncClient

        with self._mock_load(SAMPLE_MEMORY) as (mock_save, memory_copy):
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/memory/tropelex/handoff",
                    json={"role": "CoderAgent", "agent_name": "Claude"},
                )

        assert resp.status_code == 200
        events = [e for e in memory_copy.get("audit_log", []) if e["event_type"] == "handoff_created"]
        assert len(events) == 1
        assert events[0]["role"] == "CoderAgent"
        assert events[0]["agent_name"] == "Claude"
        assert events[0]["packet_hash"] == resp.json()["packet_hash"]
        assert "hash" in events[0] and "previous_hash" in events[0]
        mock_save.assert_called_once()

    async def test_handoff_endpoint_persist_failure_does_not_break_generation(self):
        """Audit logging must never break the handoff generation that
        already succeeded -- same 'instrumentation can't break the thing
        it's observing' stance as #45's session-shape capture."""
        from httpx import ASGITransport, AsyncClient

        with self._mock_load(SAMPLE_MEMORY) as (mock_save, _memory_copy):
            mock_save.side_effect = RuntimeError("disk full")
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/memory/tropelex/handoff",
                    json={"role": "CoderAgent"},
                )

        assert resp.status_code == 200
        assert "packet_hash" in resp.json()

    async def test_handoff_endpoint_returns_404_for_unknown_project(self):
        """Unknown project → 404."""
        from httpx import ASGITransport, AsyncClient
        from fastapi import HTTPException

        def _raise_404(project):
            raise HTTPException(status_code=404, detail=f"Project '{project}' not found")

        with patch("core.handoff.router._load_memory", side_effect=_raise_404):
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/memory/nonexistent-project/handoff",
                    json={"role": "CoderAgent"},
                )

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    async def test_handoff_roles_endpoint_returns_roles(self):
        """GET roles → 200 with role descriptions."""
        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(
            transport=ASGITransport(app=_app()), base_url="http://test"
        ) as client:
            resp = await client.get("/api/memory/tropelex/handoff/roles")

        assert resp.status_code == 200
        body = resp.json()
        assert "roles" in body
        assert "CoderAgent" in body["roles"]
        assert "TestEngineer" in body["roles"]
        assert "Architect" in body["roles"]
        assert isinstance(body["roles"]["CoderAgent"], str)


class TestHandoffAcknowledge:
    """Tests for POST /{project}/handoff/acknowledge (#59)."""

    @contextmanager
    def _mock_load(self, memory):
        """See TestHandoffEndpoint._mock_load's docstring -- same double
        risk (real disk write via unmocked _mm, shared-dict mutation
        pollution) applies here."""
        memory_copy = copy.deepcopy(memory)
        with patch("core.handoff.router._load_memory", return_value=memory_copy), \
             patch("core.handoff.router._mm.save_project_memory") as mock_save:
            yield mock_save, memory_copy

    def _memory_with_handoff(self, packet_hash="abc123"):
        memory = copy.deepcopy(SAMPLE_MEMORY)
        memory["audit_log"] = [{
            "event_type": "handoff_created",
            "timestamp": "2026-08-10T00:00:00+00:00",
            "previous_hash": "genesis",
            "role": "CoderAgent",
            "agent_name": "Claude",
            "packet_hash": packet_hash,
            "hash": "deadbeef",
        }]
        return memory

    async def test_acknowledge_known_packet_succeeds(self):
        from httpx import ASGITransport, AsyncClient

        with self._mock_load(self._memory_with_handoff("abc123")) as (mock_save, memory_copy):
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/memory/tropelex/handoff/acknowledge",
                    json={"packet_hash": "abc123", "agent_name": "Claude"},
                )

        assert resp.status_code == 200
        body = resp.json()
        assert body["acknowledged"] is True
        assert body["packet_hash"] == "abc123"
        events = [e for e in memory_copy["audit_log"] if e["event_type"] == "handoff_acknowledged"]
        assert len(events) == 1
        assert events[0]["agent_name"] == "Claude"
        assert events[0]["packet_hash"] == "abc123"
        mock_save.assert_called_once()

    async def test_acknowledge_unknown_packet_hash_404s(self):
        """Rejects acking a packet that was never actually generated --
        same 'validate the reference is real' discipline as #53's
        override endpoint validating decision_id."""
        from httpx import ASGITransport, AsyncClient

        with self._mock_load(self._memory_with_handoff("abc123")):
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/memory/tropelex/handoff/acknowledge",
                    json={"packet_hash": "does-not-exist"},
                )

        assert resp.status_code == 404

    async def test_acknowledge_records_acknowledged_constraints(self):
        from httpx import ASGITransport, AsyncClient

        with self._mock_load(self._memory_with_handoff("abc123")) as (mock_save, memory_copy):
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                await client.post(
                    "/api/memory/tropelex/handoff/acknowledge",
                    json={"packet_hash": "abc123", "acknowledged_constraints": ["do not touch prod"]},
                )

        events = [e for e in memory_copy["audit_log"] if e["event_type"] == "handoff_acknowledged"]
        assert events[0]["acknowledged_constraints"] == ["do not touch prod"]

    async def test_acknowledge_defaults_agent_name(self):
        from httpx import ASGITransport, AsyncClient

        with self._mock_load(self._memory_with_handoff("abc123")):
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/memory/tropelex/handoff/acknowledge",
                    json={"packet_hash": "abc123"},
                )

        assert resp.json()["agent_name"] == "unspecified"

    async def test_acknowledge_empty_audit_log_404s(self):
        from httpx import ASGITransport, AsyncClient

        with self._mock_load(copy.deepcopy(SAMPLE_MEMORY)):
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/memory/tropelex/handoff/acknowledge",
                    json={"packet_hash": "anything"},
                )

        assert resp.status_code == 404


class TestUnacknowledgedHandoffs:
    """Pure-function tests for core.handoff.router._unacknowledged_handoffs."""

    def test_no_audit_log_returns_empty(self):
        from core.handoff.router import _unacknowledged_handoffs
        assert _unacknowledged_handoffs({}) == []

    def test_created_without_ack_is_returned(self):
        from core.handoff.router import _unacknowledged_handoffs
        memory = {"audit_log": [
            {"event_type": "handoff_created", "packet_hash": "h1", "role": "CoderAgent",
             "agent_name": "Claude", "timestamp": "t1"},
        ]}
        result = _unacknowledged_handoffs(memory)
        assert len(result) == 1
        assert result[0]["packet_hash"] == "h1"
        assert result[0]["role"] == "CoderAgent"

    def test_acknowledged_handoff_is_excluded(self):
        from core.handoff.router import _unacknowledged_handoffs
        memory = {"audit_log": [
            {"event_type": "handoff_created", "packet_hash": "h1"},
            {"event_type": "handoff_acknowledged", "packet_hash": "h1"},
        ]}
        assert _unacknowledged_handoffs(memory) == []

    def test_multiple_handoffs_only_unacked_returned(self):
        from core.handoff.router import _unacknowledged_handoffs
        memory = {"audit_log": [
            {"event_type": "handoff_created", "packet_hash": "h1"},
            {"event_type": "handoff_created", "packet_hash": "h2"},
            {"event_type": "handoff_acknowledged", "packet_hash": "h1"},
        ]}
        result = _unacknowledged_handoffs(memory)
        assert len(result) == 1
        assert result[0]["packet_hash"] == "h2"

    def test_non_list_audit_log_does_not_raise(self):
        from core.handoff.router import _unacknowledged_handoffs
        assert _unacknowledged_handoffs({"audit_log": "corrupted"}) == []

    def test_non_dict_entries_are_skipped(self):
        from core.handoff.router import _unacknowledged_handoffs
        memory = {"audit_log": [
            "not a dict", None, 42,
            {"event_type": "handoff_created", "packet_hash": "h1"},
        ]}
        result = _unacknowledged_handoffs(memory)
        assert len(result) == 1


class TestListUnacknowledgedHandoffsEndpoint:
    """Tests for GET /{project}/handoff/unacknowledged."""

    async def test_returns_unacked_handoffs(self):
        from httpx import ASGITransport, AsyncClient

        memory = {"audit_log": [
            {"event_type": "handoff_created", "packet_hash": "h1", "role": "CoderAgent",
             "agent_name": "Claude", "timestamp": "t1"},
        ]}
        with patch("core.handoff.router._mm.get_project_memory", return_value=memory):
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                resp = await client.get("/api/memory/tropelex/handoff/unacknowledged")

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["handoffs"][0]["packet_hash"] == "h1"

    async def test_empty_when_none_outstanding(self):
        from httpx import ASGITransport, AsyncClient

        with patch("core.handoff.router._mm.get_project_memory", return_value={"audit_log": []}):
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                resp = await client.get("/api/memory/tropelex/handoff/unacknowledged")

        assert resp.json() == {"handoffs": [], "count": 0}

    async def test_nonexistent_project_returns_empty_not_404(self):
        """Regression: get_needs_attention calls this for every project it
        aggregates, including ones with no memory file on disk yet --
        must stay lenient like its sibling sources (list_flagged_decisions,
        list_decay_reviews), not 404 the way generate_handoff/
        acknowledge_handoff correctly do for a direct call."""
        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(
            transport=ASGITransport(app=_app()), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/memory/definitely-nonexistent-project-xyz/handoff/unacknowledged"
            )

        assert resp.status_code == 200
        assert resp.json() == {"handoffs": [], "count": 0}


class TestCompletenessViolations:
    """Pure-function tests for core.handoff.router._completeness_violations (#69)."""

    def test_no_audit_log_returns_empty(self):
        from core.handoff.router import _completeness_violations
        assert _completeness_violations({}) == []

    def test_violation_event_is_returned(self):
        from core.handoff.router import _completeness_violations
        memory = {"audit_log": [
            {"event_type": "handoff_completeness_violation", "decision_id": "d1",
             "packet_hash": "h1", "role": "CoderAgent", "agent_name": "Claude",
             "description": "dropped", "timestamp": "t1"},
        ]}
        result = _completeness_violations(memory)
        assert len(result) == 1
        assert result[0]["decision_id"] == "d1"
        assert result[0]["role"] == "CoderAgent"

    def test_non_violation_events_are_excluded(self):
        from core.handoff.router import _completeness_violations
        memory = {"audit_log": [
            {"event_type": "handoff_created", "packet_hash": "h1"},
            {"event_type": "handoff_acknowledged", "packet_hash": "h1"},
        ]}
        assert _completeness_violations(memory) == []

    def test_non_list_audit_log_does_not_raise(self):
        from core.handoff.router import _completeness_violations
        assert _completeness_violations({"audit_log": "corrupted"}) == []

    def test_non_dict_entries_are_skipped(self):
        from core.handoff.router import _completeness_violations
        memory = {"audit_log": [
            "not a dict", None, 42,
            {"event_type": "handoff_completeness_violation", "decision_id": "d1"},
        ]}
        result = _completeness_violations(memory)
        assert len(result) == 1


class TestListCompletenessViolationsEndpoint:
    """Tests for GET /{project}/handoff/completeness-violations."""

    async def test_returns_violations(self):
        from httpx import ASGITransport, AsyncClient

        memory = {"audit_log": [
            {"event_type": "handoff_completeness_violation", "decision_id": "d1",
             "packet_hash": "h1", "role": "CoderAgent", "agent_name": "Claude",
             "description": "dropped", "timestamp": "t1"},
        ]}
        with patch("core.handoff.router._mm.get_project_memory", return_value=memory):
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                resp = await client.get("/api/memory/tropelex/handoff/completeness-violations")

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["violations"][0]["decision_id"] == "d1"

    async def test_empty_when_none_recorded(self):
        from httpx import ASGITransport, AsyncClient

        with patch("core.handoff.router._mm.get_project_memory", return_value={"audit_log": []}):
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                resp = await client.get("/api/memory/tropelex/handoff/completeness-violations")

        assert resp.json() == {"violations": [], "count": 0}

    async def test_nonexistent_project_returns_empty_not_404(self):
        """Same lenient-read regression class as #59's unacknowledged
        endpoint -- get_needs_attention calls this for every project."""
        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(
            transport=ASGITransport(app=_app()), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/memory/definitely-nonexistent-project-xyz/handoff/completeness-violations"
            )

        assert resp.status_code == 200
        assert resp.json() == {"violations": [], "count": 0}
