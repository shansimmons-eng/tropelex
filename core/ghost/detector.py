"""
Ghost Detector — orchestrates pattern matcher, decision tree, and knowledge
decay to produce a drift report showing where code contradicts documented
decisions.

Pure functions only — no I/O, no network, no file access.
"""

from dataclasses import dataclass
from typing import Any

from core.ghost.pattern_matcher import (
    MatchResult,
    extract_keywords,
    match_decision_to_diff,
    parse_diff_hunks,
    score_ghost_severity,
    extract_decision_topics,
)
from core.decision_tree import DecisionTree
from core.knowledge_decay import score_decision


# --- Severity tier thresholds ---
_SEVERITY_HIGH = 0.6
_SEVERITY_LOW = 0.3
# Minimum severity to include in the report
_MIN_SEVERITY = 0.15


@dataclass(frozen=True)
class GhostDecision:
    """A single ghost decision — code contradicts a documented decision."""
    decision_id: str
    decision_text: str
    severity: float
    evidence: list[MatchResult]
    confidence_score: float
    confidence_tier: str
    recommendation: str


@dataclass(frozen=True)
class GhostReport:
    """Full report of detected ghost decisions."""
    ghosts: list[GhostDecision]
    total_decisions_checked: int
    total_diffs_checked: int
    total_ghosts: int
    severity_distribution: dict[str, int]  # {"high": N, "medium": N, "low": N}
    recommendations: list[str]


def _classify_severity(severity: float) -> str:
    """Classify severity into tier: high (>0.6), medium (0.3-0.6), low (<0.3)."""
    if severity > _SEVERITY_HIGH:
        return "high"
    if severity >= _SEVERITY_LOW:
        return "medium"
    return "low"


def _generate_ghost_recommendation(severity: float) -> str:
    """Generate a recommendation for a ghost decision by severity."""
    tier = _classify_severity(severity)
    if tier == "high":
        return "Consider updating decision or reverting code change"
    if tier == "medium":
        return "Review this drift — may be intentional"
    return "Minor drift — monitor but no immediate action needed"


def _aggregate_severity_distribution(ghosts: list[GhostDecision]) -> dict[str, int]:
    """Count ghosts by severity tier."""
    dist: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
    for g in ghosts:
        tier = _classify_severity(g.severity)
        dist[tier] += 1
    return dist


def _generate_report_recommendations(ghosts: list[GhostDecision]) -> list[str]:
    """Generate top-level recommendations from all ghosts."""
    if not ghosts:
        return []

    dist = _aggregate_severity_distribution(ghosts)
    recs: list[str] = []

    if dist["high"] > 0:
        recs.append(
            f"{dist['high']} high-severity ghost decisions detected — review immediately"
        )
    if dist["medium"] > 0:
        recs.append(
            f"{dist['medium']} medium-severity drifts detected — review when convenient"
        )
    if dist["low"] > 0:
        recs.append(
            f"{dist['low']} minor drifts detected — monitor for patterns"
        )

    return recs


def _build_scored_lookup(
    decisions: list[dict],
) -> dict[str, dict[str, Any]]:
    """Score decisions with knowledge_decay and index by id.

    Uses score_decision individually to preserve ID correspondence
    (score_decisions sorts by score, breaking index alignment).

    Returns a dict mapping decision ID → score record.
    """
    scored_map: dict[str, dict[str, Any]] = {}
    for d in decisions:
        did = d.get("id", "")
        scored_map[did] = score_decision(d, decisions)
    return scored_map


def _match_single_decision(
    decision: dict,
    scored_map: dict[str, dict[str, Any]],
    all_hunks: list[dict[str, Any]],
) -> list[GhostDecision]:
    """Match one decision against all diff hunks, returning at most ONE ghost per decision.

    All matching hunks are collected as evidence on a single GhostDecision,
    with severity equal to the worst (highest) individual match. Previously
    this returned one ghost per hunk, causing the same decision to appear
    dozens of times in the report.
    """
    did = decision.get("id", "")
    decision_text = decision.get("decision", "")
    score_record = scored_map.get(did, {})
    confidence = score_record.get("score", 0.5)
    tier = score_record.get("tier", "medium")

    matches = match_decision_to_diff(decision_text, all_hunks)
    if not matches:
        return []

    # Filter below-minimum matches, then aggregate into one ghost
    valid = [(m, score_ghost_severity(m, confidence)) for m in matches]
    valid = [(m, s) for m, s in valid if s >= _MIN_SEVERITY]
    if not valid:
        return []

    worst_severity = max(s for _, s in valid)
    evidence = [m for m, _ in valid]

    return [GhostDecision(
        decision_id=did,
        decision_text=decision_text,
        severity=worst_severity,
        evidence=evidence,
        confidence_score=confidence,
        confidence_tier=tier,
        recommendation=_generate_ghost_recommendation(worst_severity),
    )]


def detect_ghost_decisions(
    memory: dict,
    diff_data: list[dict[str, str]],
    tree: DecisionTree | None = None,
) -> GhostReport:
    """Main entry point. Detect ghost decisions by comparing memory against diffs.

    Args:
        memory: Project memory dict with 'decisions' list
        diff_data: List of {file, diff_text} dicts (from git diffs)
        tree: Optional pre-built DecisionTree (built from memory if None)

    Returns:
        GhostReport with all detected ghosts and summary statistics.
    """
    decisions = memory.get("decisions", [])

    if not decisions or not diff_data:
        return GhostReport(
            ghosts=[],
            total_decisions_checked=len(decisions),
            total_diffs_checked=len(diff_data),
            total_ghosts=0,
            severity_distribution={"high": 0, "medium": 0, "low": 0},
            recommendations=[],
        )

    # Step 1: Score all decisions with knowledge_decay
    scored_map = _build_scored_lookup(decisions)

    # Step 2: Build decision tree if not provided (not used in matching,
    # but validates the decision graph is well-formed)
    if tree is None:
        tree = DecisionTree.from_decisions(decisions)

    # Step 3-5: For each diff, parse hunks; for each decision, match against hunks
    all_hunks = _parse_all_diffs(diff_data)

    all_ghosts: list[GhostDecision] = []
    for decision in decisions:
        ghosts = _match_single_decision(decision, scored_map, all_hunks)
        all_ghosts.extend(ghosts)

    # Step 6-9: Build report
    all_ghosts.sort(key=lambda g: g.severity, reverse=True)

    return GhostReport(
        ghosts=all_ghosts,
        total_decisions_checked=len(decisions),
        total_diffs_checked=len(diff_data),
        total_ghosts=len(all_ghosts),
        severity_distribution=_aggregate_severity_distribution(all_ghosts),
        recommendations=_generate_report_recommendations(all_ghosts),
    )


def _parse_all_diffs(diff_data: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Parse all diffs into a flat list of hunks with file labels."""
    hunks: list[dict[str, Any]] = []
    for entry in diff_data:
        file_name = entry.get("file", "")
        raw_hunks = parse_diff_hunks(entry.get("diff_text", ""))
        for h in raw_hunks:
            # Ensure file name is populated from the diff_data entry
            enriched = {**h, "file": h.get("file") or file_name}
            hunks.append(enriched)
    return hunks
