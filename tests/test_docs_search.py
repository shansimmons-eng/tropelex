"""
Tests for core.docs_search -- the GUIDE/FAQ/Getting Started/API
Reference/README search index behind the dashboard sidebar search
widget's "Documentation" category.

Runs against the real site/*.html and README.md content (not fixtures/
mocks) -- same "measure actual behavior" conviction as Drift-Bench's own
scenarios (core/driftbench/scenarios.py): a fixture-based test could stay
green forever while the real pages drift out from under it.
"""

from __future__ import annotations

from core.docs_search import (
    DocEntry,
    _slugify,
    build_docs_index,
    search_docs,
)


class TestSlugify:
    def test_lowercases_and_hyphenates(self):
        assert _slugify("What is Tropelex?") == "what-is-tropelex"

    def test_strips_punctuation(self):
        assert _slugify("Core Projects & Decisions") == "core-projects-decisions"

    def test_no_leading_trailing_hyphens(self):
        assert _slugify("  Getting Started!  ") == "getting-started"


class TestBuildDocsIndex:
    def test_returns_entries_from_every_source(self):
        index = build_docs_index()
        sources = {e.source for e in index}
        assert sources == {"Guide", "FAQ", "Getting Started", "API Reference", "README"}

    def test_entries_have_nonempty_titles(self):
        index = build_docs_index()
        assert len(index) > 20  # real content, not a near-empty stub
        assert all(e.title.strip() for e in index)

    def test_faq_question_entries_have_anchors(self):
        """FAQ's <details id="..."> wraps each question -- confirms the
        streaming parser's ancestor-id resolution works (the heading
        itself has no id; only its <details> ancestor does), not just
        the direct-id-on-heading case the other pages use. The page's
        own <h1> title and a footer heading outside any <details> are
        real content with no id at all -- not asserted on here, since
        they aren't actual FAQ questions."""
        index = build_docs_index()
        faq_by_title = {e.title: e for e in index if e.source == "FAQ"}
        known_question = faq_by_title["What are Ghost Decisions and why do they matter?"]
        assert known_question.anchor == "what-are-ghost-decisions-and-why-do-they-matter"
        assert known_question.url == "/faq#what-are-ghost-decisions-and-why-do-they-matter"

    def test_getting_started_entries_have_anchors(self):
        """Regression: these headings had no id at all before #search --
        this asserts the retrofit (site/getting-started.html) is real,
        not just that the parser degrades gracefully without one."""
        index = build_docs_index()
        entries = [e for e in index if e.source == "Getting Started"]
        assert entries
        assert any(e.anchor == "clone-and-install" for e in entries)

    def test_readme_entries_link_to_github_anchor(self):
        index = build_docs_index()
        readme_entries = [e for e in index if e.source == "README"]
        assert readme_entries
        assert all(e.url.startswith("https://github.com/shansimmons-eng/tropelex#") for e in readme_entries)

    def test_material_symbols_icon_ligature_text_excluded_from_titles(self):
        """Getting Started/API Reference headings wrap a Material Symbols
        icon span (e.g. <span class="material-symbols-outlined">checklist
        </span> Requirements) -- that ligature text renders as an icon
        glyph, not a word, and must not leak into the indexed title."""
        index = build_docs_index()
        requirements = next(e for e in index if e.source == "Getting Started" and e.anchor == "requirements")
        assert requirements.title == "Requirements"
        assert "checklist" not in requirements.title


class TestSearchDocs:
    def _index(self):
        return build_docs_index()

    def test_finds_a_known_topic_across_sources(self):
        results = search_docs(self._index(), "ghost decisions")
        assert results
        sources = {r["source"] for r in results}
        assert "Guide" in sources or "FAQ" in sources

    def test_results_are_sorted_by_score_descending(self):
        results = search_docs(self._index(), "ghost decisions drift")
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_empty_query_returns_nothing(self):
        assert search_docs(self._index(), "") == []

    def test_stopword_only_query_returns_nothing(self):
        assert search_docs(self._index(), "the a is") == []

    def test_unrelated_query_returns_no_results(self):
        results = search_docs(self._index(), "xyzzy plugh frotz")
        assert results == []

    def test_limit_is_respected(self):
        results = search_docs(self._index(), "decision", limit=3)
        assert len(results) <= 3

    def test_result_shape(self):
        results = search_docs(self._index(), "ghost decisions", limit=1)
        result = results[0]
        assert set(result.keys()) == {"source", "title", "url", "snippet", "score"}


class TestSearchDocsWithSyntheticEntries:
    """Ranking behavior against small, controlled fixtures -- independent
    of whatever the real site content happens to contain, so these
    assertions don't drift if a page's wording changes later."""

    def _entries(self):
        return [
            DocEntry(source="Guide", title="Ghost Decisions", anchor="ghost", url="/guide#ghost",
                     text="Detects silent code drift against recorded decisions."),
            DocEntry(source="FAQ", title="What is context compression?", anchor="cc", url="/faq#cc",
                     text="Strips filler before it reaches the model."),
            DocEntry(source="README", title="Unrelated", anchor="u", url="https://x#u",
                     text="Completely unrelated content about something else."),
        ]

    def test_title_match_outranks_body_only_match(self):
        results = search_docs(self._entries(), "ghost decisions")
        assert results[0]["title"] == "Ghost Decisions"

    def test_min_score_filters_weak_matches(self):
        results = search_docs(self._entries(), "ghost decisions", min_score=0.99)
        assert all(r["score"] >= 0.99 for r in results)
