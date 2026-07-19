"""
Tropelex Epoch — Pure functions for epoch summary generation.

Epochs compress supersession chains (A supersedes B supersedes C) into
single-line summaries with archived originals.  Every function is pure:
same input -> same output, no I/O, no side effects.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from core.compaction import Err, Ok, Result
from core.decision_tree import DecisionTree
from core.knowledge_decay import score_decision


# --- Domain dataclasses ---

@dataclass(frozen=True)
class CompactionChain:
    """A supersession chain of 2+ decisions, ordered oldest -> newest."""
    members: list[dict[str, Any]]
    topic: str
    chain_id: str  # deterministic hash of member IDs


@dataclass(frozen=True)
class EpochSummary:
    """One-line summary of a compaction chain."""
    text: str
    topic: str
    count: int
    resolution: str
    date_range: tuple[str, str]  # (earliest, latest) timestamps
    key_decision_id: str


@dataclass(frozen=True)
class EpochRecord:
    """Archive record produced by merging a chain."""
    summary: EpochSummary
    archived_decision_ids: list[str]
    date_range: tuple[str, str]
    confidence_range: tuple[float, float]  # (min, max) scores
    epoch_id: str


# --- Keyword extraction (consistent with decision_tree._extract_keywords) ---

_STOPWORDS: set[str] = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "before", "after", "above", "below", "between", "and", "but", "or",
    "not", "so", "if", "then", "that", "this", "it", "its", "we", "our",
    "i", "my", "you", "your", "he", "she", "they", "them", "their",
    "added", "changed", "fixed", "refactored", "removed", "updated",
    "switched", "migrated", "replaced", "reverted", "optimised",
}


def _extract_keywords(text: str) -> set[str]:
    """Extract meaningful keywords from text, matching decision_tree.py."""
    words = re.findall(r"[a-z][a-z0-9+#_]{2,}", text.lower())
    return {w for w in words if w not in _STOPWORDS}


def _chain_id(members: list[dict[str, Any]]) -> str:
    """Deterministic ID from member hashes/IDs, oldest-first."""
    ids = [m.get("id", m.get("hash", "")) for m in members]
    return hashlib.sha256("|".join(ids).encode()).hexdigest()[:12]


def _determine_topic(members: list[dict[str, Any]]) -> str:
    """Extract the dominant topic keyword from a chain's decisions.

    Returns the most frequent meaningful keyword across all members,
    falling back to the first significant word of the resolving decision.
    """
    all_kw: dict[str, int] = {}
    for m in members:
        for kw in _extract_keywords(m.get("decision", "")):
            all_kw[kw] = all_kw.get(kw, 0) + 1
    if all_kw:
        return max(all_kw, key=lambda k: all_kw[k])  # most frequent keyword
    last_text = members[-1].get("decision", "")
    words = re.findall(r"[a-zA-Z]{3,}", last_text)
    return words[0].lower() if words else "unknown"


def _resolve_text(members: list[dict[str, Any]]) -> str:
    """Extract resolution text from the newest (last) decision, capped at 80 chars."""
    return members[-1].get("decision", "settled")[:80]


def _date_range(members: list[dict[str, Any]]) -> tuple[str, str]:
    """Return (earliest, latest) timestamps from chain members."""
    timestamps = sorted(m.get("timestamp", "") for m in members)
    return (timestamps[0], timestamps[-1])


def _chain_has_stale_members(
    members: list[dict[str, Any]],
    all_decisions: list[dict[str, Any]],
) -> bool:
    """Check if any chain member has stale/low confidence (tier < medium).

    Uses knowledge_decay.score_decision for each member independently.
    """
    for m in members:
        scored = score_decision(m, all_decisions)
        tier = scored.get("tier", "high")
        if tier in ("stale", "low"):
            return True
    return False


# --- Public API ---

def identify_compactable_chains(
    decisions: list[dict[str, Any]],
) -> list[CompactionChain]:
    """Group decisions into supersession chains eligible for compaction.

    Uses DecisionTree.from_decisions() to detect supersedes/reverts edges,
    then filters to chains with 2+ members where at least one member has
    stale confidence.  Empty input returns empty list (never an error).

    Args:
        decisions: Flat list of decision dicts with at least 'id' and 'decision' keys.

    Returns:
        List of CompactionChain instances, ordered by chain length descending.
    """
    if not decisions:
        return []

    tree = DecisionTree.from_decisions(decisions)
    raw_chains = tree.get_chains()

    chains: list[CompactionChain] = []
    for chain in raw_chains:
        if len(chain) < 2:
            continue
        # Only compact chains where at least one member is decaying
        if not _chain_has_stale_members(chain, decisions):
            continue
        topic = _determine_topic(chain)
        chains.append(CompactionChain(
            members=chain,
            topic=topic,
            chain_id=_chain_id(chain),
        ))
    # Sort longest chains first for most impact
    chains.sort(key=lambda c: len(c.members), reverse=True)
    return chains


def generate_epoch_summary(chain: CompactionChain) -> Result:
    """Create a one-line summary of a compaction chain.

    Format: "{topic} churned {N}x in {year}, settled on {resolution}, see decision #{id}"

    Returns:
        Ok(EpochSummary) on success, Err if chain members are empty.
    """
    members = chain.members
    if not members:
        return Err(
            error="Cannot summarize empty chain",
            code="VALIDATION_ERROR",
        )

    count = len(members)
    topic = chain.topic
    resolution = _resolve_text(members)
    dates = _date_range(members)
    year = dates[1][:4] if dates[1] else "unknown"
    key_id = members[-1].get("id", members[-1].get("hash", "unknown"))

    text = (
        f"{topic} churned {count}x in {year}, "
        f"settled on {resolution}, see decision #{key_id}"
    )

    return Ok(value=EpochSummary(
        text=text,
        topic=topic,
        count=count,
        resolution=resolution,
        date_range=dates,
        key_decision_id=key_id,
    ))


def _score_chain_confidence(
    member_ids: list[str],
    decisions: list[dict[str, Any]],
) -> tuple[float, float]:
    """Score confidence range (min, max) for chain members."""
    idx = {d.get("id", ""): d for d in decisions}
    scores = [
        score_decision(idx[mid], decisions).get("score", 0.0)
        for mid in member_ids
        if mid in idx
    ]
    return (
        round(min(scores), 3) if scores else 0.0,
        round(max(scores), 3) if scores else 1.0,
    )


def merge_chain_to_epoch(
    chain: CompactionChain,
    decisions: list[dict[str, Any]],
) -> Result:
    """Produce an epoch record from a chain, marking originals as archived.

    Never deletes originals — marks them with archived=True and an epoch_id.
    Scores confidence range via knowledge_decay.score_decision.
    Returns Ok(EpochRecord) or Err if inputs are invalid.
    """
    members = chain.members
    if not members:
        return Err(error="Cannot merge empty chain", code="VALIDATION_ERROR")
    if not decisions:
        return Err(
            error="Decisions list empty — cannot score confidence",
            code="VALIDATION_ERROR",
        )

    summary_result = generate_epoch_summary(chain)
    if isinstance(summary_result, Err):
        return summary_result

    member_ids = [m.get("id", "") for m in members]
    confidence = _score_chain_confidence(member_ids, decisions)
    epoch_id = f"epoch_{chain.chain_id}"

    return Ok(value=EpochRecord(
        summary=summary_result.value,
        archived_decision_ids=member_ids,
        date_range=summary_result.value.date_range,
        confidence_range=confidence,
        epoch_id=epoch_id,
    ))
