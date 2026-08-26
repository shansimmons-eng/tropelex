"""
Tests for Decision Tree.
"""

from core.decision_tree import (
    DecisionTree,
    _extract_keywords,
    _find_caused_by,
    _gen_id,
    _is_revert,
    _similarity,
)


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


class TestFindCausedBy:
    """Regression coverage: _find_caused_by used to flag a match on ANY
    single keyword shared with another decision's text, co-occurring
    ANYWHERE (not adjacent, not actually related) with a generic word like
    "after"/"due to". Found live: one decision whose context happened to
    mention "memory" -- about the most common word possible in a memory
    system -- ended up falsely claiming 131 of the project's ~306 decisions
    as its own causes. Now returns [] unconditionally; these tests prove
    that holds even against inputs specifically engineered to have
    triggered the old heuristic."""

    def test_always_returns_empty(self):
        assert _find_caused_by({"context": "x"}, [{"id": "a", "decision": "x"}]) == []

    def test_empty_on_the_exact_shape_that_used_to_false_positive(self):
        # Old behavior: one shared keyword ("memory") + one signal word
        # ("after") anywhere in the text was enough to match, regardless
        # of whether the two decisions have anything to do with each other.
        new = {
            "context": "Parallelized the dashboard init calls after profiling "
            "showed 15s load times, caching the memory payload.",
            "rationale": "",
        }
        existing = [
            {"id": "unrelated-1", "decision": "Use MySQL for the primary database"},
            {"id": "unrelated-2", "decision": "Added dark mode to the memory viewer"},
            {"id": "unrelated-3", "decision": "Documented the CLI in the README"},
        ]
        assert _find_caused_by(new, existing) == []

    def test_add_decision_never_auto_creates_a_caused_by_edge(self):
        tree = DecisionTree()
        tree.add_decision({
            "decision": "Use MySQL for the primary database",
            "context": "",
            "timestamp": "2026-01-01T00:00:00Z",
        })
        did = tree.add_decision({
            "decision": "Parallelize dashboard init calls, cache memory payload",
            "context": "After profiling showed 15s load times due to sequential "
            "API calls and a large memory payload.",
            "timestamp": "2026-01-02T00:00:00Z",
        })
        node = tree.get_decision(did)
        assert all(e["relationship"] != "caused_by" for e in node["edges"])


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

    def test_real_id_wins_over_hash(self):
        """Regression: a decision carrying both a real id (set by
        MemoryManager's backfill) and a git hash (from import) must use
        the id as its node key -- every other decision-lookup endpoint
        (interpretability, versions, safety review) matches by the real
        id, not the hash. Preferring hash here made /decision-tree/timeline
        and /decision-tree/{id} return a value none of those other
        endpoints recognized, 404ing "Inspect" for every git-imported
        decision that had already been backfilled with a real id."""
        tree = DecisionTree()
        did = tree.add_decision({
            "decision": "Fixed: normalize agent identity in Slack capture too",
            "timestamp": "2026-08-04T00:00:00Z",
            "hash": "d1c3d671",
            "id": "8ac9ee9258c3",
            "source": "git",
        })
        assert did == "8ac9ee9258c3"
        assert tree.get_decision("8ac9ee9258c3") is not None
        assert tree.get_decision("d1c3d671") is None

    def test_revert_matching_still_uses_hash_when_id_differs(self):
        """The revert-detection heuristic matches against the git hash
        prefix specifically, not the node id -- must keep working once id
        and hash diverge (real id present alongside hash)."""
        tree = DecisionTree()
        tree.add_decision({
            "decision": "Added feature: dark mode",
            "timestamp": "2026-01-01T00:00:00Z",
            "hash": "abc1234",
            "id": "111111111111",
        })
        did2 = tree.add_decision({
            "decision": "Revert abc1234",
            "timestamp": "2026-01-02T00:00:00Z",
            "hash": "def5678",
            "id": "222222222222",
            "is_revert": True,
            "reverts": "abc1234",
        })
        node2 = tree.get_decision(did2)
        reverts_edges = [e for e in node2["edges"] if e["relationship"] == "reverts"]
        assert len(reverts_edges) == 1
        assert reverts_edges[0]["target"] == "111111111111"

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


class TestGitImportedDecisionsAreInspectableEndToEnd:
    """The dashboard's "Inspect" action on a timeline row hits three
    endpoints with whatever id /decision-tree/timeline returned:
    /decision-tree/{id}, /interpretability/{id}, /decisions/{id}/versions.
    The latter two match by the decision's real, persisted id -- if the
    timeline hands back the git hash instead (id != hash), those two 404
    while the first one (self-consistently using the same key internally)
    doesn't, which is exactly what was reported: a whole span of
    git-imported decisions 404ing "Decision not found" under Inspect."""

    def test_timeline_and_lookup_endpoints_agree_on_id(self):
        import uuid
        from fastapi.testclient import TestClient

        from core.memory.manager import MemoryManager
        from core.tropebook.web.server import app

        client = TestClient(app)
        project = f"test_decision_tree_{uuid.uuid4().hex[:8]}"
        client.post("/api/memory", json={"project_name": project})

        mm = MemoryManager()
        memory = mm.get_project_memory(project)
        memory.setdefault("decisions", []).append({
            "timestamp": "2026-08-04T00:00:00+00:00",
            "decision": "Fixed: normalize agent identity in Slack capture too",
            "context": "From git commit d1c3d671 on 2026-08-04",
            "hash": "d1c3d671",
            "source": "git",
            "id": "8ac9ee9258c3",  # already backfilled, like real data
        })
        mm.save_project_memory(project, memory)

        timeline = client.get(f"/api/memory/{project}/decision-tree/timeline").json()
        assert timeline["timeline"][0]["id"] == "8ac9ee9258c3"

        returned_id = timeline["timeline"][0]["id"]
        detail = client.get(f"/api/memory/{project}/decision-tree/{returned_id}")
        interp = client.get(f"/api/memory/{project}/interpretability/{returned_id}")
        versions = client.get(f"/api/memory/{project}/decisions/{returned_id}/versions")

        assert detail.status_code == 200
        assert interp.status_code == 200
        assert versions.status_code == 200
