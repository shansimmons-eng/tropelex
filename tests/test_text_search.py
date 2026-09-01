"""
Tests for core.text_search -- the shared keyword-overlap scoring
extracted out of core.search_router once core.docs_search needed the
same logic. Both consumers already had their own coverage exercising
this indirectly; these are the direct unit tests for the shared module
itself.
"""

from __future__ import annotations

from core.text_search import keyword_score, tokenize


class TestTokenize:
    def test_lowercases_and_splits(self):
        assert tokenize("Ghost Decisions Engine") == {"ghost", "decisions", "engine"}

    def test_strips_stopwords(self):
        assert "the" not in tokenize("the quick brown fox")
        assert "is" not in tokenize("this is a test")

    def test_strips_short_tokens(self):
        # "a", "an", "to" etc. are 1-2 chars and filtered regardless of
        # the stopword list, via the length > 2 requirement.
        assert tokenize("go to a fair") == {"fair"}

    def test_non_alphanumeric_ignored(self):
        assert tokenize("ghost-decisions & drift!") == {"ghost", "decisions", "drift"}

    def test_empty_string(self):
        assert tokenize("") == set()


class TestKeywordScore:
    def test_full_overlap_scores_one(self):
        assert keyword_score({"ghost", "decisions"}, "Ghost Decisions Engine") == 1.0

    def test_no_overlap_scores_zero(self):
        assert keyword_score({"ghost", "decisions"}, "completely unrelated text") == 0.0

    def test_partial_overlap_is_fraction_of_query_tokens(self):
        assert keyword_score({"ghost", "decisions", "engine"}, "ghost drift") == 1 / 3

    def test_empty_query_tokens_scores_zero(self):
        assert keyword_score(set(), "any text at all") == 0.0
