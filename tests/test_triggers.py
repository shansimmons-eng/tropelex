"""Tests for core/triggers: the event->check registry, the pre_push checks
built on it, and the tag_gate primitive used by add_decision."""

from __future__ import annotations

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
