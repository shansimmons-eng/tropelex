"""
Tests for Digital Twin Personas — persona builder pure functions.
Covers: identify_strengths, identify_weaknesses, build_persona,
        generate_summary_text, suggest_review_focus.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from core.personas.persona_builder import (
    build_persona,
    generate_summary_text,
    identify_strengths,
    identify_weaknesses,
    suggest_review_focus,
)
from core.personas import Ok, Err, PersonaSummary
from core.personas.router import _load_agent_skills
from core.tropebook.web.server import app


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


# ── _load_agent_skills — agent scoping (regression: router.py bug fix) ──────
#
# GET /{project}/personas/{agent} took a real `agent` path param but
# _load_agent_skills(project) ignored it, so every agent requested got back
# the identical project-wide persona. Fixed by giving _load_agent_skills an
# `agent` arg that filters skills_by_agent/sessions down to that agent only.

class TestLoadAgentSkillsAgentScoping:
    @pytest.fixture
    def project(self, tmp_path, monkeypatch):
        from core.agent_skills import AgentSkillGraph
        import core.personas.router as router_module

        monkeypatch.setattr(router_module, "BASE_DIR", tmp_path)
        graph = AgentSkillGraph(str(tmp_path))
        graph.record_session_outcome("proj", "manual", ["ui"], "success", agent_name="Claude")
        graph.record_session_outcome("proj", "manual", ["ui"], "failure", agent_name="Gemini")
        return "proj"

    def test_agent_none_returns_full_aggregate(self, project):
        data = _load_agent_skills(project, agent=None)
        assert data["skills"]["ui"]["attempts"] == 2

    def test_agent_given_scopes_to_that_agent_only(self, project):
        claude_data = _load_agent_skills(project, agent="Claude")
        gemini_data = _load_agent_skills(project, agent="Gemini")
        assert claude_data["skills"]["ui"]["score"] == 1.0
        assert gemini_data["skills"]["ui"]["score"] == 0.0

    def test_agent_scoping_filters_sessions_too(self, project):
        claude_data = _load_agent_skills(project, agent="Claude")
        assert len(claude_data["sessions"]) == 1
        assert claude_data["sessions"][0]["agent"] == "Claude"

    def test_unknown_agent_returns_empty_skills_not_error(self, project):
        data = _load_agent_skills(project, agent="NoSuchAgent")
        assert data["skills"] == {}
        assert data["sessions"] == []


# ── Router regression: GET /{project}/personas/{agent} distinguishes agents ─

class TestPersonaRouterAgentRegression:
    @pytest.fixture
    def client(self):
        return TestClient(app)

    @pytest.fixture
    def project(self):
        return f"test_personas_{uuid.uuid4().hex[:8]}"

    def _record_skill(self, client, project, agent, outcome):
        res = client.post(
            f"/api/memory/{project}/agent-skills/record",
            json={"session_type": "manual", "categories": ["ui"], "outcome": outcome, "agent_name": agent},
        )
        assert res.status_code == 200, res.text

    def test_distinct_agents_get_distinct_personas(self, client, project):
        self._record_skill(client, project, "Claude", "success")
        self._record_skill(client, project, "Gemini", "failure")

        claude = client.get(f"/api/memory/{project}/personas/Claude")
        gemini = client.get(f"/api/memory/{project}/personas/Gemini")
        assert claude.status_code == 200
        assert gemini.status_code == 200

        claude_accuracy = claude.json()["persona"]["accuracy_by_category"]
        gemini_accuracy = gemini.json()["persona"]["accuracy_by_category"]
        assert claude_accuracy != gemini_accuracy
        assert claude_accuracy["ui"] == 1.0
        assert gemini_accuracy["ui"] == 0.0

    def test_all_personas_endpoint_returns_one_per_real_agent(self, client, project):
        """GET /{project}/personas (no agent) previously blended every agent
        into a single fake persona keyed by the *project* name, which showed
        up in the dashboard as an "Unknown" persona with no strengths or
        weaknesses. It must now return one real persona per distinct agent
        that has actually recorded skill outcomes."""
        self._record_skill(client, project, "Claude", "success")
        self._record_skill(client, project, "Gemini", "failure")

        res = client.get(f"/api/memory/{project}/personas")
        assert res.status_code == 200
        personas = res.json()["personas"]
        assert len(personas) == 2

        by_agent = {p["persona"]["agent_name"]: p["persona"] for p in personas}
        assert set(by_agent.keys()) == {"Claude", "Gemini"}
        assert by_agent["Claude"]["accuracy_by_category"]["ui"] == 1.0
        assert by_agent["Gemini"]["accuracy_by_category"]["ui"] == 0.0

    def test_record_response_echoes_normalized_name_not_raw_input(self, client, project):
        """POST /agent-skills/record must report back the name it actually
        persisted. Previously it echoed the raw request value verbatim, so
        a caller sending an alias spelling ("claude-sonnet-5") was told
        that name was saved -- but agent-skills/record normalizes before
        writing, so the real stored key was "Claude" and the reported name
        never actually existed in storage, silently vanishing from every
        agent list on the next refresh."""
        res = client.post(
            f"/api/memory/{project}/agent-skills/record",
            json={"session_type": "manual", "categories": ["ui"], "outcome": "success", "agent_name": "claude-sonnet-5"},
        )
        assert res.status_code == 200, res.text
        assert res.json()["agent_name"] == "Claude"

    def test_known_aliases_produce_one_persona_not_two(self, client, project):
        """Skill outcomes recorded under known-alias spellings of the same
        agent ("Claude" vs "Claude Code") must collapse into one persona."""
        self._record_skill(client, project, "Claude", "success")
        self._record_skill(client, project, "Claude Code", "success")
        self._record_skill(client, project, "Gemini", "failure")

        res = client.get(f"/api/memory/{project}/personas")
        assert res.status_code == 200
        personas = res.json()["personas"]
        assert len(personas) == 2

        by_agent = {p["persona"]["agent_name"]: p["persona"] for p in personas}
        assert set(by_agent.keys()) == {"Claude", "Gemini"}

    def test_all_personas_endpoint_falls_back_to_project_aggregate_when_no_agents_tagged(self, client, project):
        """Legacy data recorded before agent tagging existed has no agent
        names to iterate — the endpoint should still return something usable
        (the old project-wide aggregate) rather than an empty list."""
        res = client.post(
            f"/api/memory/{project}/agent-skills/record",
            json={"session_type": "manual", "categories": ["ui"], "outcome": "success"},
        )
        assert res.status_code == 200, res.text

        res = client.get(f"/api/memory/{project}/personas")
        assert res.status_code == 200
        personas = res.json()["personas"]
        assert len(personas) == 1
        assert personas[0]["persona"]["agent_name"] == project

    def test_all_personas_endpoint_returns_empty_list_when_no_skills_file_exists(self, client, project):
        """A project with zero skill outcomes ever recorded has no
        agent_skills file on disk at all -- distinct from the fallback
        case above (file exists, just untagged). Previously this hit
        _load_agent_skills' 404-on-missing-file path (meant for "give me
        this specific named agent"), so a brand-new project's Personas
        panel would error instead of showing the graceful empty state the
        frontend already has ("No personas built yet")."""
        res = client.get(f"/api/memory/{project}/personas")
        assert res.status_code == 200
        assert res.json() == {"project": project, "personas": [], "count": 0}
