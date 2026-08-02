"""
Tests for Agent Skill Graph & Prompt Genealogy.
"""

import tempfile
from pathlib import Path

import pytest

from core.agent_skills import AgentSkillGraph, PromptGenealogy, _proficiency_label


class TestProficiencyLabel:
    def test_expert(self):
        assert _proficiency_label(0.95) == "expert"
    def test_proficient(self):
        assert _proficiency_label(0.75) == "proficient"
    def test_competent(self):
        assert _proficiency_label(0.55) == "competent"
    def test_learning(self):
        assert _proficiency_label(0.35) == "learning"
    def test_novice(self):
        assert _proficiency_label(0.1) == "novice"


class TestAgentSkillGraph:
    @pytest.fixture
    def graph(self, tmp_path):
        return AgentSkillGraph(str(tmp_path))

    def test_record_and_get(self, graph):
        graph.record_session_outcome("proj", "manual", ["ui", "backend"], "success")
        skills = graph.get_skills("proj")
        assert len(skills) == 2
        assert skills[0]["score"] == 1.0

    def test_multiple_sessions(self, graph):
        graph.record_session_outcome("proj", "manual", ["ui"], "success")
        graph.record_session_outcome("proj", "manual", ["ui"], "success")
        graph.record_session_outcome("proj", "manual", ["ui"], "failure")
        skills = graph.get_skills("proj")
        assert len(skills) == 1
        assert skills[0]["attempts"] == 3
        assert skills[0]["successes"] == 2
        assert skills[0]["failures"] == 1

    def test_strengths(self, graph):
        for _ in range(5):
            graph.record_session_outcome("proj", "manual", ["ui"], "success")
        strengths = graph.get_strengths("proj")
        assert "ui" in strengths

    def test_weaknesses(self, graph):
        for _ in range(5):
            graph.record_session_outcome("proj", "manual", ["database"], "failure")
        weaknesses = graph.get_weaknesses("proj")
        assert "database" in weaknesses

    def test_briefing(self, graph):
        graph.record_session_outcome("proj", "manual", ["ui"], "success")
        briefing = graph.get_briefing("proj")
        assert "Agent Proficiency" in briefing

    def test_empty_briefing(self, graph):
        assert graph.get_briefing("empty") == ""

    def test_proficiency_levels(self, graph):
        for _ in range(10):
            graph.record_session_outcome("proj", "manual", ["ui"], "success")
        skills = graph.get_skills("proj")
        assert skills[0]["proficiency"] == "expert"


class TestAgentSkillGraphPerAgent:
    """agent_name isolation — added when tracking became multi-agent aware."""

    @pytest.fixture
    def graph(self, tmp_path):
        return AgentSkillGraph(str(tmp_path))

    def test_default_agent_name_is_unspecified(self, graph):
        graph.record_session_outcome("proj", "manual", ["ui"], "success")
        assert graph.get_skills("proj", agent_name="unspecified")[0]["attempts"] == 1

    def test_two_agents_are_isolated(self, graph):
        graph.record_session_outcome("proj", "manual", ["ui"], "success", agent_name="Claude")
        graph.record_session_outcome("proj", "manual", ["ui"], "failure", agent_name="Gemini")

        claude_skills = graph.get_skills("proj", agent_name="Claude")
        gemini_skills = graph.get_skills("proj", agent_name="Gemini")
        assert claude_skills[0]["score"] == 1.0
        assert gemini_skills[0]["score"] == 0.0

    def test_unknown_agent_returns_empty(self, graph):
        graph.record_session_outcome("proj", "manual", ["ui"], "success", agent_name="Claude")
        assert graph.get_skills("proj", agent_name="Gemini") == []

    def test_aggregate_unaffected_by_agent_name_arg(self, graph):
        """agent_name=None (default) must keep reading the original project-wide
        'skills' bucket exactly as before per-agent tracking existed — this is
        the backward-compatibility guarantee the feature was built around."""
        graph.record_session_outcome("proj", "manual", ["ui"], "success", agent_name="Claude")
        graph.record_session_outcome("proj", "manual", ["ui"], "failure", agent_name="Gemini")

        aggregate = graph.get_skills("proj")
        assert len(aggregate) == 1
        assert aggregate[0]["attempts"] == 2
        assert aggregate[0]["successes"] == 1
        assert aggregate[0]["score"] == 0.5

    def test_agent_name_is_stripped_and_blank_falls_back(self, graph):
        graph.record_session_outcome("proj", "manual", ["ui"], "success", agent_name="  Claude  ")
        graph.record_session_outcome("proj", "manual", ["ui"], "success", agent_name="   ")
        assert graph.get_skills("proj", agent_name="Claude")[0]["attempts"] == 1
        assert graph.get_skills("proj", agent_name="unspecified")[0]["attempts"] == 1

    def test_strengths_weaknesses_briefing_scoped_per_agent(self, graph):
        for _ in range(5):
            graph.record_session_outcome("proj", "manual", ["ui"], "success", agent_name="Claude")
        for _ in range(5):
            graph.record_session_outcome("proj", "manual", ["ui"], "failure", agent_name="Gemini")

        assert graph.get_strengths("proj", agent_name="Claude") == ["ui"]
        assert graph.get_strengths("proj", agent_name="Gemini") == []
        assert graph.get_weaknesses("proj", agent_name="Gemini") == ["ui"]
        assert "Strong at" in graph.get_briefing("proj", agent_name="Claude")
        assert "Needs care" in graph.get_briefing("proj", agent_name="Gemini")

    def test_list_agents_excludes_unspecified_and_sorts(self, graph):
        graph.record_session_outcome("proj", "manual", ["ui"], "success", agent_name="Gemini")
        graph.record_session_outcome("proj", "manual", ["ui"], "success", agent_name="Claude")
        graph.record_session_outcome("proj", "manual", ["ui"], "success")  # default -> unspecified
        assert graph.list_agents("proj") == ["Claude", "Gemini"]

    def test_list_agents_empty_project(self, graph):
        assert graph.list_agents("empty") == []

    def test_sessions_record_which_agent(self, graph):
        graph.record_session_outcome("proj", "manual", ["ui"], "success", agent_name="Claude")
        data = graph._load("proj")
        assert data["sessions"][-1]["agent"] == "Claude"

    def test_reading_pre_agent_file_is_unaffected(self, graph):
        """A memory/agent_skills/{project}.json written before this feature
        existed has no skills_by_agent key at all — get_skills(agent_name=None)
        must still return its data exactly as before."""
        import json

        legacy = {
            "project": "legacy",
            "skills": {"ui": {"attempts": 2, "successes": 2, "failures": 0, "score": 1.0}},
            "sessions": [],
            "created": "2026-01-01T00:00:00+00:00",
        }
        graph._skills_file("legacy").write_text(json.dumps(legacy))

        skills = graph.get_skills("legacy")
        assert skills[0]["attempts"] == 2
        assert graph.get_skills("legacy", agent_name="Claude") == []
        assert graph.list_agents("legacy") == []


class TestPromptGenealogy:
    @pytest.fixture
    def pg(self, tmp_path):
        return PromptGenealogy(str(tmp_path))

    def test_record_compression(self, pg):
        prompt_id = pg.record_compression("proj", "original text", "compressed", "level1")
        assert prompt_id
        assert len(prompt_id) == 12

    def test_record_outcome(self, pg):
        prompt_id = pg.record_compression("proj", "original", "compressed", "level1")
        pg.record_outcome("proj", prompt_id, "good")
        stats = pg.get_stats("proj")
        assert stats["with_outcomes"] == 1
        assert stats["success_rate"] == 1.0

    def test_strategy_rankings(self, pg):
        id1 = pg.record_compression("proj", "orig1", "comp1", "level1")
        id2 = pg.record_compression("proj", "orig2", "comp2", "level1")
        pg.record_outcome("proj", id1, "good")
        pg.record_outcome("proj", id2, "good")

        rankings = pg.get_strategy_rankings("proj")
        assert len(rankings) == 1
        assert rankings[0]["strategy"] == "level1"
        assert rankings[0]["effectiveness"] == 1.0

    def test_best_strategy(self, pg):
        for i in range(5):
            pid = pg.record_compression("proj", f"orig{i}", f"comp{i}", "level2")
            pg.record_outcome("proj", pid, "good")

        assert pg.get_best_strategy("proj") == "level2"

    def test_best_strategy_insufficient_data(self, pg):
        pid = pg.record_compression("proj", "orig", "comp", "level1")
        pg.record_outcome("proj", pid, "good")
        # Only 1 use, need 3 minimum
        assert pg.get_best_strategy("proj") is None

    def test_stats(self, pg):
        pid = pg.record_compression("proj", "original text here", "compressed", "level1", 0.5)
        pg.record_outcome("proj", pid, "good")
        stats = pg.get_stats("proj")
        assert stats["total_prompts"] == 1
        assert stats["avg_compression_ratio"] == 0.5

    def test_empty_stats(self, pg):
        stats = pg.get_stats("empty")
        assert stats["total_prompts"] == 0
