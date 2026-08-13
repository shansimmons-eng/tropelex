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


class TestSetAiSummary:
    """#19: ai_summary is a separate field from the human-provided
    `summary` -- generating one must never overwrite the other."""

    @pytest.fixture
    def replay(self, tmp_path):
        return SessionReplay(str(tmp_path))

    def test_sets_ai_summary_on_full_record(self, replay):
        result = replay.record_session(
            "proj", {"decisions": []}, {"decisions": [{"decision": "x"}]}, summary="human note",
        )
        session_id = result["session_id"]

        ok = replay.set_ai_summary("proj", session_id, "AI-generated summary")
        assert ok is True

        session = replay.get_session("proj", session_id)
        assert session["ai_summary"] == "AI-generated summary"
        assert session["summary"] == "human note"  # untouched

    def test_updates_index_entry_too(self, replay):
        result = replay.record_session("proj", {}, {"decisions": []}, summary="x")
        session_id = result["session_id"]
        replay.set_ai_summary("proj", session_id, "AI summary")

        sessions = replay.get_sessions("proj")
        assert sessions[0]["ai_summary"] == "AI summary"

    def test_unknown_session_returns_false(self, replay):
        assert replay.set_ai_summary("proj", "does-not-exist", "x") is False

    def test_corrupt_index_does_not_break_the_real_save(self, replay, tmp_path):
        """The session file itself is the source of truth; a corrupt index
        is a best-effort convenience update, not a reason to fail the
        whole operation."""
        result = replay.record_session("proj", {}, {"decisions": []}, summary="x")
        session_id = result["session_id"]

        index_file = tmp_path / "memory" / "replays" / "proj" / "index.json"
        index_file.write_text("{not valid json")

        ok = replay.set_ai_summary("proj", session_id, "AI summary")
        assert ok is True
        assert replay.get_session("proj", session_id)["ai_summary"] == "AI summary"


class TestSessionReplayAgent:
    """agent field on record_session — added when session tracking became
    multi-agent aware, mirroring the same convention in agent_skills/friction."""

    @pytest.fixture
    def replay(self, tmp_path):
        return SessionReplay(str(tmp_path))

    def _sess(self, replay, agent=None, **kwargs):
        before = {"project_name": "test", "decisions": []}
        after = {"project_name": "test", "decisions": [{"decision": "x"}]}
        if agent is None:
            return replay.record_session("proj", before, after, **kwargs)
        return replay.record_session("proj", before, after, agent=agent, **kwargs)

    def test_default_agent_is_unspecified(self, replay):
        self._sess(replay)
        sessions = replay.get_sessions("proj")
        assert sessions[0]["agent"] == "unspecified"

    def test_agent_is_recorded_on_full_record(self, replay):
        result = self._sess(replay, agent="Claude")
        full = replay.get_session("proj", result["session_id"])
        assert full["agent"] == "Claude"

    def test_agent_is_recorded_on_index_entry(self, replay):
        """The lightweight index (what get_sessions reads) must carry agent
        too — it's a separate, smaller record than the full session file."""
        self._sess(replay, agent="Gemini")
        sessions = replay.get_sessions("proj")
        assert sessions[0]["agent"] == "Gemini"

    def test_agent_is_stripped_and_blank_falls_back(self, replay):
        self._sess(replay, agent="  Claude  ")
        self._sess(replay, agent="   ")
        agents = [s["agent"] for s in replay.get_sessions("proj")]
        assert "Claude" in agents
        assert "unspecified" in agents

    def test_list_agents_excludes_unspecified_and_sorts(self, replay):
        self._sess(replay, agent="Gemini")
        self._sess(replay, agent="Claude")
        self._sess(replay)  # default -> unspecified
        assert replay.list_agents("proj") == ["Claude", "Gemini"]

    def test_list_agents_empty_project(self, replay):
        assert replay.list_agents("empty-project") == []
