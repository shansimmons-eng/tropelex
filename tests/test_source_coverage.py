"""Tests for core/tropebook/source_coverage.py (wishlist #88): per-source
citation volume and "useful vs noise" via decision citation_ids. Pure-
function tests -- no HTTP, no MemoryManager.
"""

from __future__ import annotations

from core.tropebook.source_coverage import classify_source_domain, compute_source_coverage


class TestClassifySourceDomain:
    def test_reddit(self):
        assert classify_source_domain("https://reddit.com/r/programming/comments/x") == "reddit"

    def test_reddit_subdomain(self):
        assert classify_source_domain("https://old.reddit.com/r/programming") == "reddit"

    def test_github(self):
        assert classify_source_domain("https://github.com/anthropics/claude-code") == "github"

    def test_x_and_twitter_both_map_to_x(self):
        assert classify_source_domain("https://x.com/someone/status/1") == "x"
        assert classify_source_domain("https://twitter.com/someone/status/1") == "x"

    def test_academic_domains(self):
        assert classify_source_domain("https://arxiv.org/abs/1234.5678") == "academic"
        assert classify_source_domain("https://scholar.google.com/citations?x") == "academic"

    def test_www_prefix_stripped(self):
        assert classify_source_domain("https://www.github.com/x/y") == "github"

    def test_unrecognized_domain_falls_back_to_the_domain_itself(self):
        assert classify_source_domain("https://some-random-blog.example/post") == "some-random-blog.example"

    def test_empty_url_returns_unknown(self):
        assert classify_source_domain("") == "unknown"

    def test_malformed_url_does_not_raise(self):
        assert classify_source_domain("not a url at all") in ("unknown", "not a url at all")


class TestComputeSourceCoverage:
    def _citation(self, cid: str, url: str) -> dict:
        return {"id": cid, "url": url}

    def test_counts_per_source(self):
        citations = [
            self._citation("c1", "https://github.com/a/b"),
            self._citation("c2", "https://github.com/c/d"),
            self._citation("c3", "https://reddit.com/r/x"),
        ]
        result = compute_source_coverage(citations, useful_ids=set())
        by_source = {s["source"]: s["count"] for s in result["sources"]}
        assert by_source == {"github": 2, "reddit": 1}
        assert result["total_citations"] == 3

    def test_useful_count_and_value_rate(self):
        citations = [
            self._citation("c1", "https://github.com/a/b"),
            self._citation("c2", "https://github.com/c/d"),
        ]
        result = compute_source_coverage(citations, useful_ids={"c1"})
        github = next(s for s in result["sources"] if s["source"] == "github")
        assert github["useful_count"] == 1
        assert github["value_rate"] == 0.5
        assert result["total_useful"] == 1

    def test_sorted_by_count_descending(self):
        citations = [
            self._citation("c1", "https://reddit.com/x"),
            self._citation("c2", "https://github.com/a"),
            self._citation("c3", "https://github.com/b"),
            self._citation("c4", "https://github.com/c"),
        ]
        result = compute_source_coverage(citations, useful_ids=set())
        assert result["sources"][0]["source"] == "github"

    def test_disabled_flag_set_from_disabled_sources(self):
        citations = [self._citation("c1", "https://reddit.com/x")]
        result = compute_source_coverage(citations, useful_ids=set(), disabled_sources={"reddit"})
        assert result["sources"][0]["disabled"] is True

    def test_not_disabled_by_default(self):
        citations = [self._citation("c1", "https://reddit.com/x")]
        result = compute_source_coverage(citations, useful_ids=set())
        assert result["sources"][0]["disabled"] is False

    def test_empty_citations_returns_empty_report(self):
        result = compute_source_coverage([], useful_ids=set())
        assert result["sources"] == []
        assert result["total_citations"] == 0
        assert result["total_useful"] == 0

    def test_malformed_entries_skipped_not_raising(self):
        citations = ["garbage", None, {}, self._citation("c1", "https://github.com/a")]
        result = compute_source_coverage(citations, useful_ids=set())
        assert result["total_citations"] == 4  # len() counts them; only well-formed ones get bucketed
        assert sum(s["count"] for s in result["sources"]) == 2  # {} -> unknown, plus the real one

    def test_missing_url_classified_as_unknown(self):
        result = compute_source_coverage([{"id": "c1"}], useful_ids=set())
        assert result["sources"][0]["source"] == "unknown"
