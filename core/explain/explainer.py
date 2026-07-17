"""
Tropelex Explainable Memory — Causal explanations for 'why' questions.

Pure functions that walk the decision tree, extract provenance,
and compose natural-language answers. No I/O.
"""

import re
from dataclasses import dataclass
from typing import Any

from core.decision_tree import DecisionTree, _similarity
from core.knowledge_decay import score_decisions

# Reuse the same stop words as rag.py for consistency
_STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "have",
    "has", "had", "do", "does", "did", "will", "would", "could", "should",
    "may", "might", "can", "to", "of", "in", "for", "on", "with", "at",
    "by", "from", "as", "and", "but", "or", "not", "so", "if", "then",
    "that", "this", "it", "its", "we", "our", "i", "my", "you", "your",
}


@dataclass(frozen=True)
class ExplanationReport:
    """Full causal explanation for a 'why' question."""
    question: str
    answer: str
    causal_chain: list[dict[str, Any]]
    provenance: dict[str, Any]
    supersession_chain: list[dict[str, Any]]
    downstream_impact: list[dict[str, Any]]
    source_citations: list[dict[str, Any]]
    confidence: float


def _tokenize(text: str) -> set[str]:
    """Extract lowercase word tokens, stripping stop words."""
    return {
        w.lower()
        for w in re.findall(r"[a-zA-Z][a-zA-Z0-9]+", text)
        if w.lower() not in _STOP_WORDS
    }


def _find_best_matching_decision(
    question: str, decisions: list[dict]
) -> dict | None:
    """Find the decision most relevant to the question using keyword overlap.

    Returns the best-matching decision dict, or None.
    """
    if not decisions:
        return None

    question_kw = _tokenize(question)
    if not question_kw:
        return None

    best_decision = None
    best_score = 0.0

    for d in decisions:
        decision_text = f"{d.get('decision', '')} {d.get('context', '')}"
        decision_kw = _tokenize(decision_text)
        score = _similarity(question_kw, decision_kw)
        if score > best_score:
            best_score = score
            best_decision = d

    return best_decision if best_score > 0.0 else None


def _build_causal_chain(
    decision_id: str, tree: DecisionTree
) -> list[dict[str, Any]]:
    """Walk ancestors via caused_by/supersedes edges to build causal chain.

    Returns list of {decision, relationship, depth} in order.
    """
    ancestors = tree.get_ancestors(decision_id, max_depth=5)
    # get_ancestors already returns {decision, relationship, depth}
    # Sort by depth ascending so root causes come first
    ancestors.sort(key=lambda x: x.get("depth", 0))
    return ancestors


def _build_supersession_chain(
    decision_id: str, tree: DecisionTree
) -> list[dict[str, Any]]:
    """Find what superseded this decision (if anything), walking forward.

    Returns list of {decision, relationship, timestamp}.
    """
    descendants = tree.get_descendants(decision_id, max_depth=5)
    supersessions = [
        {
            "decision": d["decision"],
            "relationship": d["relationship"],
            "timestamp": d["decision"].get("timestamp", ""),
        }
        for d in descendants
        if d.get("relationship") in ("supersedes", "reverts")
    ]
    supersessions.sort(
        key=lambda x: x.get("timestamp", "")
    )
    return supersessions


def _compute_downstream_impact(
    decision_id: str, tree: DecisionTree
) -> list[dict[str, Any]]:
    """Find descendants (decisions caused by this one).

    Returns list of {decision, relationship, depth}.
    """
    return tree.get_descendants(decision_id, max_depth=3)


def _extract_provenance(decision: dict) -> dict[str, Any]:
    """Extract who/when/confidence from a decision.

    Returns {author, timestamp, confidence_score, confidence_tier, source}.
    """
    all_decisions = [decision]
    scored = score_decisions(all_decisions)
    confidence_info = scored[0] if scored else {}

    return {
        "author": decision.get("author", "unknown"),
        "timestamp": decision.get("timestamp", ""),
        "confidence_score": confidence_info.get("score", 0.0),
        "confidence_tier": confidence_info.get("tier", "unknown"),
        "source": decision.get("source", "manual"),
    }


def _build_source_citations(
    decision: dict, memory: dict
) -> list[dict[str, Any]]:
    """Find git commits and session history entries referencing this decision.

    Returns list of {type, reference, date}.
    """
    citations: list[dict[str, Any]] = []
    decision_text = decision.get("decision", "").lower()
    decision_id = decision.get("id", "")

    for commit in memory.get("git_history", []):
        message = commit.get("message", "").lower()
        if decision_id and decision_id in message:
            citations.append({
                "type": "git_commit",
                "reference": commit.get("message", "")[:120],
                "date": commit.get("date", ""),
            })
        elif _has_keyword_overlap(decision_text, message):
            citations.append({
                "type": "git_commit",
                "reference": commit.get("message", "")[:120],
                "date": commit.get("date", ""),
            })

    for session in memory.get("session_history", []):
        summary = session.get("summary", "").lower()
        if decision_id and decision_id in summary:
            citations.append({
                "type": "session",
                "reference": session.get("summary", "")[:120],
                "date": session.get("timestamp", ""),
            })
        elif _has_keyword_overlap(decision_text, summary):
            citations.append({
                "type": "session",
                "reference": session.get("summary", "")[:120],
                "date": session.get("timestamp", ""),
            })

    return citations


def _has_keyword_overlap(text_a: str, text_b: str, threshold: float = 0.3) -> bool:
    """Check if two texts share meaningful keyword overlap."""
    kw_a = _tokenize(text_a)
    kw_b = _tokenize(text_b)
    return _similarity(kw_a, kw_b) >= threshold


def _generate_natural_language_answer(
    decision: dict,
    causal_chain: list,
    supersession_chain: list,
    downstream_impact: list,
) -> str:
    """Generate a human-readable answer from the structured data.

    Compose: "We decided X because Y. It was made by Z on date.
    If superseded: 'This was later replaced by W.'
    If has downstream: 'This led to N other decisions.'"
    """
    decision_text = decision.get("decision", "an unspecified decision")
    author = decision.get("author", "unknown")
    timestamp = decision.get("timestamp", "an unknown date")
    context = decision.get("context", "")

    parts = [f"We decided {decision_text}."]
    if context:
        parts.append(f"Context: {context}.")
    parts.append(f"This decision was made by {author} on {timestamp}.")

    if causal_chain:
        causes = causal_chain[0]
        cause_text = causes.get("decision", {}).get("decision", "a prior decision")
        parts.append(
            f"This was influenced by: \"{cause_text}\"."
        )

    if supersession_chain:
        latest = supersession_chain[-1]
        replacement = latest.get("decision", {}).get("decision", "a newer decision")
        parts.append(f"This was later replaced by: \"{replacement}\".")

    if downstream_impact:
        count = len(downstream_impact)
        parts.append(f"This led to {count} downstream decision{'s' if count != 1 else ''}.")

    return " ".join(parts)


def explain_why(
    question: str,
    memory: dict,
    tree: DecisionTree | None = None,
) -> ExplanationReport:
    """Main entry point. Given a 'why' question and project memory,
    produce a full ExplanationReport.

    Steps:
    1. Find best matching decision
    2. Build causal chain via tree
    3. Build supersession chain
    4. Compute downstream impact
    5. Extract provenance
    6. Build source citations
    7. Generate natural language answer
    8. Return ExplanationReport
    """
    decisions = memory.get("decisions", [])
    if not decisions:
        return ExplanationReport(
            question=question,
            answer="No decisions found in memory.",
            causal_chain=[],
            provenance={},
            supersession_chain=[],
            downstream_impact=[],
            source_citations=[],
            confidence=0.0,
        )

    if tree is None:
        tree = DecisionTree.from_decisions(decisions)

    best = _find_best_matching_decision(question, decisions)

    if best is None:
        return ExplanationReport(
            question=question,
            answer="No matching decision found.",
            causal_chain=[],
            provenance={},
            supersession_chain=[],
            downstream_impact=[],
            source_citations=[],
            confidence=0.0,
        )

    decision_id = best.get("id", "")
    causal_chain = _build_causal_chain(decision_id, tree)
    supersession_chain = _build_supersession_chain(decision_id, tree)
    downstream_impact = _compute_downstream_impact(decision_id, tree)
    provenance = _extract_provenance(best)
    source_citations = _build_source_citations(best, memory)

    answer = _generate_natural_language_answer(
        best, causal_chain, supersession_chain, downstream_impact
    )

    confidence = provenance.get("confidence_score", 0.0)

    return ExplanationReport(
        question=question,
        answer=answer,
        causal_chain=causal_chain,
        provenance=provenance,
        supersession_chain=supersession_chain,
        downstream_impact=downstream_impact,
        source_citations=source_citations,
        confidence=confidence,
    )
