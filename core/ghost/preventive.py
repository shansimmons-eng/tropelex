"""
Preventive Ghost Checking — pure functions for pre-write diff analysis.

Checks a diff against active decisions *before* code is written, returning
structured warnings so callers can surface them as guardrails.

All functions are pure: no I/O, no side effects, same input → same output.
"""

from dataclasses import dataclass
from typing import Any

from core.ghost.pattern_matcher import (
    extract_keywords,
    match_decision_to_diff,
    parse_diff_hunks,
    score_ghost_severity,
)
from core.knowledge_decay import score_decision
from core.result import Err, Ok, Result  # noqa: F401 - re-exported for this module's consumers

# Severity tier thresholds (mirrors detector.py)
_SEVERITY_HIGH = 0.6
_SEVERITY_LOW = 0.3
_MIN_SEVERITY = 0.15


@dataclass(frozen=True)
class GhostWarning:
    """A single pre-write warning: a decision may be violated by the proposed diff."""
    decision_id: str
    decision_text: str
    severity: str  # "high" | "medium" | "low"
    severity_score: float
    matched_keywords: list[str]
    recommendation: str
    diff_file: str = ""
    diff_line: int = 0


def _classify_severity(score: float) -> str:
    """Classify a raw severity score into a tier label."""
    if score > _SEVERITY_HIGH:
        return "high"
    if score >= _SEVERITY_LOW:
        return "medium"
    return "low"


def _truncate(text: str, limit: int = 80) -> str:
    """Shorten text for inline display, without cutting mid-word where avoidable."""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


def _recommendation_for(
    severity: str, decision_text: str, diff_file: str, matched_keywords: list[str]
) -> str:
    """Generate a human-readable, diff-specific recommendation.

    Interpolates the actual matched decision/file/keywords rather than
    returning one of three fixed strings, so two different warnings in the
    same severity tier don't read as identical.
    """
    where = f" in `{diff_file}`" if diff_file else ""
    quoted_decision = f'"{_truncate(decision_text)}"'
    keyword_note = f" (matched: {', '.join(matched_keywords[:5])})" if matched_keywords else ""

    if severity == "high":
        return (
            f"This change{where} may contradict the decision {quoted_decision}"
            f"{keyword_note} — consider updating the decision or reverting this change."
        )
    if severity == "medium":
        return (
            f"This change{where} overlaps with the decision {quoted_decision}"
            f"{keyword_note} — review this drift, may be intentional."
        )
    return (
        f"Minor overlap{where} with the decision {quoted_decision}"
        f"{keyword_note} — monitor but no immediate action needed."
    )


def _build_scored_decisions(
    decisions: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Score every decision and index by id for O(1) lookup."""
    scored: dict[str, dict[str, Any]] = {}
    for d in decisions:
        did = d.get("id", "")
        scored[did] = score_decision(d, decisions)
    return scored


def _warn_single_decision(
    decision: dict[str, Any],
    scored_map: dict[str, dict[str, Any]],
    diff_hunks: list[dict[str, Any]],
) -> list[GhostWarning]:
    """Match one decision against all hunks, returning warnings above threshold."""
    did = decision.get("id", "")
    text = decision.get("decision", "")
    score_record = scored_map.get(did, {})
    confidence: float = score_record.get("score", 0.5)

    matches = match_decision_to_diff(text, diff_hunks)
    if not matches:
        return []

    warnings: list[GhostWarning] = []
    for m in matches:
        raw_severity = score_ghost_severity(m, confidence)
        if raw_severity < _MIN_SEVERITY:
            continue

        tier = _classify_severity(raw_severity)
        warnings.append(GhostWarning(
            decision_id=did,
            decision_text=text,
            severity=tier,
            severity_score=round(raw_severity, 4),
            matched_keywords=m.matched_keywords,
            recommendation=_recommendation_for(tier, text, m.diff_file, m.matched_keywords),
            diff_file=m.diff_file,
            diff_line=m.diff_line,
        ))
    return warnings


def _warning_to_dict(w: GhostWarning) -> dict[str, Any]:
    """Convert a GhostWarning dataclass to a plain dict for public API return."""
    return {
        "decision_id": w.decision_id,
        "decision_text": w.decision_text,
        "severity": w.severity,
        "severity_score": w.severity_score,
        "matched_keywords": w.matched_keywords,
        "recommendation": w.recommendation,
        "diff_file": w.diff_file,
        "diff_line": w.diff_line,
    }


def check_diff_for_warnings(
    memory: dict[str, Any],
    diff_text: str,
) -> Result[list[dict[str, Any]]]:
    """Check a proposed diff against all active decisions for ghost warnings.

    Pure function — no I/O, no side effects.  Designed as a pre-write hook:
    call this *before* applying a diff and surface the warnings to the user.

    Args:
        memory: Project memory dict containing a 'decisions' list.
        diff_text: Unified diff string to check.

    Returns:
        Ok(list[dict]) where each dict has: decision_id, decision_text,
        severity, severity_score, matched_keywords, recommendation,
        diff_file, diff_line.  List is empty when nothing matches.
        Err on unexpected internal failure.
    """
    if not diff_text:
        return Ok(value=[])

    decisions = memory.get("decisions", [])
    if not decisions:
        return Ok(value=[])

    try:
        hunks = parse_diff_hunks(diff_text)
        scored_map = _build_scored_decisions(decisions)

        all_warnings: list[GhostWarning] = []
        for decision in decisions:
            warnings = _warn_single_decision(decision, scored_map, hunks)
            all_warnings.extend(warnings)

        all_warnings.sort(key=lambda w: w.severity_score, reverse=True)
        return Ok(value=[_warning_to_dict(w) for w in all_warnings])

    except (TypeError, ValueError, AttributeError) as exc:
        # Malformed diff or decision data — degrade gracefully, no crash
        return Ok(value=[])
