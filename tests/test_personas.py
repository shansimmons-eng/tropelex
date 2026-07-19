"""
Tests for Digital Twin Personas — persona builder pure functions.
Covers: identify_strengths, identify_weaknesses, build_persona,
        generate_summary_text, suggest_review_focus.
"""

import pytest
from core.personas.persona_builder import (
    build_persona,
    generate_summary_text,
    identify_strengths,
    identify_weaknesses,
    suggest_review_focus,
)
from core.personas import Ok, Err, PersonaSummary


# ── identify_strengths ─────────────────────────────────────────────────────

class TestIdentifyStrengths:
    def test_finds_expert_categories(self):
        skills = {
            "backend": {"score": 0.9, "attempts": 5},
            "frontend": {"score": 0.3, "attempts": 5},
        }
        assert identify_strengths(skills) == ["backend"]

    def test_requires_minimum_attempts(self):
        skills = {"backend": {"score": 0.9, "attempts": 2}}
        assert identify_strengths(skills) == []

    def test_empty_skills(self):
        assert identify_strengths({}) == []

    def test_sorted_output(self):
        skills = {
            "zeta": {"score": 0.8, "attempts": 5},
            "alpha": {"score": 0.9, "attempts": 5},
        }
        assert identify_strengths(skills) == ["alpha", "zeta"]


# ── identify_weaknesses ────────────────────────────────────────────────────

class TestIdentifyWeaknesses:
    def test_finds_novice_categories(self):
        skills = {
            "backend": {"score": 0.2, "attempts": 5},
            "frontend": {"score": 0.8, "attempts": 5},
        }
        assert identify_weaknesses(skills) == ["backend"]

    def test_requires_minimum_attempts(self):
        skills = {"backend": {"score": 0.2, "attempts": 1}}
        assert identify_weaknesses(skills) == []

    def test_boundary_at_04(self):
        skills = {"backend": {"score": 0.4, "attempts": 5}}
        assert identify_weaknesses(skills) == ["backend"]


# ── build_persona ──────────────────────────────────────────────────────────

class TestBuildPersona:
    def test_empty_agent_name(self):
        result = build_persona({}, "")
        assert isinstance(result, Err)

    def test_no_skill_data(self):
        result = build_persona({"skills": {}}, "agent1")
        assert isinstance(result, Ok)
        assert result.value.strengths == []
        assert "No skill data" in result.value.summary_text

    def test_with_skills(self):
        agent_skills = {
            "skills": {
                "backend": {"score": 0.9, "attempts": 10},
                "frontend": {"score": 0.2, "attempts": 8},
                "testing": {"score": 0.6, "attempts": 5},
            },
            "sessions": ["s1", "s2"],
        }
        result = build_persona(agent_skills, "agent1")
        assert isinstance(result, Ok)
        persona = result.value
        assert "backend" in persona.strengths
        assert "frontend" in persona.weaknesses
        assert persona.total_sessions == 2
        assert len(persona.preferred_categories) <= 3

    def test_accuracy_by_category(self):
        agent_skills = {
            "skills": {"backend": {"score": 0.85, "attempts": 5}},
            "sessions": [],
        }
        result = build_persona(agent_skills, "a")
        assert result.value.accuracy_by_category["backend"] == pytest.approx(0.85, abs=0.01)


# ── generate_summary_text ─────────────────────────────────────────────────

class TestGenerateSummaryText:
    def test_with_strengths_and_weaknesses(self):
        persona = PersonaSummary(
            agent_name="test-agent",
            strengths=["backend"],
            weaknesses=["frontend"],
            preferred_categories=["backend"],
            accuracy_by_category={"backend": 0.9, "frontend": 0.2},
            summary_text="",
            total_sessions=5,
        )
        text = generate_summary_text(persona)
        assert "Excels at backend" in text
        assert "Needs improvement in frontend" in text

    def test_no_patterns(self):
        persona = PersonaSummary(
            agent_name="test-agent",
            strengths=[],
            weaknesses=[],
            preferred_categories=[],
            accuracy_by_category={},
            summary_text="",
            total_sessions=0,
        )
        text = generate_summary_text(persona)
        assert "No significant patterns" in text


# ── suggest_review_focus ──────────────────────────────────────────────────

class TestSuggestReviewFocus:
    def test_prioritizes_weaknesses(self):
        persona = PersonaSummary(
            agent_name="a",
            strengths=["backend"],
            weaknesses=["frontend"],
            preferred_categories=["backend"],
            accuracy_by_category={"frontend": 0.2, "backend": 0.9},
            summary_text="",
            total_sessions=5,
        )
        result = suggest_review_focus(persona)
        assert "frontend" in result.focus_areas
        assert "Known weaknesses" in result.reasoning

    def test_fallback_to_preferred(self):
        persona = PersonaSummary(
            agent_name="a",
            strengths=[],
            weaknesses=[],
            preferred_categories=["backend", "testing"],
            accuracy_by_category={},
            summary_text="",
            total_sessions=5,
        )
        result = suggest_review_focus(persona)
        assert "backend" in result.focus_areas or "testing" in result.focus_areas

    def test_includes_borderline(self):
        persona = PersonaSummary(
            agent_name="a",
            strengths=[],
            weaknesses=[],
            preferred_categories=[],
            accuracy_by_category={"api": 0.5, "db": 0.45, "ui": 0.8},
            summary_text="",
            total_sessions=5,
        )
        result = suggest_review_focus(persona)
        assert "api" in result.focus_areas or "db" in result.focus_areas
