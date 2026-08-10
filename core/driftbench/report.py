"""
Drift-Bench report aggregation + publishing (wishlist #60).

`run_suite` executes a scenario corpus against real production detectors,
aggregates the results, and persists them to memory/driftbench/latest.json
so the numbers are checkable (the "Published metrics" feature the wishlist
names) rather than only ever computed live and discarded.

Deliberately does NOT compute an override_rate here -- that's
core/prevention_report.py's job, reading a real project's audit_log.
Drift-Bench measures something different and complementary: synthetic
ground-truth detection accuracy against a fixed scenario corpus, not live
project history.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.driftbench import CATEGORIES, Scenario, ScenarioResult

logger = logging.getLogger("tropelex.driftbench")

_REPORT_FILENAME = "latest.json"


def _default_storage_dir() -> Path:
    # Same base-path resolution MemoryManager itself uses, reused rather
    # than duplicated -- keeps memory/driftbench/ next to memory/tropebook/,
    # memory/feeds/, etc. under the one real repo root.
    from core.memory.manager import MemoryManager

    return MemoryManager().base_path / "memory" / "driftbench"


def _run_one(scenario: Scenario) -> ScenarioResult:
    """Execute a single scenario defensively -- a scenario whose run()
    raises must not crash the whole suite or silently count as a pass."""
    start = time.monotonic()
    detected = False
    error: str | None = None
    try:
        detected = bool(scenario.run())
    except Exception as exc:
        logger.error("Drift-Bench scenario '%s' raised: %s", scenario.id, exc)
        error = str(exc)
        detected = False
    duration_ms = (time.monotonic() - start) * 1000
    return ScenarioResult(
        scenario_id=scenario.id,
        category=scenario.category,
        expected=scenario.expect_detection,
        detected=detected,
        duration_ms=round(duration_ms, 3),
        error=error,
    )


def _rate(numerator: int, denominator: int) -> float | None:
    """None (not 0.0) when there's nothing to measure -- an empty
    denominator isn't a 0% rate, it's an undefined one."""
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


def _aggregate(results: list[ScenarioResult]) -> dict[str, Any]:
    positives = [r for r in results if r.expected]
    negatives = [r for r in results if not r.expected]
    true_positives = [r for r in positives if r.detected]
    false_positives = [r for r in negatives if r.detected]
    errored = [r for r in results if r.error is not None]

    durations = [r.duration_ms for r in results]
    check_duration_ms = {
        "mean": round(sum(durations) / len(durations), 3) if durations else None,
        "max": max(durations) if durations else None,
        "per_scenario": {r.scenario_id: r.duration_ms for r in results},
    }

    by_category: dict[str, Any] = {}
    for category in CATEGORIES:
        cat_results = [r for r in results if r.category == category]
        cat_positives = [r for r in cat_results if r.expected]
        cat_negatives = [r for r in cat_results if not r.expected]
        by_category[category] = {
            "scenario_count": len(cat_results),
            "detection_rate": _rate(sum(1 for r in cat_positives if r.detected), len(cat_positives)),
            "false_positive_rate": _rate(sum(1 for r in cat_negatives if r.detected), len(cat_negatives)),
        }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scenario_count": len(results),
        "detection_rate": _rate(len(true_positives), len(positives)),
        "false_positive_rate": _rate(len(false_positives), len(negatives)),
        "check_duration_ms": check_duration_ms,
        "by_category": by_category,
        "errored_scenarios": [r.scenario_id for r in errored],
        "results": [
            {
                "scenario_id": r.scenario_id, "category": r.category,
                "expected": r.expected, "detected": r.detected,
                "correct": r.correct, "duration_ms": r.duration_ms, "error": r.error,
            }
            for r in results
        ],
    }


def _persist(report: dict[str, Any], storage_dir: Path | None) -> None:
    """Write the report to disk. Failure here must never break the caller
    -- the computed report is still valid and already returned regardless
    of whether it could be saved."""
    try:
        target_dir = storage_dir or _default_storage_dir()
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / _REPORT_FILENAME).write_text(json.dumps(report, indent=2))
    except Exception as exc:
        logger.error("Drift-Bench report persist failed: %s", exc)


def run_suite(
    scenarios: list[Scenario], *, persist: bool = True, storage_dir: Path | None = None,
) -> dict[str, Any]:
    """Run every scenario, aggregate, and (by default) persist to
    memory/driftbench/latest.json. Pass persist=False for a dry run
    (e.g. unit tests that don't want disk side effects)."""
    results = [_run_one(s) for s in scenarios]
    report = _aggregate(results)
    if persist:
        _persist(report, storage_dir)
    return report


def load_latest(storage_dir: Path | None = None) -> dict[str, Any] | None:
    """Read the last-persisted report, or None if the suite has never run."""
    target_dir = storage_dir or _default_storage_dir()
    path = target_dir / _REPORT_FILENAME
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Drift-Bench latest.json unreadable: %s", exc)
        return None
