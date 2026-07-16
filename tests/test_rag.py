"""
Tests for Memory-Driven RAG & Cross-Pollination.
"""

from core.rag import CrossPollinator, MemoryRAG, _keyword_match_score


class TestKeywordMatchScore:
    def test_exact_match(self):
        assert _keyword_match_score("fastapi backend", "fastapi backend server") == 1.0

    def test_partial_match(self):
        score = _keyword_match_score("fastapi authentication", "fastapi backend server")
        assert 0 < score < 1

    def test_no_match(self):
        assert _keyword_match_score("python backend", "react frontend styling") == 0.0

    def test_empty_query(self):
        assert _keyword_match_score("", "some text") == 0.0

    def test_stop_words_ignored(self):
        score = _keyword_match_score("the fastapi", "fastapi server")
        assert score == 1.0  # "the" is a stop word


class TestMemoryRAG:
    def test_retrieve_decisions(self):
        class MockMM:
            def get_project_memory(self, name):
                return {
                    "decisions": [
                        {"decision": "Use FastAPI for backend", "context": "Async support"},
                        {"decision": "Use React for frontend", "context": "Component model"},
                    ],
                    "session_history": [],
                    "quick_captures": [],
                }

        rag = MemoryRAG(MockMM())
        results = rag.retrieve("test", "fastapi backend")
        assert len(results) > 0
        assert any("FastAPI" in r["text"] for r in results)

    def test_retrieve_returns_sorted(self):
        class MockMM:
            def get_project_memory(self, name):
                return {
                    "decisions": [
                        {"decision": "Use Python", "context": ""},
                        {"decision": "Use Python FastAPI for backend API", "context": ""},
                    ],
                    "session_history": [],
                    "quick_captures": [],
                }

        rag = MemoryRAG(MockMM())
        results = rag.retrieve("test", "python fastapi backend")
        assert results[0]["score"] >= results[-1]["score"]

    def test_retrieve_with_context(self):
        class MockMM:
            def get_project_memory(self, name):
                return {
                    "decisions": [
                        {"decision": "Use FastAPI", "context": "For async"},
                    ],
                    "session_history": [],
                    "quick_captures": [],
                }

        rag = MemoryRAG(MockMM())
        context = rag.retrieve_with_context("test", "fastapi")
        assert "Relevant Memory" in context
        assert "FastAPI" in context

    def test_retrieve_empty(self):
        class MockMM:
            def get_project_memory(self, name):
                return {"decisions": [], "session_history": [], "quick_captures": []}

        rag = MemoryRAG(MockMM())
        results = rag.retrieve("test", "nonexistent topic")
        assert results == []


class TestCrossPollinator:
    def test_find_transferable(self):
        class MockMM:
            def list_projects(self):
                return ["project-a", "project-b"]
            def get_project_memory(self, name):
                if name == "project-a":
                    return {
                        "tech_stack": ["Python", "FastAPI"],
                        "decisions": [{"decision": "Use FastAPI for backend", "context": ""}],
                    }
                return {
                    "tech_stack": ["Python", "React"],
                    "decisions": [
                        {"decision": "Use FastAPI authentication middleware", "context": "JWT support"},
                    ],
                }

        cp = CrossPollinator(MockMM())
        transfers = cp.find_transferable_knowledge("project-a", "fastapi auth")
        assert len(transfers) > 0
        assert transfers[0]["project"] == "project-b"

    def test_no_transferable(self):
        class MockMM:
            def list_projects(self):
                return ["project-a", "project-b"]
            def get_project_memory(self, name):
                if name == "project-a":
                    return {"tech_stack": ["Python"], "decisions": []}
                return {"tech_stack": ["Go"], "decisions": []}

        cp = CrossPollinator(MockMM())
        transfers = cp.find_transferable_knowledge("project-a")
        assert transfers == []

    def test_briefing(self):
        class MockMM:
            def list_projects(self):
                return ["a", "b"]
            def get_project_memory(self, name):
                if name == "a":
                    return {"tech_stack": ["Python", "FastAPI"], "decisions": []}
                return {
                    "tech_stack": ["Python", "FastAPI"],
                    "decisions": [{"decision": "Use FastAPI caching", "context": "Redis"}],
                }

        cp = CrossPollinator(MockMM())
        briefing = cp.get_project_briefing("a", "fastapi caching")
        assert "Cross-Project" in briefing

    def test_suggest_approaches(self):
        class MockMM:
            def list_projects(self):
                return ["a", "b"]
            def get_project_memory(self, name):
                if name == "a":
                    return {"tech_stack": ["Python"], "decisions": []}
                return {
                    "tech_stack": ["Python"],
                    "decisions": [
                        {"decision": "Use Redis for caching", "context": ""},
                        {"decision": "Use Redis for session store", "context": ""},
                    ],
                }

        cp = CrossPollinator(MockMM())
        approaches = cp.suggest_approaches("a", "redis caching")
        # Should deduplicate similar decisions
        assert len(approaches) <= 2

    def test_self_exclusion(self):
        class MockMM:
            def list_projects(self):
                return ["a"]
            def get_project_memory(self, name):
                return {"tech_stack": ["Python"], "decisions": []}

        cp = CrossPollinator(MockMM())
        transfers = cp.find_transferable_knowledge("a")
        assert transfers == []
