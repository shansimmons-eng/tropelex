"""
Memory Lens — pure annotation functions.

Maps code patterns to stored decisions using keyword overlap,
detects drift between code and documented decisions, and formats
annotations for display.  All functions are pure (no side effects).
"""

from __future__ import annotations

import re
from typing import Any

from core.lens import Annotation, Err, Ok, Result

# Stop words excluded from keyword matching
_STOP_WORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "and", "or", "not", "but", "if", "that", "this", "it", "as",
    "do", "does", "did", "will", "would", "could", "should",
    "have", "has", "had", "can", "may", "might", "use", "using",
    "used", "into", "about", "than", "then", "so",
})

# Signals that suggest code contradicts a positive decision
_NEGATION_SIGNALS = (
    "not ", "never ", "don't ", "do not ", "avoid ",
    "reject ", "remove ", "disable ", "forbid ",
)


def _tokenize(text: str) -> set[str]:
    """Extract meaningful tokens, filtering stop words and short words."""
    words = re.findall(r"[a-zA-Z_]\w*", text.lower())
    return {w for w in words if w not in _STOP_WORDS and len(w) > 2}


def detect_drift(code_text: str, decision: dict[str, Any]) -> bool:
    """Check if code contradicts a decision.

    Returns True when code contains negation signals AND shares
    keywords with the decision text.  Pure predicate, no side effects.
    """
    if not code_text or not decision:
        return False
    code_lower = code_text.lower()
    has_negation = any(signal in code_lower for signal in _NEGATION_SIGNALS)
    if not has_negation:
        return False
    shared = _tokenize(decision.get("decision", "")) & _tokenize(code_text)
    return len(shared) > 0


def map_code_to_decisions(
    code_text: str,
    decisions: list[dict[str, Any]],
) -> Result[list[Annotation]]:
    """Match a code snippet to decisions using keyword overlap.

    Returns Ok(annotations) sorted by confidence descending,
    or Err with VALIDATION_ERROR for bad inputs.
    """
    if not isinstance(code_text, str):
        return Err(error="code_text must be a string", code="VALIDATION_ERROR")
    if not isinstance(decisions, list):
        return Err(error="decisions must be a list", code="VALIDATION_ERROR")

    code_tokens = _tokenize(code_text)
    if not code_tokens:
        return Ok(value=[])

    annotations: list[Annotation] = []
    for idx, decision in enumerate(decisions):
        dec_text = decision.get("decision", "")
        dec_tokens = _tokenize(dec_text)
        if not dec_tokens:
            continue
        overlap = code_tokens & dec_tokens
        if not overlap:
            continue
        confidence = len(overlap) / max(len(code_tokens), len(dec_tokens))
        rel = "drifted" if detect_drift(code_text, decision) else "referenced"
        annotations.append(Annotation(
            decision_id=decision.get("id", f"decision-{idx}"),
            decision_text=dec_text,
            confidence=round(min(confidence, 1.0), 3),
            line_number=0,
            file_path="",
            relationship=rel,
            reference_count=len(overlap),
        ))

    annotations.sort(key=lambda a: a.confidence, reverse=True)
    return Ok(value=annotations)


def format_annotation(annotation: Annotation) -> str:
    """Format an annotation for human-readable display.

    Pure function — returns a decorated string like:
        🔗 [REFERENCED] Use FastAPI for API layer (confidence: 45%, refs: 3)
    """
    icons = {"defined": "📝", "referenced": "🔗", "drifted": "⚠️"}
    icon = icons.get(annotation.relationship, "❓")
    text = annotation.decision_text[:60]
    if len(annotation.decision_text) > 60:
        text += "…"
    return (
        f"{icon} [{annotation.relationship.upper()}] "
        f"{text} "
        f"(confidence: {annotation.confidence:.0%}, refs: {annotation.reference_count})"
    )


def scan_file_for_decisions(
    file_content: str,
    decisions: list[dict[str, Any]],
) -> Result[list[Annotation]]:
    """Scan entire file content for decision references.

    Processes each line individually and collects all matches.
    Returns Ok(annotations) or Err for invalid inputs.
    """
    if not isinstance(file_content, str):
        return Err(error="file_content must be a string", code="VALIDATION_ERROR")
    if not isinstance(decisions, list):
        return Err(error="decisions must be a list", code="VALIDATION_ERROR")

    all_annotations: list[Annotation] = []
    for line_num, line in enumerate(file_content.splitlines(), start=1):
        result = map_code_to_decisions(line, decisions)
        if isinstance(result, Err):
            return result
        for ann in result.value:
            all_annotations.append(Annotation(
                decision_id=ann.decision_id,
                decision_text=ann.decision_text,
                confidence=ann.confidence,
                line_number=line_num,
                file_path="",
                relationship=ann.relationship,
                reference_count=ann.reference_count,
            ))

    return Ok(value=all_annotations)
