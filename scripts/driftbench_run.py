#!/usr/bin/env python3
"""
One-command Drift-Bench run (#111) -- reproduces the same table published
in docs/cais-summary.md, externally, without needing the dashboard server
running or any Tropelex-specific setup beyond a checkout of this repo.

    python3 scripts/driftbench_run.py            # runs and persists
    python3 scripts/driftbench_run.py --no-persist  # dry run, no disk write

Runs the real scenario corpus (core/driftbench/scenarios.py) against real,
production Tropelex detectors -- not mocks, not a simulation of them.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.driftbench.report import run_suite
from core.driftbench.scenarios import build_corpus

# Same display wording docs/cais-summary.md's table uses -- kept as an
# explicit mapping (not a mechanical underscore->title-case transform)
# since a few of these need a hyphen the raw category constant doesn't
# have ("tool_output_injection" -> "Tool-output injection"). Update this
# alongside cais-summary.md's table if a category's wording changes there.
_DISPLAY_NAMES = {
    "silent_objective_drift": "Silent objective drift",
    "unresolved_conflicting_decisions": "Unresolved conflicting decisions",
    "tool_output_injection": "Tool-output injection",
    "handoff_constraint_dropping": "Handoff constraint-dropping",
    "test_passing_reward_hacking": "Test-passing reward hacking",
    "multi_step_drift": "Multi-step drift",
}


def _fmt_rate(rate: float | None) -> str:
    return "n/a" if rate is None else str(rate)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-persist", action="store_true",
        help="Dry run -- don't write memory/driftbench/latest.json",
    )
    args = parser.parse_args()

    corpus = build_corpus()
    report = run_suite(corpus, persist=not args.no_persist)

    print(f"Drift-Bench corpus v{report['corpus_version']}, {report['scenario_count']} scenarios")
    print(f"Overall detection rate: {_fmt_rate(report['detection_rate'])}"
          f"  |  false-positive rate: {_fmt_rate(report['false_positive_rate'])}\n")

    print("| Category | Detection rate | False-positive rate |")
    print("|---|---|---|")
    for category, stats in report["by_category"].items():
        name = _DISPLAY_NAMES.get(category, category)
        print(f"| {name} | {_fmt_rate(stats['detection_rate'])} | {_fmt_rate(stats['false_positive_rate'])} |")

    if report["errored_scenarios"]:
        print(f"\nScenarios that raised (counted as not-detected): {report['errored_scenarios']}")

    if not args.no_persist:
        print("\nPersisted to memory/driftbench/latest.json")


if __name__ == "__main__":
    main()
