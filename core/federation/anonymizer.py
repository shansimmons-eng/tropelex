"""Federation anonymizer — pure functions that strip text, keep structural stats.

All functions are deterministic, side-effect-free, and return Result types.
"""
from __future__ import annotations

import hashlib
from collections import Counter

from . import AnonymizedStats, Err, Ok, Result


def hash_project_name(name: str) -> str:
    """Deterministic SHA-256 hash for anonymizing project names."""
    return hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]


_RISK_WEIGHTS = {"low": 0.0, "medium": 0.25, "high": 0.75, "critical": 1.0}


def _safety_posture(decisions: list) -> tuple[float, dict[str, int]]:
    """Aggregate safety_metadata across decisions into (avg_safety_score,
    risk_level_distribution). Mirrors the weighting in the Safety Dashboard's
    own score so federated benchmarks are comparable to what a project sees
    locally, without importing server.py (would be circular).
    """
    if not decisions:
        return 1.0, {}
    risk_dist: dict[str, int] = {}
    weighted_sum = 0.0
    for d in decisions:
        risk_level = d.get("safety_metadata", {}).get("risk_level", "low")
        risk_dist[risk_level] = risk_dist.get(risk_level, 0) + 1
        weighted_sum += _RISK_WEIGHTS.get(risk_level, 0.0)
    avg_safety_score = round(max(0.0, 1.0 - weighted_sum / len(decisions)), 4)
    return avg_safety_score, risk_dist


def extract_structural_stats(memory: dict) -> dict:
    """Extract purely structural statistics from a project memory dict.

    Returns dict with: decision_count, reversal_rate, avg_confidence,
    category_distribution, tech_stack, avg_safety_score, risk_level_distribution.
    """
    decisions = memory.get("decisions", [])
    tech_stack = memory.get("tech_stack", [])
    total = len(decisions)

    # Category distribution from patterns
    categories: Counter[str] = Counter()
    for pattern in memory.get("patterns", []):
        name = pattern.get("name", "")
        if ":" in name:
            categories[name.split(":")[0]] += pattern.get("count", 1)

    # Reversal rate: decisions mentioning reversals / total
    reversal_kw = {"revert", "undo", "removed", "superseded", "rollback"}
    reversals = sum(
        1 for d in decisions
        if any(kw in d.get("decision", "").lower() for kw in reversal_kw)
    )
    reversal_rate = round(reversals / total, 4) if total > 0 else 0.0

    # Average confidence from knowledge_decay-style scores
    confidences = [
        d.get("confidence", {}).get("score", 0.5)
        for d in decisions
        if isinstance(d.get("confidence"), dict)
    ]
    avg_confidence = (
        round(sum(confidences) / len(confidences), 4) if confidences else 0.5
    )

    avg_safety_score, risk_level_distribution = _safety_posture(decisions)

    return {
        "decision_count": total,
        "reversal_rate": reversal_rate,
        "avg_confidence": avg_confidence,
        "category_distribution": dict(categories),
        "tech_stack": [t for t in tech_stack if isinstance(t, str)],
        "avg_safety_score": avg_safety_score,
        "risk_level_distribution": risk_level_distribution,
    }


def anonymize_project(memory: dict) -> Result[AnonymizedStats]:
    """Strip all text from project memory, keep only structural stats safe to share."""
    if not isinstance(memory, dict):
        return Err(error="Memory must be a dict", code="VALIDATION_ERROR")

    name = memory.get("project_name", "")
    if not name:
        return Err(error="Missing project_name", code="VALIDATION_ERROR")

    stats = extract_structural_stats(memory)
    return Ok(value=AnonymizedStats(
        project_hash=hash_project_name(name),
        tech_stack=sorted(stats["tech_stack"]),
        decision_count=stats["decision_count"],
        reversal_rate=stats["reversal_rate"],
        avg_confidence=stats["avg_confidence"],
        category_distribution=stats["category_distribution"],
        avg_safety_score=stats["avg_safety_score"],
        risk_level_distribution=stats["risk_level_distribution"],
    ))
