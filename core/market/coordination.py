"""
Coordination Drift Detection (wishlist #43) — pure functions.

Decision Market (#14) already tracks each agent's calibration
independently (accuracy, overconfidence_index via compute_calibration).
Nothing asks whether multiple agents working the same project are
converging or diverging from each other over time — a distinct signal
from individual calibration, and one the agent-drift literature treats
as its own category ("Coordination Drift," tracked via cumulative
agreement rates).

Agreement is defined over calibration *profiles*, not shared bets on the
same decision -- multiple agents rarely bet on the identical decision_id
in practice (confirmed against the real tropelex project: 0 of 6 bets
share a decision_id across agents), so a same-decision-only definition
would have no signal to work with almost always. Comparing accuracy and
overconfidence_index between agents' resolved-bet histories works
whenever two agents each have enough resolved bets of their own,
regardless of decision overlap -- the same reasoning Decision Market's
own leaderboard already uses to compare agents without requiring shared
decisions.

Same baseline-vs-recent trend shape as core/goals/drift.py's
score_trend_drift, for consistency with this project's other drift
signals -- and the same "insufficient_data" honesty as Session-Shape
Baselining (core/session_shape/baseline.py) when there isn't enough
history to say anything real yet, rather than a degenerate score from
too little data.

Pure functions only -- no I/O.
"""

from __future__ import annotations

from typing import Any

from core.market import CalibrationScore, Ok
from core.market.calibration import compute_calibration

# Minimum resolved bets an agent needs, in EACH of the baseline/recent
# windows, before a pairwise comparison is trusted at all. Below this,
# compute_calibration itself would still run, but the resulting accuracy
# would be too noisy (e.g. 1/1 correct = 100% accuracy) to mean anything.
MIN_BETS_PER_WINDOW = 3

# A pairwise agreement decline at or beyond this magnitude counts as
# coordination drift for that pair. Agreement is bounded [0, 1]; 0.25 is
# a deliberately conservative bar -- same "don't flag on noise" instinct
# as score_trend_drift's own thresholds, picked without real usage data
# to calibrate against yet (see wishlist.md #43's own "not urgent, no
# current pain point" framing), so erring conservative over sensitive.
DRIFT_THRESHOLD = 0.25


def compute_agreement(score_a: CalibrationScore, score_b: CalibrationScore) -> float:
    """Pairwise agreement between two agents' calibration profiles, in
    [0, 1] -- 1.0 means identical accuracy and overconfidence_index, 0.0
    means maximally divergent on both.

    Deliberately symmetric in accuracy and overconfidence: an agent that
    matches another's accuracy but is wildly more overconfident isn't
    "agreeing" with it in the sense this feature cares about (behavioral
    convergence), even though their raw hit rates line up.
    """
    accuracy_diff = abs(score_a.accuracy - score_b.accuracy)
    # overconfidence_index each range roughly [-1, 1] (avg_incorrect_conf -
    # avg_correct_conf), so their difference ranges up to 2 -- normalize
    # to the same [0, 1] scale as accuracy_diff before combining.
    overconfidence_diff = abs(score_a.overconfidence_index - score_b.overconfidence_index) / 2.0
    combined_diff = min(1.0, (accuracy_diff + overconfidence_diff) / 2.0)
    return round(1.0 - combined_diff, 3)


def _split_windows(bets: list[dict], window: int) -> tuple[list[dict], list[dict]] | None:
    """An agent's own resolved bets, oldest-first, split into
    (baseline, recent) -- mirrors score_trend_drift's slicing exactly.
    Returns None if there isn't MIN_BETS_PER_WINDOW in each half.
    """
    if len(bets) < window * 2:
        return None
    baseline = bets[: len(bets) - window]
    recent = bets[-window:]
    if len(baseline) < MIN_BETS_PER_WINDOW or len(recent) < MIN_BETS_PER_WINDOW:
        return None
    return baseline, recent


def _calibration_for(bets: list[dict], agent: str) -> CalibrationScore | None:
    result = compute_calibration(bets, agent)
    return result.value if isinstance(result, Ok) else None


def score_coordination_drift(bets: list[dict[str, Any]], window: int = 5) -> dict[str, Any]:
    """Baseline-vs-recent pairwise agreement across every pair of agents
    with enough resolved bet history. Each agent's own bets are split
    into an older baseline window and a recent window (chronological
    order assumed, matching how bets are appended); agreement is scored
    within each window per pair, and a pair whose agreement dropped by
    DRIFT_THRESHOLD or more from baseline to recent is flagged.

    Returns insufficient_data honestly when fewer than two agents have
    enough resolved bets to compare -- not a degenerate 0/1 score.
    """
    if not isinstance(bets, list):
        bets = []
    resolved = [b for b in bets if isinstance(b, dict) and b.get("resolved")]

    by_agent: dict[str, list[dict]] = {}
    for b in resolved:
        agent = b.get("agent_name")
        if agent:
            by_agent.setdefault(agent, []).append(b)

    windows: dict[str, tuple[list[dict], list[dict]]] = {}
    for agent, agent_bets in by_agent.items():
        split = _split_windows(agent_bets, window)
        if split is not None:
            windows[agent] = split

    eligible_agents = sorted(windows.keys())
    if len(eligible_agents) < 2:
        return {
            "drift_detected": False,
            "message": (
                "Not enough agents with sufficient resolved bet history "
                f"(need >= 2 agents with >= {window * 2} resolved bets each, "
                f">= {MIN_BETS_PER_WINDOW} in both the baseline and recent window)"
            ),
            "eligible_agents": eligible_agents,
            "pairs": [],
        }

    pairs: list[dict[str, Any]] = []
    for i, agent_a in enumerate(eligible_agents):
        for agent_b in eligible_agents[i + 1:]:
            baseline_a, recent_a = windows[agent_a]
            baseline_b, recent_b = windows[agent_b]

            cal_baseline_a = _calibration_for(baseline_a, agent_a)
            cal_baseline_b = _calibration_for(baseline_b, agent_b)
            cal_recent_a = _calibration_for(recent_a, agent_a)
            cal_recent_b = _calibration_for(recent_b, agent_b)
            if not all((cal_baseline_a, cal_baseline_b, cal_recent_a, cal_recent_b)):
                continue

            baseline_agreement = compute_agreement(cal_baseline_a, cal_baseline_b)
            recent_agreement = compute_agreement(cal_recent_a, cal_recent_b)
            drift = round(recent_agreement - baseline_agreement, 3)

            pairs.append({
                "agent_a": agent_a,
                "agent_b": agent_b,
                "baseline_agreement": baseline_agreement,
                "recent_agreement": recent_agreement,
                "drift": drift,
                "drift_detected": drift <= -DRIFT_THRESHOLD,
            })

    return {
        "drift_detected": any(p["drift_detected"] for p in pairs),
        "eligible_agents": eligible_agents,
        "pairs": pairs,
    }
