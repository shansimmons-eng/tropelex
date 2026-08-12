"""Tests for core.last30days.lib.providers._record_usage -- the mechanism
that attributes real LLM spend inside the last30days engine subprocess to
a Tropelex project's cost ledger. Previously every call through this
engine (Gemini/OpenAI/xAI/OpenRouter) was completely untracked.
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import patch

import pytest

from core.last30days.lib.providers import _record_usage
from core.memory.manager import MemoryManager


def _project() -> str:
    return f"test_l30d_cost_{uuid.uuid4().hex[:8]}"


class TestRecordUsage:
    def test_noop_without_tropelex_project_env_var(self, monkeypatch):
        monkeypatch.delenv("TROPELEX_PROJECT", raising=False)
        with patch("core.cost.tracker.record_llm_cost") as mock_record:
            _record_usage("gemini", "gemini-3.1-flash-lite", {"promptTokenCount": 10, "candidatesTokenCount": 5}, "test")
        mock_record.assert_not_called()

    def test_noop_without_usage(self, monkeypatch):
        monkeypatch.setenv("TROPELEX_PROJECT", "cup")
        with patch("core.cost.tracker.record_llm_cost") as mock_record:
            _record_usage("gemini", "gemini-3.1-flash-lite", None, "test")
            _record_usage("gemini", "gemini-3.1-flash-lite", {}, "test")
        mock_record.assert_not_called()

    def test_records_gemini_usage_shape(self, monkeypatch):
        project = _project()
        monkeypatch.setenv("TROPELEX_PROJECT", project)
        _record_usage(
            "gemini", "gemini-3.1-flash-lite",
            {"promptTokenCount": 120, "candidatesTokenCount": 40}, "generate_text",
        )
        mm = MemoryManager()
        events = mm.get_project_memory(project).get("cost_events", [])
        assert len(events) == 1
        assert events[0]["metadata"]["prompt_tokens"] == 120
        assert events[0]["metadata"]["completion_tokens"] == 40
        assert events[0]["metadata"]["pricing_known"] is False
        assert events[0]["amount"] == 0.0

    def test_records_openai_responses_usage_shape(self, monkeypatch):
        project = _project()
        monkeypatch.setenv("TROPELEX_PROJECT", project)
        _record_usage(
            "openai", "gpt-5.4-nano",
            {"input_tokens": 200, "output_tokens": 75}, "generate_text",
        )
        mm = MemoryManager()
        events = mm.get_project_memory(project).get("cost_events", [])
        assert len(events) == 1
        assert events[0]["metadata"]["prompt_tokens"] == 200
        assert events[0]["metadata"]["completion_tokens"] == 75

    def test_records_openrouter_chat_completions_usage_shape(self, monkeypatch):
        project = _project()
        monkeypatch.setenv("TROPELEX_PROJECT", project)
        _record_usage(
            "openrouter", "google/gemini-3.1-flash-lite-preview",
            {"prompt_tokens": 50, "completion_tokens": 20}, "generate_text",
        )
        mm = MemoryManager()
        events = mm.get_project_memory(project).get("cost_events", [])
        assert len(events) == 1

    def test_cost_tracking_failure_is_non_fatal(self, monkeypatch):
        """A cost-tracking failure must never break the actual research call."""
        monkeypatch.setenv("TROPELEX_PROJECT", "cup")
        with patch("core.cost.tracker.record_llm_cost", side_effect=RuntimeError("boom")):
            _record_usage("gemini", "gemini-3.1-flash-lite", {"promptTokenCount": 1, "candidatesTokenCount": 1}, "test")
        # No exception raised -- the assertion is that we got here at all.
