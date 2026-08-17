"""
Tests for core.scheduler.BackgroundScheduler._check_stale_decisions (#58) --
the piece of Knowledge Decay Loop Closure that turns a purely-descriptive
stale-decision check into a persisted, idempotent review signal.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.memory.manager import MemoryManager
from core.scheduler import BackgroundScheduler

_OLD = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
_NOW = datetime.now(timezone.utc).isoformat()


def _seed(mm: MemoryManager, project: str, decisions: list[dict]) -> None:
    memory = mm.get_project_memory(project)
    memory["decisions"] = decisions
    mm.save_project_memory(project, memory)


def _referenced_stale_pair(prefix: str = "", topic: str = "cache") -> list[dict]:
    """Two old decisions sharing 2+ keywords -- both stale (400d old, well
    past the 90-day default half-life) and both referencing each other.

    `topic` picks distinct vocabulary so two pairs seeded together in the
    same decisions list don't cross-reference each other -- extra
    reference_count from an unrelated pair sharing words would push the
    score's ref_boost up enough to leave the "stale" tier entirely.
    """
    phrasing = {
        "cache": ("Delete old cache entries nightly", "Delete cache entries every deploy"),
        "audit": ("Archive expired audit logs monthly", "Archive audit logs every release"),
    }[topic]
    return [
        {"id": f"{prefix}a", "decision": phrasing[0], "timestamp": _OLD},
        {"id": f"{prefix}b", "decision": phrasing[1], "timestamp": _OLD},
    ]


# _check_stale_decisions skips any project with fewer than 3 decisions
# entirely (pre-existing guard, unrelated to #58) -- every test seeding
# just a referenced pair needs this padding to clear that gate. Shares no
# keywords with the pair, so it never itself becomes referenced/flagged.
_PAD = {"id": "pad", "decision": "Completely unrelated filler about deployment scripts", "timestamp": _OLD}


@pytest.fixture
def scheduler(tmp_path: Path) -> BackgroundScheduler:
    return BackgroundScheduler(tmp_path)


@pytest.fixture
def mm(tmp_path: Path) -> MemoryManager:
    return MemoryManager(str(tmp_path))


class TestCheckStaleDecisionsFlagging:
    async def test_stale_and_referenced_decision_gets_flagged(self, scheduler, mm):
        _seed(mm, "proj1", _referenced_stale_pair() + [_PAD])

        await scheduler._check_stale_decisions()

        memory = mm.get_project_memory("proj1")
        reviews = memory.get("decay_reviews", [])
        assert len(reviews) == 2
        flagged_ids = {r["decision_id"] for r in reviews}
        assert flagged_ids == {"a", "b"}
        assert all(r["review_status"] == "pending" for r in reviews)
        assert all(r["tier"] == "stale" for r in reviews)

    async def test_audit_event_written(self, scheduler, mm):
        _seed(mm, "proj1", _referenced_stale_pair() + [_PAD])

        await scheduler._check_stale_decisions()

        memory = mm.get_project_memory("proj1")
        events = [e for e in memory.get("audit_log", []) if e.get("event_type") == "decay_review_flagged"]
        assert len(events) == 1
        assert events[0]["count"] == 2

    async def test_unreferenced_stale_decision_is_not_flagged(self, scheduler, mm):
        # Three old decisions with no meaningful word overlap between any
        # pair -- reference_count stays 0 for all of them.
        _seed(mm, "proj1", [
            {"id": "solo", "decision": "Rotate TLS certificates for the ingress gateway", "timestamp": _OLD},
            {"id": "solo2", "decision": "Compress video thumbnails with a different codec", "timestamp": _OLD},
            {"id": "solo3", "decision": "Archive dormant customer support tickets", "timestamp": _OLD},
        ])

        await scheduler._check_stale_decisions()

        memory = mm.get_project_memory("proj1")
        assert memory.get("decay_reviews", []) == []

    async def test_fresh_decisions_are_not_flagged(self, scheduler, mm):
        decisions = [
            {"id": "a", "decision": "Delete old cache entries nightly", "timestamp": _NOW},
            {"id": "b", "decision": "Delete stale cache data on boot", "timestamp": _NOW},
        ]
        _seed(mm, "proj1", decisions)

        await scheduler._check_stale_decisions()

        memory = mm.get_project_memory("proj1")
        assert memory.get("decay_reviews", []) == []

    async def test_pinned_decision_is_skipped(self, scheduler, mm):
        decisions = _referenced_stale_pair() + [_PAD]
        decisions[0]["pinned"] = True
        _seed(mm, "proj1", decisions)

        await scheduler._check_stale_decisions()

        memory = mm.get_project_memory("proj1")
        flagged_ids = {r["decision_id"] for r in memory.get("decay_reviews", [])}
        assert "a" not in flagged_ids
        assert "b" in flagged_ids

    async def test_fewer_than_three_decisions_skips_project_entirely(self, scheduler, mm):
        _seed(mm, "proj1", _referenced_stale_pair())  # only 2 decisions

        await scheduler._check_stale_decisions()

        memory = mm.get_project_memory("proj1")
        assert memory.get("decay_reviews", []) == []


class TestCheckStaleDecisionsIdempotency:
    async def test_second_run_does_not_duplicate_flags(self, scheduler, mm):
        _seed(mm, "proj1", _referenced_stale_pair() + [_PAD])

        await scheduler._check_stale_decisions()
        await scheduler._check_stale_decisions()

        memory = mm.get_project_memory("proj1")
        assert len(memory.get("decay_reviews", [])) == 2

    async def test_second_run_flags_a_newly_added_decision(self, scheduler, mm):
        decisions = _referenced_stale_pair(topic="cache") + [_PAD]
        _seed(mm, "proj1", decisions)
        await scheduler._check_stale_decisions()

        # Distinct vocabulary (topic="audit") so this second pair doesn't
        # inflate the first pair's reference_count and push it out of the
        # "stale" tier -- see _referenced_stale_pair's docstring.
        decisions = decisions + _referenced_stale_pair(prefix="second_", topic="audit")
        _seed(mm, "proj1", decisions)
        await scheduler._check_stale_decisions()

        memory = mm.get_project_memory("proj1")
        flagged_ids = {r["decision_id"] for r in memory.get("decay_reviews", [])}
        assert flagged_ids == {"a", "b", "second_a", "second_b"}


class TestCheckStaleDecisionsMultiProject:
    async def test_projects_handled_independently(self, scheduler, mm):
        _seed(mm, "proj1", _referenced_stale_pair(prefix="p1_") + [_PAD])
        _seed(mm, "proj2", _referenced_stale_pair(prefix="p2_") + [_PAD])

        await scheduler._check_stale_decisions()

        m1 = mm.get_project_memory("proj1")
        m2 = mm.get_project_memory("proj2")
        assert {r["decision_id"] for r in m1.get("decay_reviews", [])} == {"p1_a", "p1_b"}
        assert {r["decision_id"] for r in m2.get("decay_reviews", [])} == {"p2_a", "p2_b"}

    async def test_one_projects_error_does_not_block_another(self, scheduler, mm, monkeypatch):
        _seed(mm, "proj1", _referenced_stale_pair(prefix="p1_") + [_PAD])
        _seed(mm, "proj2", _referenced_stale_pair(prefix="p2_") + [_PAD])

        real_get = MemoryManager.get_project_memory

        def _flaky_get(self, project_name):
            if project_name == "proj1":
                raise RuntimeError("simulated corrupt file")
            return real_get(self, project_name)

        monkeypatch.setattr(MemoryManager, "get_project_memory", _flaky_get)

        await scheduler._check_stale_decisions()

        monkeypatch.setattr(MemoryManager, "get_project_memory", real_get)
        m2 = mm.get_project_memory("proj2")
        assert {r["decision_id"] for r in m2.get("decay_reviews", [])} == {"p2_a", "p2_b"}


class TestScanGhostDecisions:
    """P4: _scan_ghost_decisions previously called
    detect_ghost_decisions(decisions, []) -- the *list* where the function
    expects the memory *dict*, and diff_data was always [] regardless.
    Both together meant this scan has been silently AttributeError-ing
    (caught by the outer try/except, logged as a warning) since it was
    added; these tests exercise the corrected version end-to-end with a
    mocked diff source standing in for real git subprocess calls."""

    NAMING_DECISION = "Use snake_case naming convention for all Python module functions"
    MATCHING_DIFF = (
        "--- a/src/utils.py\n+++ b/src/utils.py\n"
        "+# Apply naming convention to module functions\n"
        "+def getUserSettings(self):\n"
    )

    def _mock_diffs(self, monkeypatch, entries):
        monkeypatch.setattr("core.ghost.diff_source.recent_diffs", lambda memory, since_ts=None, max_diffs=50: entries)

    async def test_no_repo_no_diffs_is_a_clean_skip(self, scheduler, mm, monkeypatch):
        self._mock_diffs(monkeypatch, [])
        _seed(mm, "proj1", [{"id": "a", "decision": self.NAMING_DECISION, "timestamp": _NOW}])

        await scheduler._scan_ghost_decisions()

        memory = mm.get_project_memory("proj1")
        assert "ghost_scan" not in memory
        assert memory.get("audit_log", []) == []

    async def test_drift_detected_writes_audit_event_and_marker(self, scheduler, mm, monkeypatch):
        self._mock_diffs(monkeypatch, [{"file": "abc1234", "diff_text": self.MATCHING_DIFF}])
        _seed(mm, "proj1", [{"id": "a", "decision": self.NAMING_DECISION, "timestamp": _NOW}])

        await scheduler._scan_ghost_decisions()

        memory = mm.get_project_memory("proj1")
        assert memory["ghost_scan"]["last_diff_count"] == 1
        assert memory["ghost_scan"]["last_scan_ts"]
        events = [e for e in memory.get("audit_log", []) if e.get("event_type") == "ghost_scan_detected"]
        assert len(events) == 1
        assert events[0]["count"] >= 1

    async def test_clean_scan_with_diffs_updates_marker_without_audit_event(self, scheduler, mm, monkeypatch):
        unrelated_diff = "--- a/src/styles.css\n+++ b/src/styles.css\n+button { color: red; }\n"
        self._mock_diffs(monkeypatch, [{"file": "def5678", "diff_text": unrelated_diff}])
        _seed(mm, "proj1", [{"id": "a", "decision": "Use PostgreSQL for the database", "timestamp": _NOW}])

        await scheduler._scan_ghost_decisions()

        memory = mm.get_project_memory("proj1")
        assert memory["ghost_scan"]["last_diff_count"] == 1
        assert memory.get("audit_log", []) == []

    async def test_second_scan_passes_last_scan_ts_to_diff_source(self, scheduler, mm, monkeypatch):
        seen_since_ts = []

        def _fake_recent_diffs(memory, since_ts=None, max_diffs=50):
            seen_since_ts.append(since_ts)
            return [{"file": "abc1234", "diff_text": self.MATCHING_DIFF}]

        monkeypatch.setattr("core.ghost.diff_source.recent_diffs", _fake_recent_diffs)
        _seed(mm, "proj1", [{"id": "a", "decision": self.NAMING_DECISION, "timestamp": _NOW}])

        await scheduler._scan_ghost_decisions()
        await scheduler._scan_ghost_decisions()

        assert seen_since_ts[0] is None  # no prior marker on the first run
        assert seen_since_ts[1] is not None  # second run passes the first run's marker

    async def test_empty_project_is_skipped(self, scheduler, mm, monkeypatch):
        calls = []
        monkeypatch.setattr(
            "core.ghost.diff_source.recent_diffs",
            lambda memory, since_ts=None, max_diffs=50: calls.append(1) or [],
        )
        _seed(mm, "proj1", [])

        await scheduler._scan_ghost_decisions()

        assert calls == []  # never even asked for diffs -- no decisions to check


class TestCheckStaleDecisionsMalformedState:
    async def test_non_list_decay_reviews_does_not_raise(self, scheduler, mm):
        memory = mm.get_project_memory("proj1")
        memory["decisions"] = _referenced_stale_pair() + [_PAD]
        memory["decay_reviews"] = "corrupted"
        mm.save_project_memory("proj1", memory)

        await scheduler._check_stale_decisions()

        memory = mm.get_project_memory("proj1")
        assert len(memory["decay_reviews"]) == 2

    async def test_non_dict_entries_in_decisions_do_not_raise(self, scheduler, mm):
        decisions = _referenced_stale_pair() + ["not a dict", None, 42]
        _seed(mm, "proj1", decisions)

        await scheduler._check_stale_decisions()

        memory = mm.get_project_memory("proj1")
        assert len(memory.get("decay_reviews", [])) == 2


class TestScanAgentSurfaces:
    """P8: audit_agent_surface (core/agent_audit/scanner.py) existed but
    was only reachable via a manual POST /api/agent-audit/scan -- config
    drift between manual runs went undetected. Mocks the scanner itself
    (already unit-tested on its own) to focus these on the scheduling/
    persistence/audit-trail wiring."""

    _REPO_PATH = str(Path(__file__).parent.parent)  # any real dir

    def _mock_report(self, monkeypatch, report):
        monkeypatch.setattr("core.agent_audit.scanner.audit_agent_surface", lambda repo_path: report)

    def _fake_finding(self, severity="high"):
        from core.agent_audit import AuditFinding
        return AuditFinding(
            id="f1", category="secrets", severity=severity, file=".mcp.json",
            line=3, description="AWS Access Key detected", recommendation="Rotate the key",
        )

    def _fake_report(self, findings=None, grade="B"):
        from core.agent_audit import AuditReport
        findings = findings or []
        return AuditReport(
            findings=findings,
            files_scanned=[".mcp.json"],
            category_counts={},
            severity_distribution={f.severity: 1 for f in findings},
            grade=grade,
        )

    async def test_project_with_no_repo_path_is_skipped(self, scheduler, mm, monkeypatch):
        called = []
        monkeypatch.setattr(
            "core.agent_audit.scanner.audit_agent_surface",
            lambda repo_path: called.append(repo_path) or self._fake_report(),
        )
        _seed(mm, "proj1", [])

        await scheduler._scan_agent_surfaces()

        assert called == []
        memory = mm.get_project_memory("proj1")
        assert "agent_surface_audit" not in memory

    async def test_findings_persisted_and_audit_event_written(self, scheduler, mm, monkeypatch):
        self._mock_report(monkeypatch, self._fake_report(findings=[self._fake_finding()], grade="D"))
        memory = mm.get_project_memory("proj1")
        memory["repo_path"] = self._REPO_PATH
        mm.save_project_memory("proj1", memory)

        await scheduler._scan_agent_surfaces()

        memory = mm.get_project_memory("proj1")
        audit = memory["agent_surface_audit"]
        assert audit["grade"] == "D"
        assert len(audit["findings"]) == 1
        assert audit["findings"][0]["severity"] == "high"

        events = [e for e in memory.get("audit_log", []) if e.get("event_type") == "agent_surface_finding"]
        assert len(events) == 1
        assert events[0]["count"] == 1
        assert events[0]["grade"] == "D"

    async def test_clean_scan_updates_marker_without_audit_event(self, scheduler, mm, monkeypatch):
        self._mock_report(monkeypatch, self._fake_report(findings=[], grade="A"))
        memory = mm.get_project_memory("proj1")
        memory["repo_path"] = self._REPO_PATH
        mm.save_project_memory("proj1", memory)

        await scheduler._scan_agent_surfaces()

        memory = mm.get_project_memory("proj1")
        assert memory["agent_surface_audit"]["grade"] == "A"
        assert memory.get("audit_log", []) == []

    async def test_rescan_overwrites_previous_snapshot(self, scheduler, mm, monkeypatch):
        """Point-in-time, not accumulated -- a finding that's since been
        fixed must not linger in the persisted snapshot."""
        memory = mm.get_project_memory("proj1")
        memory["repo_path"] = self._REPO_PATH
        mm.save_project_memory("proj1", memory)

        self._mock_report(monkeypatch, self._fake_report(findings=[self._fake_finding()], grade="D"))
        await scheduler._scan_agent_surfaces()
        assert len(mm.get_project_memory("proj1")["agent_surface_audit"]["findings"]) == 1

        self._mock_report(monkeypatch, self._fake_report(findings=[], grade="A"))
        await scheduler._scan_agent_surfaces()
        final = mm.get_project_memory("proj1")["agent_surface_audit"]
        assert final["findings"] == []
        assert final["grade"] == "A"

    async def test_one_projects_scan_failure_does_not_block_another(self, scheduler, mm, monkeypatch):
        memory1 = mm.get_project_memory("proj1")
        memory1["repo_path"] = self._REPO_PATH
        mm.save_project_memory("proj1", memory1)
        memory2 = mm.get_project_memory("proj2")
        memory2["repo_path"] = self._REPO_PATH
        mm.save_project_memory("proj2", memory2)

        call_count = {"n": 0}

        def _first_call_crashes(repo_path):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("simulated scan crash")
            return self._fake_report(findings=[self._fake_finding()], grade="D")

        monkeypatch.setattr("core.agent_audit.scanner.audit_agent_surface", _first_call_crashes)

        await scheduler._scan_agent_surfaces()

        results = [mm.get_project_memory(p).get("agent_surface_audit") for p in ("proj1", "proj2")]
        assert any(r and r["grade"] == "D" for r in results)
