"""
Tests for Time-Travel Debugger — snapshot pure functions.
Covers: reconstruct_memory_at_date, diff_snapshots, find_nearest_snapshot.
"""

import pytest
from core.timetravel.snapshot import (
    reconstruct_memory_at_date,
    diff_snapshots,
    find_nearest_snapshot,
)
from core.timetravel import MemorySnapshot, Ok, Err


def _session(ts: str, project: str = "proj", decisions: list | None = None) -> dict:
    return {
        "timestamp": ts,
        "project": project,
        "snapshot_after": {"decisions": decisions or []},
    }


# ── reconstruct_memory_at_date ─────────────────────────────────────────────

class TestReconstructMemoryAtDate:
    def test_single_session_before_date(self):
        sessions = [_session("2026-01-10T12:00:00Z", decisions=["d1"])]
        result = reconstruct_memory_at_date(sessions, "2026-01-15")
        assert isinstance(result, Ok)
        assert result.value.decision_count == 1
        assert result.value.session_count == 1

    def test_multiple_sessions_returns_latest(self):
        sessions = [
            _session("2026-01-10T12:00:00Z", decisions=["d1"]),
            _session("2026-01-12T12:00:00Z", decisions=["d1", "d2"]),
            _session("2026-01-20T12:00:00Z", decisions=["d1", "d2", "d3"]),
        ]
        result = reconstruct_memory_at_date(sessions, "2026-01-15")
        assert isinstance(result, Ok)
        assert result.value.decision_count == 2  # only sessions before Jan 15

    def test_no_sessions_before_date(self):
        sessions = [_session("2026-01-20T12:00:00Z")]
        result = reconstruct_memory_at_date(sessions, "2026-01-15")
        assert isinstance(result, Err)
        assert result.code == "NOT_FOUND"

    def test_empty_sessions(self):
        result = reconstruct_memory_at_date([], "2026-01-15")
        assert isinstance(result, Err)

    def test_skips_malformed_sessions(self):
        sessions = [
            {"no_timestamp": True},  # malformed
            _session("2026-01-10T12:00:00Z", decisions=["d1"]),
        ]
        result = reconstruct_memory_at_date(sessions, "2026-01-15")
        assert isinstance(result, Ok)

    def test_invalid_date_format(self):
        sessions = [_session("2026-01-10T12:00:00Z")]
        result = reconstruct_memory_at_date(sessions, "not-a-date")
        assert isinstance(result, Err)

    def test_session_at_exact_date_included(self):
        sessions = [_session("2026-01-15T00:00:00Z", decisions=["d1"])]
        result = reconstruct_memory_at_date(sessions, "2026-01-15")
        assert isinstance(result, Ok)
        assert result.value.decision_count == 1


# ── diff_snapshots ─────────────────────────────────────────────────────────

class TestDiffSnapshots:
    def test_no_changes(self):
        snap_a = MemorySnapshot(
            project_name="p", snapshot_date="2026-01-10",
            memory={"decisions": [{"id": "d1"}]}, decision_count=1, session_count=1,
        )
        result = diff_snapshots(snap_a, snap_a)
        assert result.changes_summary == "No changes detected"

    def test_detects_added_decisions(self):
        snap_a = MemorySnapshot(
            project_name="p", snapshot_date="2026-01-10",
            memory={"decisions": [{"id": "d1"}]}, decision_count=1, session_count=1,
        )
        snap_b = MemorySnapshot(
            project_name="p", snapshot_date="2026-01-15",
            memory={"decisions": [{"id": "d1"}, {"id": "d2"}]}, decision_count=2, session_count=2,
        )
        result = diff_snapshots(snap_a, snap_b)
        assert "d2" in result.decisions_added
        assert result.sessions_added == 1

    def test_detects_removed_decisions(self):
        snap_a = MemorySnapshot(
            project_name="p", snapshot_date="2026-01-10",
            memory={"decisions": [{"id": "d1"}, {"id": "d2"}]}, decision_count=2, session_count=2,
        )
        snap_b = MemorySnapshot(
            project_name="p", snapshot_date="2026-01-15",
            memory={"decisions": [{"id": "d1"}]}, decision_count=1, session_count=1,
        )
        result = diff_snapshots(snap_a, snap_b)
        assert "d2" in result.decisions_removed

    def test_summary_includes_counts(self):
        snap_a = MemorySnapshot(
            project_name="p", snapshot_date="2026-01-10",
            memory={"decisions": []}, decision_count=0, session_count=0,
        )
        snap_b = MemorySnapshot(
            project_name="p", snapshot_date="2026-01-15",
            memory={"decisions": [{"id": "d1"}, {"id": "d2"}, {"id": "d3"}]},
            decision_count=3, session_count=3,
        )
        result = diff_snapshots(snap_a, snap_b)
        assert "3 decision(s) added" in result.changes_summary


# ── find_nearest_snapshot ──────────────────────────────────────────────────

class TestFindNearestSnapshot:
    def test_exact_match(self):
        sessions = [_session("2026-01-15T12:00:00Z")]
        result = find_nearest_snapshot(sessions, "2026-01-15T12:00:00Z")
        assert result is not None

    def test_nearest_before(self):
        sessions = [
            _session("2026-01-10T12:00:00Z"),
            _session("2026-01-20T12:00:00Z"),
        ]
        result = find_nearest_snapshot(sessions, "2026-01-12T12:00:00Z")
        assert result["timestamp"] == "2026-01-10T12:00:00Z"

    def test_nearest_after(self):
        sessions = [
            _session("2026-01-10T12:00:00Z"),
            _session("2026-01-20T12:00:00Z"),
        ]
        result = find_nearest_snapshot(sessions, "2026-01-18T12:00:00Z")
        assert result["timestamp"] == "2026-01-20T12:00:00Z"

    def test_empty_sessions(self):
        result = find_nearest_snapshot([], "2026-01-15")
        assert result is None

    def test_invalid_date(self):
        sessions = [_session("2026-01-15T12:00:00Z")]
        result = find_nearest_snapshot(sessions, "not-a-date")
        assert result is None
