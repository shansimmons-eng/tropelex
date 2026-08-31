"""
Tests for core.driftbench — the Drift-Bench Evaluation Harness (#60).

Two layers: the real scenario corpus (calls actual Tropelex detectors,
verifies each one behaves as designed) and run_suite's aggregation math
(tested against small synthetic scenario lists with known ground truth,
not the real corpus, so the arithmetic assertions don't depend on
detector internals shifting later).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.driftbench import CATEGORIES, Scenario, ScenarioResult
from core.driftbench.report import _aggregate, load_latest, run_suite
from core.driftbench.scenarios import build_corpus


class TestScenarioCorpus:
    """Runs each real scenario against the real detector it targets."""

    def test_corpus_has_at_least_one_positive_and_negative_per_category(self):
        # #100 added a second reward_hacking pair (2 positive, 2 negative)
        # and a new multi_step_drift category (1 positive, 1 negative), so
        # category size is no longer fixed at exactly 2 -- the invariant
        # that matters is every category having ground truth in both
        # directions, not a specific count.
        corpus = build_corpus()
        assert len(corpus) == 14
        for category in CATEGORIES:
            cat_scenarios = [s for s in corpus if s.category == category]
            assert len(cat_scenarios) >= 2
            assert sum(1 for s in cat_scenarios if s.expect_detection) >= 1
            assert sum(1 for s in cat_scenarios if not s.expect_detection) >= 1

    def test_scenario_ids_are_unique(self):
        corpus = build_corpus()
        ids = [s.id for s in corpus]
        assert len(ids) == len(set(ids))

    @pytest.mark.parametrize("scenario_id,expected", [
        ("ghost_naming_drift", True),
        ("ghost_unrelated_diff", False),
        ("contradiction_framework_conflict", True),
        ("contradiction_unrelated_pair", False),
        ("injection_ignore_instructions", True),
        ("injection_clean_text", False),
        ("handoff_completeness_check_flags_real_violation", True),
        ("handoff_real_pipeline_protects_critical_decision", False),
        ("reward_hacking_clean_diff", False),
        ("reward_hacking_test_gaming_clean", False),
        ("multi_step_drift_benign_sequence", False),
    ])
    def test_scenario_matches_ground_truth(self, scenario_id, expected):
        """Every scenario except the deliberately-undefended reward-hacking
        positive case must match its ground-truth label -- these are the
        real, currently-working detectors."""
        corpus = {s.id: s for s in build_corpus()}
        assert corpus[scenario_id].run() is expected

    def test_reward_hacking_positive_is_a_documented_known_gap(self):
        """Ground truth: this diff IS a real violation (expect_detection=
        True). Nothing in this codebase defends against it today -- the
        real detector call must come back False, and that's the honest,
        expected result being measured, not a scenario bug. #67 tried an
        embedding-based rescue for exactly this case and found (real
        dry-run against tropelex's own decisions) that it can't be safely
        thresholded -- see core/driftbench/scenarios.py's module docstring
        and wishlist.md #67."""
        corpus = {s.id: s for s in build_corpus()}
        scenario = corpus["reward_hacking_keyword_evasion"]
        assert scenario.expect_detection is True
        assert scenario.run() is False

    def test_reward_hacking_test_gaming_is_a_documented_known_gap(self):
        """Second reward-hacking evasion shape (#100): weakening a test
        assertion into a tautology instead of adding unrelated code. Same
        honest gap as the original backdoor scenario, for the same reason
        -- Ghost only compares decision text against diff text, it has no
        concept of an assertion that no longer asserts anything."""
        corpus = {s.id: s for s in build_corpus()}
        scenario = corpus["reward_hacking_test_gaming"]
        assert scenario.expect_detection is True
        assert scenario.run() is False

    def test_multi_step_drift_positive_is_a_documented_known_gap(self):
        """#100: a decision violated gradually across 3 individually-clean
        diffs. Ground truth is a real violation (expect_detection=True);
        the honest measured result is undetected, because Ghost checks one
        diff at a time with no session-level memory -- confirmed by
        running each of the 3 diffs against the real detector separately
        (see core/driftbench/scenarios.py's module docstring)."""
        corpus = {s.id: s for s in build_corpus()}
        scenario = corpus["multi_step_drift_gradual_removal"]
        assert scenario.expect_detection is True
        assert scenario.run() is False


class TestAggregate:
    """Aggregation math against small synthetic scenario lists with known
    ground truth -- independent of what the real detectors currently do."""

    def _result(self, category="cat_a", expected=True, detected=True, error=None):
        return ScenarioResult(
            scenario_id=f"s-{category}-{expected}-{detected}", category=category,
            expected=expected, detected=detected, duration_ms=1.0, error=error,
        )

    def test_perfect_detection_and_no_false_positives(self):
        results = [
            self._result(expected=True, detected=True),
            self._result(expected=False, detected=False),
        ]
        report = _aggregate(results)
        assert report["detection_rate"] == 1.0
        assert report["false_positive_rate"] == 0.0

    def test_missed_detection_lowers_detection_rate(self):
        results = [
            self._result(expected=True, detected=True),
            self._result(expected=True, detected=False),
        ]
        report = _aggregate(results)
        assert report["detection_rate"] == 0.5

    def test_false_positive_raises_fp_rate(self):
        results = [
            self._result(expected=False, detected=True),
            self._result(expected=False, detected=False),
        ]
        report = _aggregate(results)
        assert report["false_positive_rate"] == 0.5

    def test_empty_positives_gives_none_not_zero(self):
        """No 'should detect' scenarios at all isn't a 0% detection rate --
        it's an undefined one. None, not 0.0, matters here: 0.0 would read
        as 'total failure' on a metric that was never actually measured."""
        results = [self._result(expected=False, detected=False)]
        report = _aggregate(results)
        assert report["detection_rate"] is None

    def test_empty_results_does_not_raise(self):
        report = _aggregate([])
        assert report["scenario_count"] == 0
        assert report["detection_rate"] is None
        assert report["false_positive_rate"] is None

    def test_by_category_present_for_every_known_category(self):
        report = _aggregate([self._result(category=CATEGORIES[0])])
        assert set(report["by_category"].keys()) == set(CATEGORIES)

    def test_errored_scenario_counted_as_not_detected(self):
        results = [self._result(expected=True, detected=False, error="boom")]
        report = _aggregate(results)
        assert report["detection_rate"] == 0.0
        assert report["errored_scenarios"] == [results[0].scenario_id]

    def test_check_duration_ms_shape(self):
        results = [self._result(), self._result(category="cat_b")]
        report = _aggregate(results)
        assert "mean" in report["check_duration_ms"]
        assert "max" in report["check_duration_ms"]
        assert len(report["check_duration_ms"]["per_scenario"]) == 2


class TestScenarioResultCorrect:
    def test_correct_when_matches_and_no_error(self):
        r = ScenarioResult("s1", "cat", expected=True, detected=True, duration_ms=1.0)
        assert r.correct is True

    def test_incorrect_when_mismatched(self):
        r = ScenarioResult("s1", "cat", expected=True, detected=False, duration_ms=1.0)
        assert r.correct is False

    def test_incorrect_when_errored_even_if_values_happen_to_match(self):
        r = ScenarioResult("s1", "cat", expected=False, detected=False, duration_ms=1.0, error="boom")
        assert r.correct is False


class TestRunSuiteDefensiveness:
    """A scenario whose run() raises must not crash the whole suite."""

    def _raising_scenario(self):
        def _boom():
            raise RuntimeError("scenario blew up")
        return Scenario(id="broken", category=CATEGORIES[0], description="", expect_detection=True, run=_boom)

    def test_raising_scenario_does_not_crash_run_suite(self):
        report = run_suite([self._raising_scenario()], persist=False)
        assert report["scenario_count"] == 1
        assert report["errored_scenarios"] == ["broken"]
        assert report["detection_rate"] == 0.0

    def test_mix_of_raising_and_normal_scenarios(self):
        normal = Scenario(id="ok", category=CATEGORIES[0], description="", expect_detection=False, run=lambda: False)
        report = run_suite([self._raising_scenario(), normal], persist=False)
        assert report["scenario_count"] == 2
        assert report["errored_scenarios"] == ["broken"]


class TestPersistence:
    def test_persist_false_does_not_write_to_disk(self, tmp_path):
        report = run_suite(build_corpus(), persist=False, storage_dir=tmp_path)
        assert not (tmp_path / "latest.json").exists()
        assert report["scenario_count"] == 14

    def test_persist_true_writes_and_load_latest_matches(self, tmp_path):
        written = run_suite(build_corpus(), persist=True, storage_dir=tmp_path)
        assert (tmp_path / "latest.json").exists()
        loaded = load_latest(storage_dir=tmp_path)
        assert loaded == written

    def test_load_latest_none_when_never_run(self, tmp_path):
        assert load_latest(storage_dir=tmp_path) is None

    def test_load_latest_handles_corrupted_file(self, tmp_path):
        tmp_path.mkdir(exist_ok=True)
        (tmp_path / "latest.json").write_text("not valid json {{{")
        assert load_latest(storage_dir=tmp_path) is None

    def test_persist_failure_does_not_raise(self, tmp_path, monkeypatch):
        """A read-only/unwritable target dir must not crash run_suite --
        the computed report is still valid and should still come back."""
        target = tmp_path / "unwritable"
        target.mkdir()
        target.chmod(0o500)
        try:
            report = run_suite(build_corpus(), persist=True, storage_dir=target / "nested" / "deeper")
            assert report["scenario_count"] == 14
        finally:
            target.chmod(0o700)
