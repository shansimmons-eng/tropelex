"""
Tests for Decision Tree.
"""

from core.decision_tree import DecisionTree, _extract_keywords, _similarity, _is_revert, _gen_id


class TestExtractKeywords:
    def test_extracts_meaningful_words(self):
        kw = _extract_keywords("Switched from REST to GraphQL for better performance")
        assert "rest" in kw
        assert "graphql" in kw
        assert "performance" in kw
        assert "the" not in kw
        assert "from" not in kw

    def test_filters_short_words(self):
        kw = _extract_keywords("Add an X to Y")
        assert "an" not in kw  # 2 chars, filtered by regex
        assert "to" not in kw  # stop word

    def test_empty_string(self):
        assert _extract_keywords("") == set()


class TestSimilarity:
    def test_identical_sets(self):
        assert _similarity({"a", "b"}, {"a", "b"}) == 1.0

    def test_no_overlap(self):
        assert _similarity({"a"}, {"b"}) == 0.0

    def test_partial_overlap(self):
        sim = _similarity({"a", "b", "c"}, {"b", "c", "d"})
        assert 0.4 < sim < 0.8

    def test_empty_sets(self):
        assert _similarity(set(), {"a"}) == 0.0
        assert _similarity({"a"}, set()) == 0.0


class TestIsRevert:
    def test_revert_keyword(self):
        assert _is_revert("Revert: switched back to old API") is True

    def test_normal_decision(self):
        assert _is_revert("Added dark mode support") is False


class TestDecisionTree:
    def test_add_and_get(self):
        tree = DecisionTree()
        did = tree.add_decision({
            "decision": "Switched from REST to GraphQL",
            "context": "Performance reasons",
            "timestamp": "2026-01-01T00:00:00Z",
        })
        node = tree.get_decision(did)
        assert node is not None
        assert "GraphQL" in node["decision"]

    def test_auto_detects_related(self):
        tree = DecisionTree()
        tree.add_decision({
            "decision": "Use FastAPI for backend API server endpoints",
            "timestamp": "2026-01-01T00:00:00Z",
        })
        did2 = tree.add_decision({
            "decision": "Use FastAPI for backend authentication endpoints",
            "timestamp": "2026-01-02T00:00:00Z",
        })
        node2 = tree.get_decision(did2)
        # Should detect relationship due to high keyword overlap
        assert len(node2["edges"]) > 0

    def test_auto_detects_supersedes_on_revert(self):
        tree = DecisionTree()
        tree.add_decision({
            "decision": "Added feature: dark mode",
            "timestamp": "2026-01-01T00:00:00Z",
            "hash": "abc1234",
        })
        did2 = tree.add_decision({
            "decision": "Reverted: dark mode caused issues",
            "timestamp": "2026-01-02T00:00:00Z",
            "hash": "def5678",
        })
        node2 = tree.get_decision(did2)
        # Should have a supersedes or related edge
        rel_types = [e["relationship"] for e in node2["edges"]]
        assert any(r in rel_types for r in ["supersedes", "related_to"])

    def test_timeline_sorted(self):
        tree = DecisionTree()
        tree.add_decision({
            "decision": "Second decision",
            "timestamp": "2026-01-02T00:00:00Z",
        })
        tree.add_decision({
            "decision": "First decision",
            "timestamp": "2026-01-01T00:00:00Z",
        })
        timeline = tree.get_timeline()
        assert len(timeline) == 2
        assert timeline[0]["decision"] == "First decision"

    def test_from_decisions(self):
        decisions = [
            {"decision": "Use React for frontend", "timestamp": "2026-01-01T00:00:00Z"},
            {"decision": "Use TypeScript with React", "timestamp": "2026-01-02T00:00:00Z"},
        ]
        tree = DecisionTree.from_decisions(decisions)
        assert len(tree.nodes) == 2

    def test_serialization_roundtrip(self):
        tree = DecisionTree()
        tree.add_decision({
            "decision": "Use FastAPI",
            "timestamp": "2026-01-01T00:00:00Z",
        })
        data = tree.to_dict()
        restored = DecisionTree.from_dict(data)
        assert len(restored.nodes) == 1
        assert len(restored.edges) == len(tree.edges)

    def test_stats(self):
        tree = DecisionTree()
        tree.add_decision({"decision": "Use Python", "timestamp": "2026-01-01T00:00:00Z"})
        tree.add_decision({"decision": "Use Python 3.12", "timestamp": "2026-01-02T00:00:00Z"})
        stats = tree.stats()
        assert stats["total_decisions"] == 2

    def test_empty_tree(self):
        tree = DecisionTree()
        assert tree.get_timeline() == []
        assert tree.get_chains() == []
        assert tree.stats()["total_decisions"] == 0

    def test_gen_id_deterministic(self):
        d1 = {"decision": "test", "timestamp": "2026-01-01"}
        d2 = {"decision": "test", "timestamp": "2026-01-01"}
        assert _gen_id(d1) == _gen_id(d2)
