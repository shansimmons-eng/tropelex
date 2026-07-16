"""
Tests for Research Chains.
"""

import json
import tempfile
from pathlib import Path

import pytest

from core.research_chains import ResearchChain, ResearchChainManager


class TestResearchChain:
    def test_create(self):
        chain = ResearchChain("How to scale FastAPI?")
        assert chain.goal == "How to scale FastAPI?"
        assert chain.status == "active"
        assert len(chain.steps) == 0

    def test_add_step(self):
        chain = ResearchChain("Test goal")
        step = chain.add_step(
            "scaling strategies",
            [{"title": "Guide to scaling", "summary": "Use workers"}],
            gaps=["Need more on caching"],
        )
        assert step["step_number"] == 1
        assert len(chain.steps) == 1

    def test_get_next_queries(self):
        chain = ResearchChain("Test")
        chain.add_step("q1", [], gaps=["deep dive caching", "worker config"])
        queries = chain.get_next_queries()
        assert len(queries) == 2
        assert "deep dive caching" in queries

    def test_get_all_findings(self):
        chain = ResearchChain("Test")
        chain.add_step("q1", [{"title": "A"}, {"title": "B"}])
        chain.add_step("q2", [{"title": "C"}])
        findings = chain.get_all_findings()
        assert len(findings) == 3

    def test_add_link(self):
        chain = ResearchChain("Test")
        chain.add_link("Finding A", "Finding B", "related")
        assert len(chain.links) == 1

    def test_complete(self):
        chain = ResearchChain("Test")
        chain.complete("Found 3 key insights")
        assert chain.status == "completed"
        assert "3 key insights" in chain.synthesis

    def test_abandon(self):
        chain = ResearchChain("Test")
        chain.abandon("No results")
        assert chain.status == "abandoned"

    def test_serialization(self):
        chain = ResearchChain("Test goal")
        chain.add_step("q1", [{"title": "A"}], gaps=["gap1"])
        chain.complete("Done")

        data = chain.to_dict()
        restored = ResearchChain.from_dict(data)

        assert restored.goal == chain.goal
        assert len(restored.steps) == len(chain.steps)
        assert restored.status == "completed"


class TestResearchChainManager:
    @pytest.fixture
    def manager(self, tmp_path):
        return ResearchChainManager(str(tmp_path))

    def test_save_and_load(self, manager):
        chain = ResearchChain("Test goal")
        chain.add_step("query 1", [{"title": "Result 1"}])
        chain_id = manager.save_chain("test-project", chain)
        assert chain_id

        loaded = manager.load_chain("test-project", chain_id)
        assert loaded is not None
        assert loaded.goal == "Test goal"

    def test_list_chains(self, manager):
        chain1 = ResearchChain("Goal 1")
        chain2 = ResearchChain("Goal 2")
        manager.save_chain("test-project", chain1)
        manager.save_chain("test-project", chain2)

        chains = manager.list_chains("test-project")
        assert len(chains) == 2

    def test_list_by_status(self, manager):
        active = ResearchChain("Active goal")
        completed = ResearchChain("Completed goal")
        completed.complete("Done")

        manager.save_chain("test-project", active)
        manager.save_chain("test-project", completed)

        active_chains = manager.list_chains("test-project", status="active")
        assert len(active_chains) == 1

        completed_chains = manager.list_chains("test-project", status="completed")
        assert len(completed_chains) == 1

    def test_delete_chain(self, manager):
        chain = ResearchChain("To delete")
        chain_id = manager.save_chain("test-project", chain)
        assert manager.delete_chain("test-project", chain_id) is True
        assert manager.load_chain("test-project", chain_id) is None

    def test_delete_nonexistent(self, manager):
        assert manager.delete_chain("test-project", "nonexistent") is False

    def test_empty_project(self, manager):
        assert manager.list_chains("empty") == []
        assert manager.load_chain("empty", "nonexistent") is None
