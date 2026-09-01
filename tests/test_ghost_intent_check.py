"""
Tests for core.ghost.intent_check (#106) -- LLM-as-intent-check.

Every test mocks core.ghost.intent_check.llm_chat directly; none of these
hit a real Ollama/OpenAI backend. That mirrors core.llm's own test
conventions (mock at the module boundary, never a real network call in
CI) and is required here specifically: the graceful-no-backend-available
path (llm_chat returning None) has to be independently testable from the
has-a-backend path, which a real call couldn't guarantee either way.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from core.ghost.intent_check import (
    DEFAULT_MAX_CALLS_PER_DAY,
    _cache_key,
    _parse_response,
    check_intent_conflict,
)


class TestParseResponse:
    def test_yes_first_line_is_conflict(self):
        conflict, rationale = _parse_response("YES\nThis removes the required auth check.")
        assert conflict is True
        assert rationale == "This removes the required auth check."

    def test_yes_case_insensitive(self):
        conflict, _ = _parse_response("yes\nlowercase still counts")
        assert conflict is True

    def test_no_first_line_is_not_conflict(self):
        conflict, rationale = _parse_response("NO\nUnrelated change.")
        assert conflict is False
        assert rationale == "Unrelated change."

    def test_malformed_response_fails_closed_to_no(self):
        conflict, _ = _parse_response("I'm not sure, this is ambiguous.")
        assert conflict is False

    def test_empty_response_fails_closed_to_no(self):
        conflict, rationale = _parse_response("")
        assert conflict is False
        assert rationale == ""

    def test_single_line_response_has_empty_rationale(self):
        conflict, rationale = _parse_response("YES")
        assert conflict is True
        assert rationale == ""


class TestCacheKey:
    def test_same_inputs_same_key(self):
        assert _cache_key("d1", "diff text") == _cache_key("d1", "diff text")

    def test_different_diff_different_key(self):
        assert _cache_key("d1", "diff a") != _cache_key("d1", "diff b")

    def test_different_decision_different_key(self):
        assert _cache_key("d1", "diff") != _cache_key("d2", "diff")


class TestCheckIntentConflict:
    @pytest.fixture
    def memory(self):
        return {"decisions": [], "audit_log": []}

    @pytest.mark.asyncio
    async def test_fresh_call_hits_llm_and_caches_result(self, memory):
        with patch(
            "core.ghost.intent_check.llm_chat",
            new=AsyncMock(return_value="YES\nThis weakens the auth requirement."),
        ) as mock_chat:
            result = await check_intent_conflict("d1", "Always require auth", "diff text", memory)

        assert result == {"conflict": True, "rationale": "This weakens the auth requirement."}
        mock_chat.assert_awaited_once()
        key = _cache_key("d1", "diff text")
        assert memory["intent_check_cache"][key]["conflict"] is True
        assert memory["audit_log"][-1]["event_type"] == "ghost_intent_check"
        assert memory["audit_log"][-1]["cached"] is False
        assert memory["audit_log"][-1]["result"] is True

    @pytest.mark.asyncio
    async def test_cache_hit_does_not_call_llm(self, memory):
        with patch(
            "core.ghost.intent_check.llm_chat", new=AsyncMock(return_value="YES\nfirst call"),
        ) as mock_chat:
            await check_intent_conflict("d1", "decision text", "diff text", memory)
            assert mock_chat.await_count == 1

            result = await check_intent_conflict("d1", "decision text", "diff text", memory)
            assert mock_chat.await_count == 1  # not called again

        assert result == {"conflict": True, "rationale": "first call"}
        assert memory["audit_log"][-1]["cached"] is True

    @pytest.mark.asyncio
    async def test_no_backend_available_returns_none(self, memory):
        with patch("core.ghost.intent_check.llm_chat", new=AsyncMock(return_value=None)) as mock_chat:
            result = await check_intent_conflict("d1", "decision text", "diff text", memory)

        assert result is None
        mock_chat.assert_awaited_once()
        assert "intent_check_cache" not in memory or memory["intent_check_cache"] == {}
        assert memory["audit_log"][-1]["result"] is None

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded_skips_without_calling_llm(self, memory):
        memory["intent_check_rate_limit"] = {
            "date": "2026-09-01", "count": 2,
        }
        with patch("core.ghost.intent_check._today", return_value="2026-09-01"), \
             patch("core.ghost.intent_check.llm_chat", new=AsyncMock()) as mock_chat:
            result = await check_intent_conflict(
                "d1", "decision text", "diff text", memory, max_calls_per_day=2,
            )

        assert result is None
        mock_chat.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rate_limit_resets_on_new_day(self, memory):
        memory["intent_check_rate_limit"] = {"date": "2026-08-31", "count": 999}
        with patch("core.ghost.intent_check._today", return_value="2026-09-01"), \
             patch("core.ghost.intent_check.llm_chat", new=AsyncMock(return_value="NO\nfine")) as mock_chat:
            result = await check_intent_conflict(
                "d1", "decision text", "diff text", memory, max_calls_per_day=DEFAULT_MAX_CALLS_PER_DAY,
            )

        assert result == {"conflict": False, "rationale": "fine"}
        mock_chat.assert_awaited_once()
        assert memory["intent_check_rate_limit"]["date"] == "2026-09-01"
        assert memory["intent_check_rate_limit"]["count"] == 1

    @pytest.mark.asyncio
    async def test_rate_limit_counter_increments_on_each_fresh_call(self, memory):
        with patch("core.ghost.intent_check.llm_chat", new=AsyncMock(return_value="NO\nfine")):
            await check_intent_conflict("d1", "decision", "diff one", memory)
            await check_intent_conflict("d1", "decision", "diff two", memory)

        assert memory["intent_check_rate_limit"]["count"] == 2

    @pytest.mark.asyncio
    async def test_cache_hit_does_not_increment_rate_limit(self, memory):
        with patch("core.ghost.intent_check.llm_chat", new=AsyncMock(return_value="NO\nfine")):
            await check_intent_conflict("d1", "decision", "diff", memory)
            await check_intent_conflict("d1", "decision", "diff", memory)

        assert memory["intent_check_rate_limit"]["count"] == 1

    @pytest.mark.asyncio
    async def test_project_kwarg_passed_through_to_llm_chat(self, memory):
        with patch(
            "core.ghost.intent_check.llm_chat", new=AsyncMock(return_value="NO\nfine"),
        ) as mock_chat:
            await check_intent_conflict("d1", "decision", "diff", memory, project="myproj")

        assert mock_chat.call_args.kwargs["project"] == "myproj"

    @pytest.mark.asyncio
    async def test_malformed_llm_response_does_not_escalate(self, memory):
        with patch(
            "core.ghost.intent_check.llm_chat", new=AsyncMock(return_value="maybe? unclear."),
        ):
            result = await check_intent_conflict("d1", "decision", "diff", memory)

        assert result == {"conflict": False, "rationale": ""}
