"""Tests for automatic LLM cost tracking -- the mechanism that feeds the
Cost Ledger with real data instead of it staying permanently empty.

core.cost.tracker.record_llm_cost computes accurate per-model USD from real
token counts (not the old flat generic token_usage rate), and core.llm's
_openai_chat/_openai_embed call it automatically after every real OpenAI
response. These tests cover the pricing math directly and the end-to-end
wiring through core.llm.compress().
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.cost.tracker import record_llm_cost
from core.cost import Err, Ok
from core.memory.manager import MemoryManager


def _project() -> str:
    return f"test_costllm_{uuid.uuid4().hex[:8]}"


def _fake_response(status_code: int, json_data: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.text = str(json_data)
    return resp


def _fake_async_client(post_response) -> MagicMock:
    """Build a mock that behaves like `async with httpx.AsyncClient() as client`."""
    client = MagicMock()
    client.post = AsyncMock(return_value=post_response)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=ctx)


class TestRecordLlmCostPricing:
    def test_accurate_usd_for_known_model(self):
        project = _project()
        result = record_llm_cost(project, prompt_tokens=1000, completion_tokens=200, model="gpt-4o-mini")
        assert isinstance(result, Ok)
        event = result.value
        # 1000 * 0.15e-6 + 200 * 0.60e-6 = 0.00015 + 0.00012 = 0.00027
        assert event.amount == pytest.approx(0.00027, abs=1e-8)
        assert event.unit == "usd"
        assert event.event_type == "llm_usage"

    def test_embedding_model_has_no_output_cost(self):
        project = _project()
        result = record_llm_cost(
            project, prompt_tokens=500, completion_tokens=0, model="text-embedding-3-small",
        )
        assert isinstance(result, Ok)
        # 500 * 0.02e-6
        assert result.value.amount == pytest.approx(0.00001, abs=1e-8)

    def test_unknown_model_records_tokens_at_zero_usd_not_dropped(self):
        """An unpriced model must still leave a ledger trace (real token
        counts, amount 0.0, pricing_known False) rather than vanishing
        entirely -- a $0 entry with pricing_known False is legible as
        "priced unknown," not "this call was free."""
        project = _project()
        result = record_llm_cost(project, prompt_tokens=100, completion_tokens=10, model="not-a-real-model")
        assert isinstance(result, Ok)
        event = result.value
        assert event.amount == 0.0
        assert event.metadata["pricing_known"] is False
        assert event.metadata["prompt_tokens"] == 100
        assert event.metadata["completion_tokens"] == 10

    def test_invalid_project_name_returns_err_not_raise(self):
        """The docstring promises "Never raises." get_project_memory() (via
        _safe_path) raises ValueError for a project name outside
        [a-zA-Z0-9_-]+, and that call happens before record_cost_event's own
        try/except -- must not escape record_llm_cost."""
        result = record_llm_cost(
            "not a valid name!", prompt_tokens=10, completion_tokens=5, model="gpt-4o-mini",
        )
        assert isinstance(result, Err)
        assert result.code == "VALIDATION_ERROR"

    def test_defaults_to_general_decision_id(self):
        project = _project()
        result = record_llm_cost(project, prompt_tokens=10, completion_tokens=5, model="gpt-4o-mini")
        assert result.value.decision_id == "_general"

    def test_metadata_carries_real_token_counts(self):
        project = _project()
        result = record_llm_cost(
            project, prompt_tokens=300, completion_tokens=150, model="gpt-4o-mini", description="test call",
        )
        event = result.value
        assert event.metadata == {
            "model": "gpt-4o-mini",
            "prompt_tokens": 300,
            "completion_tokens": 150,
            "total_tokens": 450,
            "pricing_known": True,
        }
        assert event.description == "test call"

    def test_event_actually_persisted_to_project_memory(self):
        project = _project()
        record_llm_cost(project, prompt_tokens=1000, completion_tokens=100, model="gpt-4o-mini")
        memory = MemoryManager().get_project_memory(project)
        events = memory.get("cost_events", [])
        assert len(events) == 1
        assert events[0]["event_type"] == "llm_usage"


class TestOpenAiChatRecordsRealCost:
    """core.llm._openai_chat must record a cost event from the real `usage`
    block OpenAI returns, using the actual project name it was called with."""

    @pytest.mark.asyncio
    async def test_successful_chat_call_records_cost_for_given_project(self, monkeypatch):
        import core.llm as llm_mod

        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
        monkeypatch.setattr(llm_mod, "_ollama_available", AsyncMock(return_value=False))

        project = _project()
        resp = _fake_response(200, {
            "choices": [{"message": {"content": "compressed text"}}],
            "usage": {"prompt_tokens": 800, "completion_tokens": 50, "total_tokens": 850},
        })

        with patch("httpx.AsyncClient", _fake_async_client(resp)):
            result = await llm_mod.compress("a very verbose prompt please help me", project=project)

        assert result["compressed"] == "compressed text"
        assert result["backend"] == "openai/gpt-4o-mini"

        memory = MemoryManager().get_project_memory(project)
        events = memory.get("cost_events", [])
        assert len(events) == 1
        assert events[0]["metadata"]["prompt_tokens"] == 800
        assert events[0]["metadata"]["completion_tokens"] == 50
        # 800 * 0.15e-6 + 50 * 0.60e-6 = 0.00012 + 0.00003 = 0.00015
        assert events[0]["amount"] == pytest.approx(0.00015, abs=1e-8)

    @pytest.mark.asyncio
    async def test_no_project_is_skipped_not_recorded_as_a_fake_project(self, monkeypatch, tmp_path):
        """A synthetic "_global" project used to get written to disk for
        calls with no project context (e.g. the standalone /hijacker page),
        which then leaked into the dashboard's project dropdown via the
        same list_projects() every router uses for existence checks. No
        project context now means the call is logged but not persisted as
        a fake project -- confirmed here by checking no file was created."""
        import core.llm as llm_mod
        import core.cost.tracker as tracker_mod

        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
        monkeypatch.setattr(llm_mod, "_ollama_available", AsyncMock(return_value=False))
        isolated_mm = MemoryManager(base_path=str(tmp_path))
        monkeypatch.setattr(tracker_mod, "MemoryManager", lambda *a, **kw: isolated_mm)

        resp = _fake_response(200, {
            "choices": [{"message": {"content": "x"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11},
        })

        with patch("httpx.AsyncClient", _fake_async_client(resp)):
            result = await llm_mod.compress("hi", project=None)

        assert result["compressed"] == "x"
        assert not (tmp_path / "memory" / "_global.json").exists()
        assert isolated_mm.list_projects() == []

    @pytest.mark.asyncio
    async def test_ollama_path_never_records_a_cost_event(self, monkeypatch):
        """Ollama is free/local -- serving the request there must never
        produce a cost event, since there's nothing to charge for."""
        import core.llm as llm_mod

        monkeypatch.setattr(llm_mod, "_ollama_available", AsyncMock(return_value=True))
        monkeypatch.setattr(llm_mod, "_ollama_chat", AsyncMock(return_value="compressed via ollama"))

        project = _project()
        with patch("httpx.AsyncClient") as mock_client:
            result = await llm_mod.compress("some prompt", project=project)
            mock_client.assert_not_called()

        assert result["backend"].startswith("ollama/")
        memory = MemoryManager().get_project_memory(project)
        assert memory.get("cost_events", []) == []

    @pytest.mark.asyncio
    async def test_cost_recording_failure_does_not_break_the_chat_call(self, monkeypatch):
        """A broken cost tracker must never take down a real LLM response --
        _record_usage_best_effort catches everything and just logs."""
        import core.llm as llm_mod
        import core.cost.tracker as tracker_mod

        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
        monkeypatch.setattr(llm_mod, "_ollama_available", AsyncMock(return_value=False))
        monkeypatch.setattr(
            tracker_mod, "record_llm_cost", MagicMock(side_effect=RuntimeError("boom")),
        )

        resp = _fake_response(200, {
            "choices": [{"message": {"content": "still works"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        })
        with patch("httpx.AsyncClient", _fake_async_client(resp)):
            result = await llm_mod.compress("hi", project=_project())

        assert result["compressed"] == "still works"
