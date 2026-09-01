"""
Drift-Bench Evaluation Harness (wishlist #60, expanded by #100) — a small,
deterministic scenario suite measuring how well Tropelex's real detectors
(Ghost, Contradictions, Injection Sentinel) and a new handoff-completeness
check actually catch six drift/injection threat categories, run against
production code directly, not mocks.

Three categories have no existing defense in this codebase at all
(test-passing reward hacking, multi-step drift, and handoff
constraint-dropping wasn't checked by anything before this module) --
their scenarios exist to measure and publish that gap honestly, not to
manufacture a pass. See core/driftbench/scenarios.py's module docstring
for the full accounting.

No I/O in this module -- pure dataclasses only, same shape as
core/knowledge_decay.py and core/prevention_report.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

# The five original threat categories from wishlist.md #60, plus
# multi-step drift (wishlist #100): a decision violated gradually across
# several individually-innocuous diffs rather than one obviously-bad one.
SILENT_OBJECTIVE_DRIFT = "silent_objective_drift"
UNRESOLVED_CONFLICTING_DECISIONS = "unresolved_conflicting_decisions"
TOOL_OUTPUT_INJECTION = "tool_output_injection"
HANDOFF_CONSTRAINT_DROPPING = "handoff_constraint_dropping"
TEST_PASSING_REWARD_HACKING = "test_passing_reward_hacking"
MULTI_STEP_DRIFT = "multi_step_drift"

CATEGORIES = (
    SILENT_OBJECTIVE_DRIFT,
    UNRESOLVED_CONFLICTING_DECISIONS,
    TOOL_OUTPUT_INJECTION,
    HANDOFF_CONSTRAINT_DROPPING,
    TEST_PASSING_REWARD_HACKING,
    MULTI_STEP_DRIFT,
)

# #111: the corpus was never explicitly versioned before this -- a
# published metric (docs/cais-summary.md's table) implicitly meant
# "whatever the corpus happened to contain the day someone ran it,"
# which a later scenario addition could silently redefine without
# anyone noticing the old number no longer refers to the same test.
# Bump this on any scenario added/removed, or an existing scenario's
# expect_detection changed -- not on wording-only tweaks to a
# description. See core/driftbench/README.md for the full policy.
CORPUS_VERSION = "1.0"


@dataclass(frozen=True)
class Scenario:
    """One deterministic test case: a real call into a detector, and
    whether that detector is *expected* to flag it.

    `run` is a zero-arg callable (a closure over the scenario's own fixture
    data) returning True if the detector flagged the scenario, False if it
    didn't. Scenarios call real production functions directly -- this
    measures actual behavior, not a simulation of it.
    """
    id: str
    category: str
    description: str
    expect_detection: bool
    run: Callable[[], bool]


@dataclass(frozen=True)
class ScenarioResult:
    """Outcome of running one Scenario. `error` is set (and `detected`
    forced to False) if `run()` raised -- a broken scenario must not crash
    the whole suite or silently count as a pass."""
    scenario_id: str
    category: str
    expected: bool
    detected: bool
    duration_ms: float
    error: str | None = None

    @property
    def correct(self) -> bool:
        return self.error is None and self.detected == self.expected
