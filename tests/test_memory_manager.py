"""Tests for core.memory.manager.MemoryManager"""

import pytest

from core.memory.manager import MemoryManager


@pytest.fixture
def mm(tmp_path):
    """Create a MemoryManager with a temp directory."""
    return MemoryManager(base_path=str(tmp_path))


class TestMemoryManagerCRUD:
    def test_create_and_get_project(self, mm):
        mm.add_decision("test-proj", "Used FastAPI", "REST API needed async support")
        memory = mm.get_project_memory("test-proj")
        assert memory["project_name"] == "test-proj"
        assert len(memory["decisions"]) == 1
        assert memory["decisions"][0]["decision"] == "Used FastAPI"

    def test_get_nonexistent_project_returns_empty(self, mm):
        memory = mm.get_project_memory("nonexistent")
        assert memory["project_name"] == "nonexistent"
        assert memory["decisions"] == []

    def test_save_and_reload(self, mm):
        mm.add_decision("proj-a", "Decision 1", "Context 1")
        memory = mm.get_project_memory("proj-a")
        assert len(memory["decisions"]) == 1

    def test_set_preference(self, mm):
        mm.set_preference("proj", "ui", "mobile-first")
        val = mm.get_preference("proj", "ui")
        assert val == "mobile-first"

    def test_get_preference_default(self, mm):
        val = mm.get_preference("proj", "missing", default="fallback")
        assert val == "fallback"

    def test_append_to_history(self, mm):
        mm.append_to_history("proj", {"type": "session", "summary": "Built UI"})
        memory = mm.get_project_memory("proj")
        assert len(memory["session_history"]) == 1
        assert memory["session_history"][0]["summary"] == "Built UI"

    def test_list_projects(self, mm):
        mm.add_decision("proj-a", "d", "c")
        mm.add_decision("proj-b", "d", "c")
        projects = mm.list_projects()
        assert "proj-a" in projects
        assert "proj-b" in projects

    def test_context_generation(self, mm):
        mm.add_decision("proj", "Used React", "Frontend needed SPA")
        mm.set_preference("proj", "theme", "dark")
        context = mm.get_context_for_project("proj")
        assert "proj" in context
        assert "Used React" in context
        assert "theme: dark" in context


class TestPathTraversal:
    def test_safe_path_strips_dotslash(self, mm):
        # _safe_path uses Path().name which strips directory components
        path = mm._safe_path("../../../etc/passwd")
        assert path.name == "passwd.json"

    def test_safe_path_strips_slash(self, mm):
        path = mm._safe_path("proj/subdir")
        assert path.name == "subdir.json"

    def test_safe_path_rejects_special_chars(self, mm):
        with pytest.raises(ValueError, match="Invalid project name"):
            mm._safe_path("proj name with spaces")

    def test_safe_path_accepts_valid_names(self, mm):
        path = mm._safe_path("my-project_123")
        assert path.name == "my-project_123.json"
