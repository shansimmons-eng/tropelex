"""Tests for core/tropebook/adaptive_scheduling.py (wishlist #85): interval
recommendation and query-stagnation detection. Pure-function tests -- no
HTTP, no MemoryManager.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from core.tropebook.adaptive_scheduling import (
    LOW_NOVELTY_STREAK,
    is_query_stagnant,
    recommend_interval_change,
    suggest_query_rewrite,
)


def _run(count: int, timestamp: str = "2026-08-24T00:00:00+00:00") -> dict:
    return {"results_count": count, "timestamp": timestamp}


class TestRecommendIntervalChange:
    def test_manual_interval_never_adjusted(self):
        runs = [_run(0)] * 5
        result = recommend_interval_change("manual", runs)
        assert result["action"] == "none"
        assert result["recommended_interval"] == "manual"

    def test_lengthens_on_zero_novelty_streak(self):
        runs = [_run(5), _run(0), _run(0), _run(0)]
        result = recommend_interval_change("daily", runs)
        assert result["action"] == "lengthen"
        assert result["recommended_interval"] == "weekly"

    def test_weekly_lengthens_to_monthly(self):
        runs = [_run(0)] * LOW_NOVELTY_STREAK
        result = recommend_interval_change("weekly", runs)
        assert result["recommended_interval"] == "monthly"

    def test_monthly_stays_capped_no_further_lengthening(self):
        runs = [_run(0)] * LOW_NOVELTY_STREAK
        result = recommend_interval_change("monthly", runs)
        assert result["action"] == "none"
        assert result["recommended_interval"] == "monthly"

    def test_below_streak_threshold_no_lengthen(self):
        runs = [_run(0)] * (LOW_NOVELTY_STREAK - 1)
        result = recommend_interval_change("daily", runs)
        assert result["action"] == "none"

    def test_a_nonzero_run_breaks_the_streak(self):
        runs = [_run(0), _run(0), _run(1)]
        result = recommend_interval_change("daily", runs)
        assert result["action"] == "none"

    def test_shortens_on_spike(self):
        runs = [_run(2), _run(2), _run(2), _run(20)]
        result = recommend_interval_change("weekly", runs)
        assert result["action"] == "shorten"
        assert result["recommended_interval"] == "daily"

    def test_daily_stays_capped_no_further_shortening(self):
        runs = [_run(2), _run(2), _run(20)]
        result = recommend_interval_change("daily", runs)
        assert result["action"] == "none"
        assert result["recommended_interval"] == "daily"

    def test_no_spike_below_multiplier_threshold(self):
        runs = [_run(5), _run(5), _run(10)]  # 2x, not >3x
        result = recommend_interval_change("weekly", runs)
        assert result["action"] == "none"

    def test_zero_avg_prior_does_not_falsely_trigger_shorten(self):
        # All prior runs were zero -- this is the lengthen case, not spike,
        # since avg_prior == 0 can't be multiplied into a meaningful spike.
        runs = [_run(0), _run(0), _run(5)]
        result = recommend_interval_change("weekly", runs)
        assert result["action"] != "shorten"

    def test_empty_history_no_recommendation(self):
        result = recommend_interval_change("daily", [])
        assert result["action"] == "none"

    def test_malformed_entries_ignored_not_raising(self):
        runs = ["garbage", None, {}, _run(0), _run(0), _run(0)]
        result = recommend_interval_change("daily", runs)
        assert result["action"] == "lengthen"


class TestIsQueryStagnant:
    def test_true_on_zero_novelty_streak(self):
        assert is_query_stagnant([_run(0)] * LOW_NOVELTY_STREAK) is True

    def test_false_below_streak_threshold(self):
        assert is_query_stagnant([_run(0)] * (LOW_NOVELTY_STREAK - 1)) is False

    def test_false_when_streak_broken(self):
        assert is_query_stagnant([_run(0), _run(0), _run(1)]) is False

    def test_false_for_empty_history(self):
        assert is_query_stagnant([]) is False


class TestSuggestQueryRewrite:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_llm_backend(self):
        with patch("core.tropebook.adaptive_scheduling.llm.chat", new=AsyncMock(return_value=None)):
            result = await suggest_query_rewrite("Feed", "old query", [_run(0)])
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_llm_output(self):
        with patch(
            "core.tropebook.adaptive_scheduling.llm.chat", new=AsyncMock(return_value="better query"),
        ):
            result = await suggest_query_rewrite("Feed", "old query", [_run(0)])
        assert result == "better query"
