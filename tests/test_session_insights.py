"""Tests for core.session_insights (wishlist #19) -- LLM-generated
session summaries and retrospectives layered on SessionReplay's
structured diffs.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from core.session_insights import generate_retrospective, summarize_session


def _session(changes=None, summary="", **extra):
    return {
        "session_id": "sess-1",
        "changes": changes if changes is not None else [
            {"path": "decisions", "type": "items_appended", "count": 1, "items": ["Use Python"]},
        ],
        "summary": summary,
        **extra,
    }


class TestSummarizeSession:
    @pytest.mark.asyncio
    async def test_returns_llm_output(self):
        with patch("core.llm.chat", new=AsyncMock(return_value="Added a decision about Python.")):
            result = await summarize_session(_session())
        assert result == "Added a decision about Python."

    @pytest.mark.asyncio
    async def test_no_backend_returns_none(self):
        """core.llm.chat itself returns None when no backend is
        available -- summarize_session must pass that through, not treat
        it as an error."""
        with patch("core.llm.chat", new=AsyncMock(return_value=None)):
            result = await summarize_session(_session())
        assert result is None

    @pytest.mark.asyncio
    async def test_passes_project_through_for_cost_tracking(self):
        mock_chat = AsyncMock(return_value="summary")
        with patch("core.llm.chat", new=mock_chat):
            await summarize_session(_session(), project="tropelex")
        assert mock_chat.call_args.kwargs["project"] == "tropelex"

    @pytest.mark.asyncio
    async def test_malformed_changes_not_a_list_does_not_crash(self):
        with patch("core.llm.chat", new=AsyncMock(return_value="summary")):
            result = await summarize_session(_session(changes="not a list"))
        assert result == "summary"

    @pytest.mark.asyncio
    async def test_prompt_includes_human_summary_and_changes(self):
        mock_chat = AsyncMock(return_value="summary")
        with patch("core.llm.chat", new=mock_chat):
            await summarize_session(_session(summary="Migrated auth"))
        user_prompt = mock_chat.call_args.kwargs["user"]
        assert "Migrated auth" in user_prompt
        assert "decisions" in user_prompt

    @pytest.mark.asyncio
    async def test_caps_changes_in_prompt(self):
        many_changes = [{"path": f"p{i}", "type": "modified", "before": "a", "after": "b"} for i in range(50)]
        mock_chat = AsyncMock(return_value="summary")
        with patch("core.llm.chat", new=mock_chat):
            await summarize_session(_session(changes=many_changes))
        user_prompt = mock_chat.call_args.kwargs["user"]
        assert "and 20 more change(s)" in user_prompt


class TestGenerateRetrospective:
    @pytest.mark.asyncio
    async def test_returns_llm_output(self):
        sessions = [
            {"timestamp": "2026-08-10T00:00:00+00:00", "summary": "Shipped feature X", "change_count": 5},
        ]
        with patch("core.llm.chat", new=AsyncMock(return_value="You shipped feature X this week.")):
            result = await generate_retrospective(sessions, "last 7 day(s)")
        assert result == "You shipped feature X this week."

    @pytest.mark.asyncio
    async def test_empty_sessions_returns_none_without_calling_llm(self):
        mock_chat = AsyncMock(return_value="should not be called")
        with patch("core.llm.chat", new=mock_chat):
            result = await generate_retrospective([], "last 7 day(s)")
        assert result is None
        mock_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_backend_returns_none(self):
        sessions = [{"timestamp": "2026-08-10T00:00:00+00:00", "summary": "x", "change_count": 1}]
        with patch("core.llm.chat", new=AsyncMock(return_value=None)):
            result = await generate_retrospective(sessions, "last 7 day(s)")
        assert result is None

    @pytest.mark.asyncio
    async def test_malformed_session_entries_skipped_not_crashed(self):
        sessions = [
            {"timestamp": "2026-08-10T00:00:00+00:00", "summary": "real one", "change_count": 1},
            None, "not a dict", 42,
        ]
        mock_chat = AsyncMock(return_value="retrospective")
        with patch("core.llm.chat", new=mock_chat):
            result = await generate_retrospective(sessions, "last 7 day(s)")
        assert result == "retrospective"
        assert "real one" in mock_chat.call_args.kwargs["user"]

    @pytest.mark.asyncio
    async def test_all_malformed_entries_returns_none(self):
        mock_chat = AsyncMock(return_value="should not be called")
        with patch("core.llm.chat", new=mock_chat):
            result = await generate_retrospective([None, "not a dict"], "last 7 day(s)")
        assert result is None
        mock_chat.assert_not_called()
