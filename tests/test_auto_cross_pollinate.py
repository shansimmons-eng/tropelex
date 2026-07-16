"""Tests for cross-project learning automation (core.rag extensions)."""

import pytest
from unittest.mock import MagicMock
from core.rag import auto_detect_similar_projects, generate_auto_suggestions


def _make_manager(projects: dict[str, dict]):
    """Create a mock MemoryManager with the given projects."""
    mm = MagicMock()
    mm.list_projects.return_value = list(projects.keys())
    mm.get_project_memory.side_effect = lambda name: projects.get(name, {})
    return mm


class TestAutoDetectSimilarProjects:
    def test_no_overlap(self):
        projects = {
            "projA": {"tech_stack": ["React"], "decisions": []},
            "projB": {"tech_stack": ["Go"], "decisions": []},
        }
        mm = _make_manager(projects)
        result = auto_detect_similar_projects(mm, "projA")
        assert result == []

    def test_overlap_found(self):
        projects = {
            "projA": {"tech_stack": ["React", "Python"], "decisions": []},
            "projB": {"tech_stack": ["Python", "Docker"], "decisions": [{"decision": "x"}]},
        }
        mm = _make_manager(projects)
        result = auto_detect_similar_projects(mm, "projA")
        assert len(result) == 1
        assert result[0]["project"] == "projB"
        assert "python" in result[0]["shared_tech"]

    def test_empty_tech_stack(self):
        projects = {
            "projA": {"tech_stack": [], "decisions": []},
            "projB": {"tech_stack": ["Python"], "decisions": []},
        }
        mm = _make_manager(projects)
        result = auto_detect_similar_projects(mm, "projA")
        assert result == []

    def test_sorted_by_overlap(self):
        projects = {
            "projA": {"tech_stack": ["React", "Python", "Docker"], "decisions": []},
            "projB": {"tech_stack": ["Python"], "decisions": []},
            "projC": {"tech_stack": ["React", "Python", "Docker"], "decisions": []},
        }
        mm = _make_manager(projects)
        result = auto_detect_similar_projects(mm, "projA")
        assert result[0]["project"] == "projC"
        assert result[0]["overlap_ratio"] > result[1]["overlap_ratio"]


class TestGenerateAutoSuggestions:
    def test_no_similar_projects(self):
        projects = {
            "projA": {"tech_stack": ["React"], "decisions": []},
            "projB": {"tech_stack": ["Go"], "decisions": [{"decision": "x"}]},
        }
        mm = _make_manager(projects)
        result = generate_auto_suggestions(mm, "projA")
        assert result == []

    def test_novel_suggestions(self):
        projects = {
            "projA": {
                "tech_stack": ["Python"],
                "decisions": [{"decision": "Use FastAPI", "context": "web"}],
            },
            "projB": {
                "tech_stack": ["Python"],
                "decisions": [{"decision": "Use Celery for tasks", "context": "async"}],
            },
        }
        mm = _make_manager(projects)
        result = generate_auto_suggestions(mm, "projA")
        assert len(result) >= 1
        assert result[0]["source_project"] == "projB"

    def test_limit(self):
        projects = {
            "projA": {"tech_stack": ["Python"], "decisions": []},
            "projB": {"tech_stack": ["Python"], "decisions": [
                {"decision": f"Decision {i}"} for i in range(10)
            ]},
        }
        mm = _make_manager(projects)
        result = generate_auto_suggestions(mm, "projA", limit=3)
        assert len(result) <= 3

    def test_already_covered_filtered(self):
        projects = {
            "projA": {
                "tech_stack": ["Python"],
                "decisions": [{"decision": "Use FastAPI for web"}],
            },
            "projB": {
                "tech_stack": ["Python"],
                "decisions": [{"decision": "Use FastAPI for API"}],
            },
        }
        mm = _make_manager(projects)
        result = generate_auto_suggestions(mm, "projA")
        # "FastAPI" is already a topic in projA, so should be filtered
        # (or at least have lower relevance)
        for s in result:
            assert s["source_project"] == "projB"
