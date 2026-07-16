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
