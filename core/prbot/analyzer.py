"""
PR Diff Analyzer — pure-function module for analyzing PR diffs against
project decisions.

Reuses ghost detection modules for keyword matching and warning generation.
All functions are pure: no I/O, no side effects, same input → same output.
"""

from dataclasses import dataclass
from typing import Any

from core.ghost.pattern_matcher import extract_keywords
from core.ghost.preventive import check_diff_for_warnings
from core.knowledge_decay import score_decision
from core.prbot import Err, Ok, PRDecision, PRGhostWarning, Result


@dataclass(frozen=True)
class PRAnalysis:
    """Result of analyzing a PR diff against project decisions."""
    ghost_warnings: list[PRGhostWarning]
    relevant_decisions: list[PRDecision]
    relevance_score: float


def _to_ghost_warning(raw: dict[str, Any]) -> PRGhostWarning:
    """Convert a raw ghost warning dict to PRGhostWarning dataclass."""
    return PRGhostWarning(
        decision_id=raw.get("decision_id", ""),
        severity=raw.get("severity", "low"),
        matched_keywords=raw.get("matched_keywords", []),
        recommendation=raw.get("recommendation", ""),
    )


def _score_all_decisions(
    decisions: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Score every decision and index by id for O(1) lookup."""
    scored: dict[str, dict[str, Any]] = {}
    for d in decisions:
        did = d.get("id", "")
        scored[did] = score_decision(d, decisions)
    return scored


def _build_pr_decision(
    decision: dict[str, Any],
    all_decisions: list[dict[str, Any]],
    combined_keywords: set[str],
    scored_map: dict[str, dict[str, Any]],
) -> PRDecision | None:
    """Build a PRDecision if the decision has keyword overlap with the diff."""
    did = decision.get("id", "")
    text = decision.get("decision", "")
    dec_keywords = extract_keywords(text)
    if not dec_keywords:
        return None

    intersection = dec_keywords & combined_keywords
    union = dec_keywords | combined_keywords
    relevance = len(intersection) / len(union) if union else 0.0
    if relevance <= 0.0:
        return None

    confidence = scored_map.get(did, {}).get("score", 0.5)
    safety = decision.get("safety_metadata", {})
    return PRDecision(
        decision_id=did,
        decision_text=text[:120],
        confidence=round(confidence, 4),
        relevance_score=round(relevance, 4),
        impact_score=0.0,
        relationship="direct",
        risk_level=safety.get("risk_level", "low"),
        requires_review=safety.get("requires_review", False),
    )


def find_relevant_decisions(
    memory: dict[str, Any],
    diff_text: str,
    pr_title: str = "",
) -> list[PRDecision]:
    """Find decisions relevant to a PR diff via keyword overlap.

    Pure function — no I/O, no side effects.
    Extracts keywords from diff + title, matches against all decisions,
    and returns sorted by relevance_score descending.
    """
    decisions = memory.get("decisions", [])
    if not decisions or (not diff_text and not pr_title):
        return []

    combined = extract_keywords(diff_text) | extract_keywords(pr_title)
    if not combined:
        return []

    scored_map = _score_all_decisions(decisions)
    relevant = [
        pr_dec
        for d in decisions
        if (pr_dec := _build_pr_decision(d, decisions, combined, scored_map))
    ]
    relevant.sort(key=lambda d: d.relevance_score, reverse=True)
    return relevant


def compute_pr_relevance(
    ghost_warnings: list[PRGhostWarning],
    decisions: list[PRDecision],
) -> float:
    """Compute overall PR relevance score (0.0-1.0).

    Weighted combination: ghost severity (up to 0.5) + decision relevance (up to 0.5).
    """
    if not ghost_warnings and not decisions:
        return 0.0

    severity_weights = {"high": 1.0, "medium": 0.6, "low": 0.3}
    ghost_score = sum(
        severity_weights.get(w.severity, 0.3) for w in ghost_warnings
    ) / max(len(ghost_warnings), 1)
    ghost_contribution = min(ghost_score * 0.5, 0.5)

    avg_relevance = (
        sum(d.relevance_score for d in decisions) / len(decisions)
        if decisions
        else 0.0
    )
    decision_contribution = min(avg_relevance * 0.5, 0.5)

    return round(min(ghost_contribution + decision_contribution, 1.0), 4)


def analyze_pr_diff(
    memory: dict[str, Any],
    diff_text: str,
    pr_title: str = "",
    pr_body: str = "",
) -> Result:
    """Analyze a PR diff against project decisions.

    Pure function — no I/O, no side effects. Combines ghost detection
    with decision keyword matching to produce a PR analysis.

    Returns:
        Ok(PRAnalysis) with ghost_warnings, relevant_decisions, relevance_score.
        Err on validation failure or unexpected internal error.
    """
    if not diff_text and not pr_title:
        return Err(error="No diff or title provided", code="VALIDATION_ERROR")

    try:
        ghost_result = check_diff_for_warnings(memory, diff_text)
        ghost_warnings = (
            [_to_ghost_warning(w) for w in ghost_result.value]
            if hasattr(ghost_result, "value")
            else []
        )

        full_title = f"{pr_title} {pr_body}".strip()
        relevant_decisions = find_relevant_decisions(memory, diff_text, full_title)
        relevance_score = compute_pr_relevance(ghost_warnings, relevant_decisions)

        return Ok(value=PRAnalysis(
            ghost_warnings=ghost_warnings,
            relevant_decisions=relevant_decisions,
            relevance_score=relevance_score,
        ))
    except (TypeError, ValueError, AttributeError) as exc:
        return Err(
            error=f"Failed to analyze PR diff: {exc}",
            code="ANALYSIS_ERROR",
            details={"diff_length": len(diff_text)},
        )
