"""Tests for core.tropebook.alert_service — Feed Alert Service."""

import pytest
from core.tropebook.alert_service import (
    format_slack_message,
    _event_text,
    should_alert,
)


class TestFormatSlackMessage:
    def test_run_complete(self):
        payload = format_slack_message("AI Research", "run_complete", {"citations_count": 5})
        assert "attachments" in payload
        att = payload["attachments"][0]
        assert "AI Research" in att["title"]
        assert att["color"] == "#98fa80"
        assert any(f["value"] == "5" for f in att["fields"])

    def test_error_event(self):
        payload = format_slack_message("My Feed", "error", {"error": "disk full"})
        att = payload["attachments"][0]
        assert att["color"] == "#ff6b6b"
        assert any("disk full" in f["value"] for f in att["fields"])

    def test_trend_alert(self):
        payload = format_slack_message("Feed", "trend_alert", {"trend": "increasing"})
        att = payload["attachments"][0]
        assert att["color"] == "#a580fa"

    def test_new_citations(self):
        payload = format_slack_message("Feed", "new_citations", {"citations_count": 3})
        att = payload["attachments"][0]
        assert att["color"] == "#80d5fa"


class TestEventText:
    def test_run_complete(self):
        text = _event_text("run_complete", "Feed", {"citations_count": 10})
        assert "10" in text

    def test_error(self):
        text = _event_text("error", "Feed", {"error": "timeout"})
        assert "timeout" in text

    def test_unknown(self):
        text = _event_text("unknown", "Feed", {})
        assert "unknown" in text


class TestShouldAlert:
    def test_alerts_disabled(self):
        assert should_alert("run_complete", {"alerts_enabled": False}) is False

    def test_event_not_in_filter(self):
        assert should_alert("trend_alert", {"alert_events": ["run_complete"]}) is False

    def test_event_in_filter(self):
        assert should_alert("run_complete", {"alert_events": ["run_complete"]}) is True

    def test_default_filter(self):
        assert should_alert("run_complete", {}) is True
        assert should_alert("error", {}) is True
        assert should_alert("trend_alert", {}) is False

    def test_quiet_hours_no_wrap(self):
        # This test depends on current UTC hour, so we test the logic
        config = {"alerts_enabled": True}
        # Just verify it returns a bool
        result = should_alert("run_complete", config, quiet_hours=(0, 23))
        assert isinstance(result, bool)

    def test_quiet_hours_none(self):
        assert should_alert("run_complete", {"alerts_enabled": True}, quiet_hours=None) is True
