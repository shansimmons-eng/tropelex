"""
Tests for Session Replay.
"""

import json
import tempfile
from pathlib import Path

import pytest

from core.session_replay import SessionReplay, _deep_diff, _snapshot_id


class TestSnapshotId:
    def test_deterministic(self):
        memory = {"key": "value", "number": 42}
        assert _snapshot_id(memory) == _snapshot_id(memory)

    def test_different_for_different_state(self):
        m1 = {"key": "value1"}
        m2 = {"key": "value2"}
        assert _snapshot_id(m1) != _snapshot_id(m2)


class TestDeepDiff:
    def test_no_changes(self):
        assert _deep_diff({"a": 1}, {"a": 1}) == []

    def test_added_key(self):
        changes = _deep_diff({}, {"new_key": "value"})
        assert len(changes) == 1
        assert changes[0]["type"] == "added"
        assert changes[0]["path"] == "new_key"

    def test_removed_key(self):
        changes = _deep_diff({"old_key": "value"}, {})
        assert len(changes) == 1
        assert changes[0]["type"] == "removed"

    def test_modified_value(self):
        changes = _deep_diff({"key": "old"}, {"key": "new"})
        assert len(changes) == 1
        assert changes[0]["type"] == "modified"
        assert changes[0]["before"] == "old"
        assert changes[0]["after"] == "new"

    def test_nested_changes(self):
        before = {"outer": {"inner": "old"}}
        after = {"outer": {"inner": "new"}}
        changes = _deep_diff(before, after)
        assert len(changes) == 1
        assert changes[0]["path"] == "outer.inner"

    def test_list_additions(self):
        before = {"items": ["a", "b"]}
        after = {"items": ["a", "b", "c"]}
        changes = _deep_diff(before, after)
        assert len(changes) > 0

    def test_list_length_changed(self):
        before = {"decisions": [{"d": "1"}]}
        after = {"decisions": [{"d": "1"}, {"d": "2"}]}
        changes = _deep_diff(before, after)
        assert any(c["type"] in ("list_length_changed", "items_appended") for c in changes)


class TestSessionReplay:
    @pytest.fixture
    def replay(self, tmp_path):
        return SessionReplay(str(tmp_path))

    def test_record_session(self, replay):
        before = {"project_name": "test", "decisions": []}
        after = {"project_name": "test", "decisions": [{"decision": "Use Python"}]}

        result = replay.record_session("test-project", before, after, summary="Added Python decision")
        assert result["change_count"] > 0
        assert "session_id" in result

    def test_get_sessions(self, replay):
        before = {"project_name": "test", "decisions": []}
        after = {"project_name": "test", "decisions": []}

        replay.record_session("test-project", before, after, summary="session 1")
        replay.record_session("test-project", before, after, summary="session 2")

        sessions = replay.get_sessions("test-project")
        assert len(sessions) == 2

    def test_get_session_detail(self, replay):
        before = {"project_name": "test", "decisions": []}
        after = {"project_name": "test", "decisions": [{"decision": "Use Python"}]}

        result = replay.record_session("test-project", before, after)
        detail = replay.get_session("test-project", result["session_id"])

        assert detail is not None
        assert detail["session_id"] == result["session_id"]
        assert "snapshot_before" in detail
        assert "snapshot_after" in detail

    def test_get_session_changes(self, replay):
        before = {"project_name": "test", "decisions": []}
        after = {"project_name": "test", "decisions": [{"decision": "Use Python"}]}

        result = replay.record_session("test-project", before, after)
        changes = replay.get_session_changes("test-project", result["session_id"])

        assert changes is not None
        assert len(changes) > 0

    def test_get_nonexistent_session(self, replay):
        assert replay.get_session("test", "nonexistent") is None
        assert replay.get_session_changes("test", "nonexistent") is None

    def test_rollback(self, replay):
        original = {"project_name": "test", "decisions": [{"decision": "Original"}]}
        modified = {"project_name": "test", "decisions": [{"decision": "Modified"}]}

        # Record a session
        result = replay.record_session("test-project", original, modified)

        # Rollback
        class MockMM:
            def __init__(self):
                self.current = modified
            def get_project_memory(self, name):
                return self.current
            def save_project_memory(self, name, memory):
                self.current = memory

        mm = MockMM()
        rollback = replay.rollback_session("test-project", result["session_id"], mm)
        assert rollback["rolled_back"] is True
        assert mm.current == original

    def test_weekly_summary(self, replay):
        before = {"project_name": "test", "decisions": []}
        after = {"project_name": "test", "decisions": [{"decision": "Use Python"}]}

        replay.record_session("test-project", before, after, summary="session")
        summary = replay.get_weekly_summary("test-project")

        assert summary["sessions"] == 1
        assert summary["total_changes"] > 0

    def test_empty_project(self, replay):
        assert replay.get_sessions("empty-project") == []
        assert replay.get_weekly_summary("empty-project")["sessions"] == 0
