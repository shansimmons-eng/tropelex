"""
Tests for Slack Decision Capture — pure functions.
Covers: detect_decision_signals, extract_decision_text, detect_conflict,
        capture_decision, extract_decisions_from_thread.
"""

import pytest
from core.slack.capture import (
    capture_decision,
    detect_conflict,
    detect_decision_signals,
    extract_decision_text,
    extract_decisions_from_thread,
)
from core.slack import Ok, Err


# ── detect_decision_signals ───────────────────────────────────────────────

class TestDetectDecisionSignals:
    def test_detects_lets_go_with(self):
        assert detect_decision_signals("Let's go with FastAPI") is True

    def test_detects_decided(self):
        assert detect_decision_signals("We decided to use Postgres") is True

    def test_detects_switching_to(self):
        assert detect_decision_signals("Switching to TypeScript") is True

    def test_detects_confirmed(self):
        assert detect_decision_signals("Confirmed: React for frontend") is True

    def test_detects_tldr(self):
        assert detect_decision_signals("TLDR: We're using Docker") is True

    def test_no_signal(self):
        assert detect_decision_signals("Just pushing some code") is False

    def test_empty_string(self):
        assert detect_decision_signals("") is False

    def test_none_input(self):
        assert detect_decision_signals(None) is False


# ── extract_decision_text ─────────────────────────────────────────────────

class TestExtractDecisionText:
    def test_extracts_after_signal(self):
        result = extract_decision_text("Let's go with FastAPI for backend")
        assert result == "FastAPI for backend"

    def test_strips_to_200_chars(self):
        long_msg = "Decision: " + "A" * 300
        result = extract_decision_text(long_msg)
        assert len(result) <= 200

    def test_fallback_to_full_message(self):
        result = extract_decision_text("No signal phrase here but has content")
        assert result == "No signal phrase here but has content"

    def test_empty_input(self):
        assert extract_decision_text("") == ""


# ── detect_conflict ───────────────────────────────────────────────────────

class TestDetectConflict:
    def test_detects_framework_conflict(self):
        existing = [{"decision": "Use React for frontend"}]
        conflicts = detect_conflict("Use Vue for frontend", existing)
        assert len(conflicts) == 1
        assert "React" in conflicts[0]

    def test_detects_database_conflict(self):
        existing = [{"decision": "Use Postgres as database"}]
        conflicts = detect_conflict("Use MySQL as database", existing)
        assert len(conflicts) == 1

    def test_no_conflict(self):
        existing = [{"decision": "Use React for frontend"}]
        conflicts = detect_conflict("Use FastAPI for backend", existing)
        assert len(conflicts) == 0

    def test_empty_inputs(self):
        assert detect_conflict("", [{"decision": "X"}]) == []
        assert detect_conflict("X", []) == []


# ── capture_decision ──────────────────────────────────────────────────────

class TestCaptureDecision:
    def test_captures_and_adds_to_memory(self):
        memory = {"decisions": []}
        result = capture_decision(memory, "Use FastAPI", context="Slack thread")
        assert isinstance(result, Ok)
        assert result.value.decision_text == "Use FastAPI"
        assert len(memory["decisions"]) == 1
        assert memory["decisions"][0]["source"] == "slack"

    def test_rejects_empty_text(self):
        result = capture_decision({}, "")
        assert isinstance(result, Err)

    def test_strips_whitespace(self):
        memory = {}
        result = capture_decision(memory, "  Use FastAPI  ")
        assert result.value.decision_text == "Use FastAPI"

    def test_truncates_long_text(self):
        memory = {}
        long_text = "A" * 600
        result = capture_decision(memory, long_text)
        assert len(result.value.decision_text) <= 500


# ── extract_decisions_from_thread ─────────────────────────────────────────

class TestExtractDecisionsFromThread:
    def test_extracts_from_thread(self):
        messages = [
            "Just pushing code",
            "Let's go with FastAPI for the API",
            "Looks good to me",
            "We decided to use Postgres",
        ]
        result = extract_decisions_from_thread(messages)
        assert isinstance(result, Ok)
        assert result.value.extraction_count == 2

    def test_empty_thread(self):
        result = extract_decisions_from_thread([])
        assert isinstance(result, Ok)
        assert result.value.extraction_count == 0

    def test_invalid_input(self):
        result = extract_decisions_from_thread("not a list")
        assert isinstance(result, Err)

    def test_skips_non_strings(self):
        messages = ["Let's go with FastAPI", 123, None, "We decided to use Docker"]
        result = extract_decisions_from_thread(messages)
        assert isinstance(result, Ok)
        assert result.value.extraction_count == 2

    def test_thread_summary(self):
        messages = ["Let's go with FastAPI", "We decided to use Docker"]
        result = extract_decisions_from_thread(messages)
        assert "2 decision(s)" in result.value.thread_summary
        assert "2 message(s)" in result.value.thread_summary
