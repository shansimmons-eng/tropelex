"""
Pure scoring functions for corroboration status.

Maps research findings against decision rationale to determine
whether a decision is still supported, outdated, contradicted,
or unverifiable. All functions are pure — no IO, no side effects.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

# --- Domain types ---


@dataclass(frozen=True)
class ResearchFinding:
    """A single research result returned from web lookups."""

    title: str
    url: str
    description: str
    relevance_score: float = 0.0
    published_date: str | None = None


@dataclass(frozen=True)
class CorroborationResult:
    """Outcome of comparing research findings against a decision rationale."""

    status: Literal["supported", "outdated", "contradicted", "unverifiable"]
    confidence_adjustment: float
    evidence_urls: list[str] = field(default_factory=list)
    reasoning: str = ""


# --- Constants ---

_CONTRADICTION_KEYWORDS: list[str] = [
    "deprecated",
    "no longer",
    "replaced by",
    "instead use",
    "not recommended",
    "end of life",
    "sunset",
]

_OUTDATED_KEYWORDS: list[str] = [
    "legacy",
    "old version",
    "previous version",
    "was used",
    "formerly",
]

_OUTDATED_AGE_DAYS: int = 730  # ~2 years


# --- Pure helper functions ---

_STOP_WORDS: set[str] = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "have",
    "has", "had", "do", "does", "did", "will", "would", "could", "should",
    "may", "might", "can", "to", "of", "in", "for", "on", "with", "at",
    "by", "from", "as", "and", "but", "or", "not", "so", "if", "then",
    "that", "this", "it", "its", "we", "our", "i", "my", "you", "your",
}


def _extract_words(text: str) -> set[str]:
    """Lowercase alphanumeric tokens minus stop words."""
    return {w.lower() for w in re.findall(r"[a-zA-Z][a-zA-Z0-9]+", text)} - _STOP_WORDS


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- Public API ---


def compute_relevance(rationale: str, finding: ResearchFinding) -> float:
    """Keyword overlap between rationale and finding description (0.0–1.0)."""
    rationale_words = _extract_words(rationale)
    if not rationale_words:
        return 0.0
    finding_words = _extract_words(finding.description + " " + finding.title)
    overlap = rationale_words & finding_words
    return len(overlap) / len(rationale_words)


def detect_contradiction_signals(
    rationale: str,
    findings: list[ResearchFinding],
) -> list[str]:
    """Return evidence sentences containing contradiction keywords."""
    signals: list[str] = []
    rationale_words = _extract_words(rationale)
    for f in findings:
        if not (rationale_words & _extract_words(f.description)):
            continue  # skip irrelevant findings
        lower = f.description.lower()
        for kw in _CONTRADICTION_KEYWORDS:
            if kw in lower:
                signals.append(f.description)
                break
    return signals


def _parse_date(date_str: str | None) -> datetime | None:
    """Best-effort ISO date parse."""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def detect_outdated_signals(findings: list[ResearchFinding]) -> list[str]:
    """Return evidence sentences suggesting outdated information."""
    signals: list[str] = []
    now = _now()
    for f in findings:
        dt = _parse_date(f.published_date)
        if dt and (now - dt).days > _OUTDATED_AGE_DAYS:
            signals.append(f.description)
            continue
        lower = f.description.lower()
        for kw in _OUTDATED_KEYWORDS:
            if kw in lower:
                signals.append(f.description)
                break
    return signals


def score_corroboration(
    rationale: str,
    findings: list[ResearchFinding],
) -> CorroborationResult:
    """Analyze research findings against the decision rationale.

    Pure function — same inputs always produce the same output.
    """
    if not findings:
        return CorroborationResult(
            status="unverifiable",
            confidence_adjustment=0.0,
            reasoning="No research findings provided",
        )

    # Score each finding for relevance to rationale
    scored = [(f, compute_relevance(rationale, f)) for f in findings]

    high = [f for f, s in scored if s >= 0.5]
    low = [f for f, s in scored if s >= 0.3]
    evidence_urls = [f.url for f in high if f.url]

    # No relevant findings at all
    if not low:
        return CorroborationResult(
            status="unverifiable",
            confidence_adjustment=0.0,
            evidence_urls=evidence_urls,
            reasoning="Findings have low relevance (<0.3) to rationale",
        )

    contradictions = detect_contradiction_signals(rationale, findings)
    outdated = detect_outdated_signals(findings)

    # Contradiction takes priority
    if contradictions and len(contradictions) >= 2:
        return CorroborationResult(
            status="contradicted",
            confidence_adjustment=-0.3,
            evidence_urls=evidence_urls,
            reasoning=f"{len(contradictions)} contradiction signals found",
        )

    # Outdated detection
    if outdated:
        return CorroborationResult(
            status="outdated",
            confidence_adjustment=-0.15,
            evidence_urls=evidence_urls,
            reasoning=f"{len(outdated)} outdated signals found",
        )

    # High-relevance findings present → supported
    if high:
        return CorroborationResult(
            status="supported",
            confidence_adjustment=0.1,
            evidence_urls=evidence_urls,
            reasoning=f"{len(high)} high-relevance findings support rationale",
        )

    # Only low-relevance findings
    return CorroborationResult(
        status="unverifiable",
        confidence_adjustment=0.0,
        evidence_urls=evidence_urls,
        reasoning="No high-relevance findings (≥0.5) to confirm rationale",
    )
