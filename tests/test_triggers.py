"""Tests for core/triggers: the event->check registry, the pre_push checks
built on it, and the tag_gate primitive used by add_decision."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from core.triggers.registry import CheckResult, TriggerRegistry
from core.triggers.tag_gate import SAFETY_CATEGORIES, TagRequiredError, require_tag


class TestTriggerRegistry:
    def test_run_calls_registered_checks_in_order(self):
        registry = TriggerRegistry()
        calls = []

        @registry.check("pre_push")
        def first(context):
            calls.append("first")
            return CheckResult(name="first", event="pre_push", passed=True, detail="ok")

        @registry.check("pre_push")
        def second(context):
            calls.append("second")
            return CheckResult(name="second", event="pre_push", passed=True, detail="ok")

        results = registry.run("pre_push", context={})
        assert calls == ["first", "second"]
        assert [r.name for r in results] == ["first", "second"]

    def test_run_on_unregistered_event_returns_empty(self):
        registry = TriggerRegistry()
        assert registry.run("nonexistent_event", context={}) == []

    def test_check_that_raises_becomes_a_blocking_failed_result(self):
        registry = TriggerRegistry()

        @registry.check("pre_push")
        def broken(context):
            raise ValueError("boom")

        results = registry.run("pre_push", context={})
        assert len(results) == 1
        assert results[0].passed is False
        assert results[0].severity == "block"
        assert "boom" in results[0].detail

    def test_one_broken_check_does_not_stop_the_others(self):
        registry = TriggerRegistry()

        @registry.check("pre_push")
        def broken(context):
            raise ValueError("boom")

        @registry.check("pre_push")
        def fine(context):
            return CheckResult(name="fine", event="pre_push", passed=True, detail="ok")

        results = registry.run("pre_push", context={})
        assert [r.passed for r in results] == [False, True]

    def test_registered_events_lists_only_events_with_checks(self):
        registry = TriggerRegistry()

        @registry.check("post_commit")
        def noop(context):
            return CheckResult(name="noop", event="post_commit", passed=True, detail="ok")

        assert registry.registered_events() == ["post_commit"]


class TestRecordTriggerRun:
    def test_run_persisted_and_bounded_to_50(self):
        from core.triggers.registry import record_trigger_run

        class _FakeMM:
            def __init__(self):
                self.memory = {}

            def get_project_memory(self, project):
                return self.memory.setdefault(project, {})

            def save_project_memory(self, project, memory):
                self.memory[project] = memory

        mm = _FakeMM()
        for i in range(55):
            record_trigger_run(
                "demo", mm, "pre_push",
                [CheckResult(name=f"c{i}", event="pre_push", passed=True, detail="ok")],
            )

        runs = mm.memory["demo"]["trigger_runs"]
        assert len(runs) == 50
        # bounded to the most recent 50 — the earliest 5 firings fell off
        assert runs[0]["results"][0]["name"] == "c5"
        assert runs[-1]["results"][0]["name"] == "c54"
        assert all(r["all_passed"] for r in runs)


class TestPrePushChecks:
    """Runs the real checks against this repo's own source tree — the
    findings are informational (both checks are severity="warn"), this just
    confirms the scan itself doesn't crash and returns well-formed results.
    """

    def test_checks_run_against_this_repo_without_crashing(self):
        from core.triggers import checks  # noqa: F401 - registers on import
        from core.triggers.registry import registry

        repo_root = Path(__file__).resolve().parent.parent
        results = registry.run("pre_push", context={"repo_path": str(repo_root)})

        names = {r.name for r in results}
        assert "check_every_endpoint_has_a_test" in names
        assert "check_error_handling_present" in names
        assert "check_drift_bench_coverage" in names
        assert "check_schema_version_awareness" in names
        for r in results:
            assert isinstance(r.passed, bool)
            assert r.detail

    def test_untested_endpoint_is_flagged(self, tmp_path):
        from core.triggers.checks import check_every_endpoint_has_a_test

        (tmp_path / "core").mkdir()
        router_dir = tmp_path / "core" / "widgets"
        router_dir.mkdir()
        (router_dir / "router.py").write_text(
            '@widgets_router.get("/{project}/widgets/list")\n'
            "async def list_widgets(project: str):\n"
            "    return []\n"
        )
        (tmp_path / "tests").mkdir()

        result = check_every_endpoint_has_a_test({"repo_path": str(tmp_path)})
        assert result.passed is False
        assert "widgets/list" in result.detail

    def test_tested_endpoint_passes(self, tmp_path):
        from core.triggers.checks import check_every_endpoint_has_a_test

        (tmp_path / "core" / "widgets").mkdir(parents=True)
        (tmp_path / "core" / "widgets" / "router.py").write_text(
            '@widgets_router.get("/{project}/widgets/list")\n'
            "async def list_widgets(project: str):\n"
            "    return []\n"
        )
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_widgets.py").write_text(
            'def test_list(): assert "/widgets/list" in "GET /demo/widgets/list"\n'
        )

        result = check_every_endpoint_has_a_test({"repo_path": str(tmp_path)})
        assert result.passed is True

    def test_unguarded_endpoint_is_flagged(self, tmp_path):
        from core.triggers.checks import check_error_handling_present

        router_dir = tmp_path / "core" / "widgets"
        router_dir.mkdir(parents=True)
        (router_dir / "router.py").write_text(
            '@widgets_router.post("/{project}/widgets/create")\n'
            "async def create_widget(project: str):\n"
            "    return {}\n"
        )

        result = check_error_handling_present({"repo_path": str(tmp_path)})
        assert result.passed is False
        assert "widgets/create" in result.detail

    def test_guarded_endpoint_passes(self, tmp_path):
        from core.triggers.checks import check_error_handling_present

        router_dir = tmp_path / "core" / "widgets"
        router_dir.mkdir(parents=True)
        (router_dir / "router.py").write_text(
            '@widgets_router.post("/{project}/widgets/create")\n'
            "async def create_widget(project: str):\n"
            "    try:\n"
            "        return {}\n"
            "    except Exception as exc:\n"
            "        raise\n"
        )

        result = check_error_handling_present({"repo_path": str(tmp_path)})
        assert result.passed is True

    def test_server_py_app_routes_are_now_visible(self, tmp_path):
        """core/tropebook/web/server.py hosts ~180 routes directly on
        `app`, not a X_router in its own core/*/router.py file -- the
        plain glob missed all of them until _EXTRA_ROUTE_FILES was added.
        This confirms the blind spot is actually closed, not just that
        the glob doesn't crash on a file that happens to be absent."""
        from core.triggers.checks import check_error_handling_present

        web_dir = tmp_path / "core" / "tropebook" / "web"
        web_dir.mkdir(parents=True)
        (web_dir / "server.py").write_text(
            '@app.get("/api/widgets/list")\n'
            "async def list_widgets():\n"
            "    return []\n"
        )

        result = check_error_handling_present({"repo_path": str(tmp_path)})
        assert result.passed is False
        assert "widgets/list" in result.detail

    def test_server_py_absent_does_not_break_the_scan(self, tmp_path):
        """No core/tropebook/web/server.py in this tmp tree -- _iter_router_
        files' is_file() guard must skip it silently, not raise."""
        from core.triggers.checks import check_every_endpoint_has_a_test

        (tmp_path / "core").mkdir()
        (tmp_path / "tests").mkdir()
        result = check_every_endpoint_has_a_test({"repo_path": str(tmp_path)})
        assert result.passed is True


def _git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=path, check=True)


def _commit_all(path: Path, msg: str) -> None:
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=path, check=True)


class TestSchemaVersionAwarenessCheck:
    """Versioning policy (core/version.py): warns when a push touches a
    known cross-install wire format without also touching core/version.py.
    Uses a real local git repo with a faked origin/main ref -- no actual
    remote/network involved, `git update-ref` alone is enough to give the
    check something to diff against."""

    def _repo_with_base(self, tmp_path: Path) -> Path:
        """A repo with an initial commit, and refs/remotes/origin/main
        pointed at it -- simulates "this is what's already on the
        remote," so a later local-only commit is what the check sees as
        the push's actual diff."""
        _git_repo(tmp_path)
        (tmp_path / "README.md").write_text("hello\n")
        _commit_all(tmp_path, "initial")
        base_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True,
        ).stdout.strip()
        subprocess.run(
            ["git", "update-ref", "refs/remotes/origin/main", base_sha], cwd=tmp_path, check=True,
        )
        return tmp_path

    def test_no_base_ref_skips_gracefully(self, tmp_path):
        from core.triggers.checks import check_schema_version_awareness

        _git_repo(tmp_path)
        (tmp_path / "README.md").write_text("hello\n")
        _commit_all(tmp_path, "initial")
        # No refs/remotes/origin/main exists at all -- git diff against it fails.
        result = check_schema_version_awareness({"repo_path": str(tmp_path)})
        assert result.passed is True
        assert "unavailable" in result.detail

    def test_no_schema_relevant_files_changed_passes(self, tmp_path):
        from core.triggers.checks import check_schema_version_awareness

        repo = self._repo_with_base(tmp_path)
        (repo / "README.md").write_text("hello again\n")
        _commit_all(repo, "unrelated change")

        result = check_schema_version_awareness({"repo_path": str(repo)})
        assert result.passed is True
        assert "no schema-relevant files changed" in result.detail

    def test_schema_relevant_file_changed_without_marker_passes(self, tmp_path):
        """Touching a schema-relevant file at all isn't enough to warn --
        only touching one of the actual known schema symbols is."""
        from core.triggers.checks import check_schema_version_awareness

        repo = self._repo_with_base(tmp_path)
        (repo / "core").mkdir()
        (repo / "core" / "benchmarks").mkdir()
        (repo / "core" / "benchmarks" / "router.py").write_text(
            "# unrelated comment change, no schema symbol here\n"
        )
        _commit_all(repo, "touch benchmarks router, no schema symbol")

        result = check_schema_version_awareness({"repo_path": str(repo)})
        assert result.passed is True
        assert "no known schema symbol touched" in result.detail

    def test_schema_symbol_touched_without_version_bump_warns(self, tmp_path):
        from core.triggers.checks import check_schema_version_awareness

        repo = self._repo_with_base(tmp_path)
        (repo / "core").mkdir()
        (repo / "core" / "benchmarks").mkdir()
        (repo / "core" / "benchmarks" / "router.py").write_text(
            "async def benchmarks_export():\n    return {}\n"
        )
        _commit_all(repo, "add benchmarks_export")

        result = check_schema_version_awareness({"repo_path": str(repo)})
        assert result.passed is False
        assert result.severity == "warn"
        assert "benchmarks_export" in result.detail
        assert "core/version.py" in result.detail

    def test_schema_symbol_touched_with_version_bump_passes(self, tmp_path):
        from core.triggers.checks import check_schema_version_awareness

        repo = self._repo_with_base(tmp_path)
        (repo / "core").mkdir()
        (repo / "core" / "benchmarks").mkdir()
        (repo / "core" / "benchmarks" / "router.py").write_text(
            "async def benchmarks_export():\n    return {}\n"
        )
        (repo / "core" / "version.py").write_text("MEMORY_SCHEMA_VERSION = 2\n")
        _commit_all(repo, "add benchmarks_export, bump schema version")

        result = check_schema_version_awareness({"repo_path": str(repo)})
        assert result.passed is True
        assert "core/version.py was also touched" in result.detail

    def test_sync_exporter_symbol_touched_without_version_bump_warns(self, tmp_path):
        """#provenance: core/sync/exporter.py + importer.py were untracked
        by this check entirely before -- a real gap, same class of thing
        the account_export/import blind spot was, fixed here by adding
        them to _SCHEMA_RELEVANT_FILES/_SCHEMA_RELEVANT_MARKERS."""
        from core.triggers.checks import check_schema_version_awareness

        repo = self._repo_with_base(tmp_path)
        (repo / "core").mkdir()
        (repo / "core" / "sync").mkdir()
        (repo / "core" / "sync" / "exporter.py").write_text(
            "def export_memory_data(base_path):\n    return b''\n"
        )
        _commit_all(repo, "touch sync exporter's schema-relevant function")

        result = check_schema_version_awareness({"repo_path": str(repo)})
        assert result.passed is False
        assert result.severity == "warn"
        assert "export_memory_data" in result.detail

    def test_custom_diff_base_is_respected(self, tmp_path):
        """context['diff_base'] overrides the default origin/main -- for a
        repo using a different default branch name."""
        from core.triggers.checks import check_schema_version_awareness

        _git_repo(tmp_path)
        (tmp_path / "README.md").write_text("hello\n")
        _commit_all(tmp_path, "initial")
        base_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True,
        ).stdout.strip()
        subprocess.run(
            ["git", "update-ref", "refs/remotes/origin/develop", base_sha], cwd=tmp_path, check=True,
        )
        (tmp_path / "core").mkdir()
        (tmp_path / "core" / "benchmarks").mkdir()
        (tmp_path / "core" / "benchmarks" / "router.py").write_text(
            "class BenchmarkImportRequest: pass\n"
        )
        _commit_all(tmp_path, "add BenchmarkImportRequest")

        result = check_schema_version_awareness(
            {"repo_path": str(tmp_path), "diff_base": "origin/develop"},
        )
        assert result.passed is False
        assert "BenchmarkImportRequest" in result.detail


class TestDriftBenchCheck:
    """#60: severity must always be "warn", never "block" -- the
    test-passing-reward-hacking category is a known, permanent
    0%-detection scenario, so blocking on any undetected scenario would
    brick every push forever."""

    def test_severity_is_always_warn(self):
        from core.triggers.checks import check_drift_bench_coverage

        result = check_drift_bench_coverage({"repo_path": "."})
        assert result.severity == "warn"

    def test_passes_when_no_false_positives_or_errors(self):
        from core.triggers.checks import check_drift_bench_coverage

        result = check_drift_bench_coverage({"repo_path": "."})
        # Real corpus today: 0% false positives, 0 errored scenarios.
        assert result.passed is True
        assert "detection_rate=" in result.detail
        assert "false_positive_rate=" in result.detail

    def test_run_failure_is_reported_not_raised(self, monkeypatch):
        """check_drift_bench_coverage imports run_suite locally inside the
        function body, so patching core.driftbench.report.run_suite (the
        real source, resolved at call time) is what actually takes effect
        here -- not a module-level attribute on core.triggers.checks."""
        import core.driftbench.report as report_mod

        def _boom(*a, **kw):
            raise RuntimeError("driftbench blew up")

        monkeypatch.setattr(report_mod, "run_suite", _boom)

        from core.triggers.checks import check_drift_bench_coverage
        result = check_drift_bench_coverage({"repo_path": "."})
        assert result.severity == "warn"
        assert result.passed is False
        assert "failed to run" in result.detail

    def test_false_positive_fails_the_check_but_still_warns(self, monkeypatch):
        import core.driftbench.report as report_mod

        fake_report = {
            "detection_rate": 1.0, "false_positive_rate": 0.5,
            "scenario_count": 2, "errored_scenarios": [],
        }
        monkeypatch.setattr(report_mod, "run_suite", lambda scenarios: fake_report)

        from core.triggers.checks import check_drift_bench_coverage
        result = check_drift_bench_coverage({"repo_path": "."})
        assert result.passed is False
        assert result.severity == "warn"


class TestTagGate:
    def test_missing_category_raises(self):
        with pytest.raises(TagRequiredError) as exc_info:
            require_tag(None, suggested="monitoring")
        assert exc_info.value.suggested == "monitoring"

    def test_invalid_category_raises(self):
        with pytest.raises(TagRequiredError):
            require_tag("not-a-real-category")

    def test_valid_category_is_returned(self):
        assert require_tag("governance") == "governance"

    def test_general_is_a_valid_explicit_choice(self):
        # "general" isn't banned — the gate is about an explicit choice
        # being made, not about which category was picked.
        assert require_tag("general") == "general"

    def test_to_dict_carries_suggestion_and_valid_set(self):
        try:
            require_tag(None, suggested="alignment")
        except TagRequiredError as exc:
            d = exc.to_dict()
            assert d["error"] == "tag_required"
            assert d["suggested"] == "alignment"
            assert set(d["valid_categories"]) == SAFETY_CATEGORIES
        else:
            pytest.fail("expected TagRequiredError")
