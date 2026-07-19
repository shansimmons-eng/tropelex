"""
Multi-signal relevance scoring for predictive context prefetch.

Weighted combination of impact, category match, confidence decay, and
semantic similarity -- all pure functions returning normalized 0.0-1.0.
"""

import re
from dataclasses import dataclass
from typing import Union

from core.decision_tree import DecisionTree
from core.knowledge_decay import score_decision


@dataclass(frozen=True)
class Ok:
    """Successful computation result."""
    value: float


@dataclass(frozen=True)
class Err:
    """Failed computation result."""
    error: str
    code: str = "UNKNOWN"


Result = Union[Ok, Err]


DEFAULT_WEIGHTS: dict[str, float] = {
    "w_impact": 0.35,
    "w_category": 0.25,
    "w_confidence": 0.25,
    "w_semantic": 0.15,
}

_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "have",
    "has", "had", "do", "does", "did", "will", "would", "could", "should",
    "may", "might", "can", "to", "of", "in", "for", "on", "with", "at",
    "by", "from", "as", "and", "but", "or", "not", "so", "if", "then",
    "that", "this", "it", "its", "we", "our", "i", "my", "you", "your",
    "over", "into", "through", "during", "before", "after", "above",
    "below", "between", "under", "again", "further", "than", "very",
})


def _extract_keywords(text: str) -> set[str]:
    """Extract lowercase keywords, filtered by stopwords."""
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9]+", text.lower())
    return {w for w in words if w not in _STOPWORDS}


def compute_relevance_score(
    decision: dict,
    task_text: str,
    all_decisions: list[dict],
    weights: dict[str, float] | None = None,
) -> float:
    """Weighted multi-signal relevance score (0.0-1.0).

    Combines impact, category match, confidence decay, and semantic
    similarity into a single normalized score.
    """
    w = weights or DEFAULT_WEIGHTS
    impact = compute_impact_component(decision, all_decisions)
    category = match_categories(decision, task_text)
    confidence = compute_confidence_component(decision)
    semantic = compute_semantic_component(decision, task_text)

    score = (
        w.get("w_impact", 0.35) * impact
        + w.get("w_category", 0.25) * category
        + w.get("w_confidence", 0.25) * confidence
        + w.get("w_semantic", 0.15) * semantic
    )
    return max(0.0, min(1.0, score))


def compute_impact_component(
    decision: dict, all_decisions: list[dict]
) -> float:
    """Impact score: downstream dependents + reversal penalty (0.0-1.0).

    Uses DecisionTree to count how many other decisions depend on this one.
    Reversed decisions receive a 0.5 penalty (matching analysis.py pattern).
    """
    if not all_decisions:
        return 0.0
    tree = DecisionTree.from_decisions(all_decisions)
    did = decision.get("id") or decision.get("timestamp", "")

    descendants = tree.get_descendants(did, max_depth=3)
    is_reversed = any(
        e.get("relationship") in ("supersedes", "reverts")
        for e in decision.get("edges", [])
    )
    downstream_bonus = min(len(descendants) * 0.1, 0.5)
    base = 0.5  # neutral base when no tree info available
    penalty = 0.5 if is_reversed else 1.0
    return max(0.0, min(1.0, (base + downstream_bonus) * penalty))


def match_categories(decision: dict, task_text: str) -> float:
    """Category overlap between decision and task (0.0-1.0).

    Checks explicit categories on the decision, then computes keyword
    Jaccard-like overlap with the task text. Follows _decision_matches_category
    from packet_builder.py.
    """
    decision_cats = set(decision.get("categories", []))
    decision_text = f"{decision.get('decision', '')} {decision.get('context', '')}"
    decision_kw = _extract_keywords(decision_text)
    task_kw = _extract_keywords(task_text)

    if not decision_kw or not task_kw:
        if decision_cats:
            task_lower = task_text.lower()
            hits = sum(1 for c in decision_cats if c.lower() in task_lower)
            return hits / len(decision_cats)
        return 0.0

    # Combined: explicit categories as bonus + keyword Jaccard
    intersection = decision_kw & task_kw
    union = decision_kw | task_kw
    jaccard = len(intersection) / len(union) if union else 0.0

    cat_bonus = 0.0
    if decision_cats:
        task_lower = task_text.lower()
        hits = sum(1 for c in decision_cats if c.lower() in task_lower)
        cat_bonus = hits / len(decision_cats)

    return max(0.0, min(1.0, 0.5 * jaccard + 0.5 * cat_bonus))


def compute_confidence_component(decision: dict) -> float:
    """Confidence from knowledge decay (0.0-1.0).

    Delegates to knowledge_decay.score_decision for time-based
    confidence with reference and contradiction adjustments.
    """
    result = score_decision(decision)
    return max(0.0, min(1.0, result.get("score", 0.0)))


def compute_semantic_component(decision: dict, task_text: str) -> float:
    """Keyword overlap between decision and task text (0.0-1.0).

    Stopword-filtered, case-insensitive. Follows rag._keyword_match_score
    pattern: intersection over query word count.
    """
    decision_text = f"{decision.get('decision', '')} {decision.get('context', '')}"
    decision_kw = _extract_keywords(decision_text)
    task_kw = _extract_keywords(task_text)

    if not task_kw:
        return 0.0
    overlap = decision_kw & task_kw
    return len(overlap) / len(task_kw)
