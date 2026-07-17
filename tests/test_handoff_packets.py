"""
Tests for Agent Handoff Packets (core.handoff).

Covers packet_builder (pure functions) and router (FastAPI endpoints).
Uses httpx AsyncClient for endpoint tests; all external I/O is mocked.
"""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from core.handoff.packet_builder import (
    ContextSlice,
    HandoffPacket,
    ROLE_PROFILES,
    _build_context_slices,
    _estimate_tokens,
    _format_skills_summary,
    _select_decisions,
    _select_sessions,
    _trim_to_budget,
    build_handoff_packet,
)


# ---------------------------------------------------------------------------
#  Helpers — realistic test data factories
# ---------------------------------------------------------------------------

def _decision(text, context="", categories=None, ts=None):
    """Factory: build a decision dict with realistic fields."""
    return {
        "decision": text,
        "context": context,
        "timestamp": ts or datetime.now(timezone.utc).isoformat(),
        "categories": categories or [],
    }


def _session(summary, ts=None, insights=None):
    """Factory: build a session-history entry."""
    return {
        "summary": summary,
        "timestamp": ts or datetime.now(timezone.utc).isoformat(),
        "insights": insights or [],
    }


def _memory(decisions=None, sessions=None, patterns=None):
    """Factory: build a full memory dict."""
    return {
        "decisions": decisions or [],
        "session_history": sessions or [],
        "patterns": patterns or [],
    }


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

    def _mock_load(self, memory):
        """Return a patched _load_memory that yields our test memory."""
        return patch("core.handoff.router._load_memory", return_value=memory)

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
