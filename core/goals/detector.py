"""
Goal-shaped language detection — pure function, no I/O.

The prospective sibling of core/learner/learner.py's PatternLearner.
detect_decisions(): same technique (regex over free text, no NLP), applied
to goal-shaped phrasings ("wants", "requested", "needs", "would like",
"trying to achieve") instead of decision-shaped ones ("decided", "will
use", "opted for").

This is regex/keyword matching only — no negation handling, no semantic
understanding. "The user doesn't want X" still matches "want X" and will
surface as a false-positive candidate; that's a known limitation shared
with detect_decisions, not something fixed here. No dedup across patterns:
if two patterns both match overlapping text, both entries can appear.
Pattern order is priority — when text produces more matches than the cap,
earlier patterns in the list win the available slots.

A second pattern set, _STRUCTURED_FIELD_PATTERNS, covers structured
spec-doc prose (e.g. this project's own wishlist.md entries: "**Purpose:**
Add X to Y") that the narrative patterns above never fire on — "Add 2-3
scenarios to Drift-Bench" contains no "wants"/"needs"/"the goal is"
trigger phrase even though a **Purpose:** label makes it unambiguously a
stated goal. Same regex/keyword approach, just matching on markdown
structure instead of sentence phrasing.

Deliberately not added to core/learner/ — Goals must not gain a dependency
on Learner, and detect_decisions has already shown what happens when a
detector like this ships with no UI consumer: it's fully built, tested,
and reachable via POST /api/analyze/decisions, but nothing in the
dashboard ever calls it. detect_goals ships with its UI consumer in the
same pass (see the Goals tab's "Scan for goal candidates" panel).
"""

from __future__ import annotations

import re

_GOAL_PATTERNS: list[tuple[str, str]] = [
    (r"(?:the\s+)?goal\s+is\s+(?:to\s+)?(.+?)(?:\.|$)", "explicit_goal"),
    (r"(?:user\s+)?requested\s+(?:that\s+)?(.+?)(?:\.|$)", "request"),
    (r"(?:user\s+)?wants?\s+(?:to\s+)?(.+?)(?:\.|$)", "want"),
    (r"needs?\s+to\s+(.+?)(?:\.|$)", "need"),
    (r"would\s+like\s+(?:to\s+)?(.+?)(?:\.|$)", "preference"),
    (r"trying\s+to\s+achieve\s+(.+?)(?:\.|$)", "aim"),
    (r"aiming\s+(?:to|for)\s+(.+?)(?:\.|$)", "aim"),
]

# Markdown field labels that state an explicit purpose/goal directly, as
# opposed to a narrative sentence. DOTALL lets `.` span a field's wrapped
# lines; the lookahead stops the capture at the next "**Label:**" field,
# a blank line, or end of string, rather than consuming the rest of the
# document.
_STRUCTURED_FIELD_PATTERNS: list[tuple[str, str]] = [
    (r"\*\*(?:Purpose|Goal):\*\*\s*(.+?)(?=\n\s*\*\*\w[\w /-]*:\*\*|\n\s*\n|\Z)", "structured_purpose"),
]

# Same two-tier scheme as detect_decisions: explicit/direct phrasings are
# "high", softer ones are "medium" — never "low", no numeric score.
_HIGH_CONFIDENCE_TYPES = {"explicit_goal", "request", "structured_purpose"}


def detect_goals(text: str) -> list[dict[str, str]]:
    """Scan text for goal-shaped phrasings, return up to 5 candidates.

    Returns {"type", "content", "confidence"} dicts — same shape as
    detect_decisions(). Content must be 10-500 chars; the cap is applied
    across all patterns combined, not per pattern, so pattern order above
    determines which candidates survive when a text has more than 5 hits.
    Narrative patterns run before structured-field patterns, so a text
    with both kinds fills its 5 slots from narrative matches first.
    """
    detected: list[dict[str, str]] = []
    for pattern, goal_type in _GOAL_PATTERNS:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            content = " ".join(match) if isinstance(match, tuple) else match
            content = re.sub(r"\s+", " ", content).strip()
            if 10 < len(content) < 500:
                detected.append({
                    "type": goal_type,
                    "content": content,
                    "confidence": "high" if goal_type in _HIGH_CONFIDENCE_TYPES else "medium",
                })

    for pattern, goal_type in _STRUCTURED_FIELD_PATTERNS:
        matches = re.findall(pattern, text, re.IGNORECASE | re.DOTALL)
        for match in matches:
            content = " ".join(match) if isinstance(match, tuple) else match
            content = re.sub(r"\s+", " ", content).strip()
            if 10 < len(content) < 500:
                detected.append({
                    "type": goal_type,
                    "content": content,
                    "confidence": "high" if goal_type in _HIGH_CONFIDENCE_TYPES else "medium",
                })

    return detected[:5]
