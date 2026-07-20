"""Tests for core.tropebook.tropebook.Tropebook"""

import pytest

from core.tropebook.tropebook import SourceType, Tropebook


@pytest.fixture
def tb(tmp_path):
    """Create a Tropebook with a temp directory."""
    return Tropebook(storage_path=str(tmp_path / "tropebook"))


class TestCitationCRUD:
    def test_add_citation(self, tb):
        cid = tb.add("Python Docs", "https://docs.python.org", summary="Official docs")
        assert cid is not None
        assert len(cid) == 8

    def test_get_citation(self, tb):
        cid = tb.add("Python Docs", "https://docs.python.org")
        citation = tb.get(cid)
        assert citation is not None
        assert citation.title == "Python Docs"
        assert citation.url == "https://docs.python.org"

    def test_get_nonexistent_returns_none(self, tb):
        assert tb.get("nonexistent") is None

    def test_update_citation(self, tb):
        cid = tb.add("Title", "https://example.com")
        tb.update(cid, summary="Updated summary")
        citation = tb.get(cid)
        assert citation.summary == "Updated summary"

    def test_delete_citation(self, tb):
        cid = tb.add("To Delete", "https://delete.me")
        assert tb.delete(cid) is True
        assert tb.get(cid) is None

    def test_delete_nonexistent_returns_false(self, tb):
        assert tb.delete("nonexistent") is False

    def test_duplicate_url_updates(self, tb):
        cid1 = tb.add("First", "https://dup.com")
        cid2 = tb.add("Second", "https://dup.com", summary="new")
        assert cid1 == cid2  # same citation updated
        assert tb.get(cid1).summary == "new"

    def test_add_with_tags_and_entities(self, tb):
        cid = tb.add(
            "Tagged",
            "https://tagged.com",
            tags=["python", "async"],
            entities=["Guido"],
        )
        citation = tb.get(cid)
        assert "python" in citation.tags
        assert "Guido" in citation.entities


class TestSearch:
    def test_search_by_title(self, tb):
        tb.add("Python Documentation", "https://docs.python.org")
        tb.add("JavaScript Guide", "https://developer.mozilla.org")
        results = tb.search("python")
        assert len(results) == 1
        cid, cite = results[0]
        assert cite.title == "Python Documentation"

    def test_search_by_summary(self, tb):
        tb.add("FastAPI", "https://fastapi.tiangolo.com", summary="Modern Python web framework")
        results = tb.search("web framework")
        assert len(results) == 1

    def test_search_by_tag(self, tb):
        tb.add("Item", "https://item.com", tags=["machine-learning"])
        results = tb.search("machine learning")
        assert len(results) == 1

    def test_search_no_results(self, tb):
        tb.add("Python", "https://python.org")
        results = tb.search("xyznonexistent")
        assert len(results) == 0


class TestGraph:
    def test_link_citations(self, tb):
        cid1 = tb.add("A", "https://a.com")
        cid2 = tb.add("B", "https://b.com")
        tb.link(cid1, cid2, "related_to")
        assert len(tb.graph.edges) == 1
        assert tb.graph.edges[0]["relationship"] == "related_to"

    def test_get_related(self, tb):
        cid1 = tb.add("A", "https://a.com")
        cid2 = tb.add("B", "https://b.com")
        tb.link(cid1, cid2, "related_to")
        related = tb.get_related(cid1)
        assert cid2 in related


class TestIndex:
    def test_find_by_url(self, tb):
        tb.add("Test", "https://find.me")
        found = tb.find_by_url("https://find.me")
        assert found is not None
        assert found.title == "Test"

    def test_find_by_tag(self, tb):
        tb.add("Tagged", "https://tagged.com", tags=["rust"])
        results = tb.find_by_tag("rust")
        assert len(results) == 1

    def test_find_by_source(self, tb):
        tb.add("Brave", "https://brave.com", source_type=SourceType.BRAVE_SEARCH)
        results = tb.find_by_source(SourceType.BRAVE_SEARCH)
        assert len(results) == 1


class TestImportExport:
    def test_import_deep_research(self, tb):
        data = {
            "sources": [
                {"title": "Source 1", "url": "https://s1.com", "snippet": "First"},
                {"title": "Source 2", "url": "https://s2.com", "snippet": "Second"},
            ]
        }
        count = tb.import_from_deep_research(data)
        assert count == 2

    def test_export_json(self, tb):
        tb.add("Export", "https://export.com")
        exported = tb.export_json()
        assert "citations" in exported
        assert "graph" in exported
        assert len(exported["citations"]) == 1

    def test_stats(self, tb):
        tb.add("A", "https://a.com", tags=["t1"])
        stats = tb.stats()
        assert stats["total_citations"] == 1
        assert stats["total_tags"] == 1


class TestMergeDuplicates:
    def test_merge_duplicates(self, tb):
        # Manually create duplicates by bypassing the URL check in add()
        tb.add("A", "https://same.com")
        from core.tropebook.tropebook import Citation

        dup = Citation(title="B", url="https://same.com", summary="second")
        tb.citations["dup1"] = dup
        tb.graph.add_node("dup1", "citation", {"title": "B", "url": "https://same.com"})
        tb._build_index()
        tb._save()

        count = tb.merge_duplicates()
        assert count >= 1
