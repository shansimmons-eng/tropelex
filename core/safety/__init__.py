"""
Safety surface index (#103) — the single importable place that lists every
safety-relevant pure function/class in this codebase, with a pointer to
where each one actually lives.

This is a re-export, not a relocation. #103 was prompted by a real
reviewability gap (SFF's "Evaluation & Limitations" section, this pass):
an external auditor trying to review "the safety surface" as a bounded
unit couldn't, because the logic is genuinely spread across core/ghost/,
core/contradictions/, core/handoff/, core/session_shape/, core/driftbench/,
core/market/, and core/safety_budget.py -- each module correctly living
next to the feature area it's part of (Ghost checks diffs, Handoff builds
packets, Market tracks calibration), not misplaced. Physically moving all
of that under core/safety/ would mean rewriting imports across every
router, the MCP server, and ~15 test files for a purely cosmetic
reorganization -- real risk (a missed import breaks a live gate) for a
grant-credibility goal that a re-export index satisfies just as well:
`import core.safety; core.safety.__all__` gives an auditor the complete,
bounded list in one place, and every symbol's own module still carries
its real docstring and tests, unmoved and unbroken.

Wishlist #73's fast-follow (below) already established this module and
its own file, and made the same "extraction, not endpoint-relocation"
call for the same reason -- #103 extends that precedent rather than
reversing it.

Wishlist #73's original note: SafetyMetadata and the auto-classifier
(classifier.py) have now moved out of server.py's inline block. DecisionCreate
and the safety-report endpoints downstream of them (get_safety_stats,
get_safety_dashboard, get_safety_trend, submit_safety_review, run_safety_check,
get_safety_envelope, and their private helpers — a genuinely larger surface
than the original "~150-line block" estimate suggested, confirmed by grep
before touching anything) are still in server.py, deliberately deferred
again rather than folded into this pass — moving a dozen interdependent
endpoints in the same change as the classifier extraction would be exactly
the wide, hard-to-review change this project avoids. Real fast-follow, not
a blocker, same as last time. #103 leaves this deferral exactly where #73
left it, for the same reason: these are FastAPI endpoints wired into
server.py's routing, not standalone symbols a re-export can meaningfully
front.

A confusable-names note, since it bit the author of this docstring while
writing it: `core.gate` (module-level, `core/gate.py`) is the generalized
severity->action policy gate (#72/#101). `core.safety.gate` (this
package's own `gate.py`) is a different, unrelated thing -- the
required-safety-metadata check (#54). Both are re-exported below, under
names that don't collide, but the module *paths* are easy to mix up.
"""

from core.contradictions import Contradiction, ContradictionReport
from core.contradictions.detector import classify_contradiction, detect_contradictions
from core.driftbench import CATEGORIES as DRIFT_BENCH_CATEGORIES
from core.driftbench import Scenario, ScenarioResult
from core.driftbench.report import run_suite as run_drift_bench_suite
from core.driftbench.scenarios import build_corpus as build_drift_bench_corpus
from core.gate import (
    DEFAULT_GATE_POLICY,
    GATE_ACTIONS,
    GATE_SEVERITIES,
    overridden_ids,
    policy_for,
)
from core.ghost.detector import GhostDecision, GhostReport, detect_ghost_decisions
from core.ghost.preventive import GhostWarning, check_diff_for_warnings
from core.handoff.packet_builder import (
    HandoffCompletenessFinding,
    HandoffPacket,
    build_handoff_packet,
)
from core.market.coordination import score_coordination_drift
from core.safety.classifier import SafetyMetadata, auto_classify_safety
from core.safety.gate import SafetyMetadataRequiredError, require_safety_metadata
from core.safety_budget import compute_safety_budget
from core.session_shape.baseline import classify_deviation, compute_baseline, record_session_shape

#112: a plain, checkable version tag for the frozen surface below --
# deliberately not part of __all__ itself (that list is specifically
# "every pure function/class backing a safety mechanism"; a version
# string is a different kind of thing), but still directly importable
# rather than only asserted in SAFETY.md's prose. Bump this if __all__'s
# membership changes in a way that changes what "the safety surface"
# means, not on docstring or comment edits.
SAFETY_SURFACE_VERSION = "v1"

__all__ = [
    # Safety metadata & required-metadata gate (#54, core/safety/)
    "SafetyMetadata", "SafetyMetadataRequiredError",
    "auto_classify_safety", "require_safety_metadata",
    # Generalized severity->action policy gate (#72/#101, core/gate.py)
    "policy_for", "overridden_ids",
    "DEFAULT_GATE_POLICY", "GATE_ACTIONS", "GATE_SEVERITIES",
    # Silent objective-drift detection (core/ghost/)
    "detect_ghost_decisions", "GhostDecision", "GhostReport",
    "check_diff_for_warnings", "GhostWarning",
    # Conflicting-objective surfacing (core/contradictions/)
    "detect_contradictions", "classify_contradiction",
    "Contradiction", "ContradictionReport",
    # Inter-agent handoff protection (core/handoff/)
    "build_handoff_packet", "HandoffPacket", "HandoffCompletenessFinding",
    # Behavioral anomaly baselining (core/session_shape/)
    "compute_baseline", "classify_deviation", "record_session_shape",
    # Cross-agent coordination-drift detection (core/market/)
    "score_coordination_drift",
    # Per-agent cumulative-risk escalation (core/safety_budget.py)
    "compute_safety_budget",
    # Synthetic ground-truth evaluation harness (core/driftbench/)
    "build_drift_bench_corpus", "run_drift_bench_suite",
    "Scenario", "ScenarioResult", "DRIFT_BENCH_CATEGORIES",
]
