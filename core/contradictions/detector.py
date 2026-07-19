"""
Contradiction Detector — pure functions for finding conflicting decisions.

Scans decision pairs for direct, implicit, and temporal contradictions.
Pure functions only — no I/O, no network, no file access.
"""

import hashlib
import re
from itertools import combinations

from core.contradictions import (
    Contradiction,
    ContradictionReport,
)


# --- Opposing keyword pairs for direct contradiction detection ---
_OPPOSING_PAIRS: list[tuple[str, str]] = [
    ("use", "don't use"),
    ("use", "do not use"),
    ("use", "avoid"),
    ("use", "remove"),
    ("enable", "disable"),
    ("include", "exclude"),
    ("add", "remove"),
    ("allow", "disallow"),
    ("allow", "forbid"),
    ("allow", "block"),
    ("require", "optional"),
    ("always", "never"),
    ("must", "must not"),
    ("should", "should not"),
    ("prefer", "avoid"),
    ("adopt", "reject"),
    ("keep", "drop"),
    ("start", "stop"),
    ("enable", "deprecate"),
]

# Technology pairs that are typically mutually exclusive
_TECH_OPPOSITIONS: list[tuple[str, str]] = [
    ("rest", "graphql"),
    ("rest", "grpc"),
    ("graphql", "rest"),
    ("mysql", "postgres"),
    ("react", "vue"),
    ("react", "angular"),
    ("vue", "react"),
    ("vue", "angular"),
    ("angular", "react"),
    ("angular", "vue"),
    ("typescript", "javascript"),
    ("docker", "kubernetes"),
    ("monolith", "microservice"),
    ("monolith", "microservices"),
    ("sql", "nosql"),
    ("mocha", "jest"),
    ("pytest", "unittest"),
    ("webpack", "vite"),
    ("redux", "zustand"),
    ("redux", "mobx"),
    ("express", "fastify"),
    ("express", "koa"),
    ("flask", "django"),
    ("jwt", "session"),
    ("oauth", "basic auth"),
]


def compute_similarity(text_a: str, text_b: str) -> float:
    """Keyword overlap similarity score between two texts.

    Returns a float 0.0-1.0 based on Jaccard similarity of word sets.
    """
    words_a = set(_tokenize(text_a))
    words_b = set(_tokenize(text_b))
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


def detect_direct_contradiction(text_a: str, text_b: str) -> bool:
    """Check for opposing keywords indicating a direct contradiction.

    Detects patterns like "use X" vs "don't use X" and
    mutually exclusive technology choices.
    """
    lower_a = text_a.lower()
    lower_b = text_b.lower()

    # Check opposing verb pairs
    for pos, neg in _OPPOSING_PAIRS:
        if (pos in lower_a and neg in lower_b) or (neg in lower_a and pos in lower_b):
            # Verify they reference the same subject
            if _share_subject(lower_a, lower_b):
                return True

    # Check mutually exclusive technologies
    for tech_a, tech_b in _TECH_OPPOSITIONS:
        if (tech_a in lower_a and tech_b in lower_b) or (
            tech_b in lower_a and tech_a in lower_b
        ):
            return True

    return False


def classify_contradiction(
    decision_a: dict, decision_b: dict, similarity: float
) -> Contradiction | None:
    """Classify the type and severity of a contradiction between two decisions.

    Returns a Contradiction if one is detected, None otherwise.
    """
    text_a = decision_a.get("decision", "")
    text_b = decision_b.get("decision", "")
    id_a = decision_a.get("id", "unknown")
    id_b = decision_b.get("id", "unknown")

    # Only consider pairs with some similarity
    if similarity < 0.15:
        return None

    is_direct = detect_direct_contradiction(text_a, text_b)
    is_temporal = _detect_temporal(decision_a, decision_b)

    if not is_direct and not is_temporal and similarity < 0.4:
        return None

    # Determine type
    if is_direct:
        contradiction_type = "direct"
        severity = "high"
    elif is_temporal:
        contradiction_type = "temporal"
        severity = "medium"
    else:
        contradiction_type = "implicit"
        severity = "low"

    # Adjust severity by similarity
    if severity == "low" and similarity > 0.6:
        severity = "medium"

    cid = _make_id(id_a, id_b)
    suggestion = _suggest_for_type(contradiction_type, text_a, text_b)

    return Contradiction(
        id=cid,
        decision_a_id=id_a,
        decision_a_text=text_a,
        decision_b_id=id_b,
        decision_b_text=text_b,
        contradiction_type=contradiction_type,
        severity=severity,
        similarity_score=round(similarity, 3),
        resolution_suggestion=suggestion,
    )


def suggest_resolution(contradiction: Contradiction) -> str:
    """Suggest how to resolve a contradiction."""
    return _suggest_for_type(
        contradiction.contradiction_type,
        contradiction.decision_a_text,
        contradiction.decision_b_text,
    )


def detect_contradictions(decisions: list[dict]) -> ContradictionReport:
    """Scan all decision pairs for contradictions.

    Returns a ContradictionReport with all detected contradictions.
    """
    if not decisions:
        return ContradictionReport(
            contradictions=[], total_checked=0, unresolved_count=0
        )

    contradictions: list[Contradiction] = []
    pair_count = 0

    for da, db in combinations(decisions, 2):
        pair_count += 1
        text_a = da.get("decision", "")
        text_b = db.get("decision", "")
        similarity = compute_similarity(text_a, text_b)
        result = classify_contradiction(da, db, similarity)
        if result is not None:
            contradictions.append(result)

    contradictions.sort(key=lambda c: _severity_rank(c.severity))

    return ContradictionReport(
        contradictions=contradictions,
        total_checked=pair_count,
        unresolved_count=len(contradictions),
    )


# --- Private helpers ---


def _tokenize(text: str) -> list[str]:
    """Lowercase, split on non-alphanumeric, drop short tokens."""
    stop_words = {
        "the", "a", "an", "to", "and", "of", "in", "for", "is", "on",
        "that", "it", "with", "as", "at", "by", "from", "or", "be",
    }
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [w for w in words if len(w) > 1 and w not in stop_words]


def _share_subject(text_a: str, text_b: str) -> bool:
    """Check if two texts share a noun/topic (beyond stop words)."""
    words_a = set(_tokenize(text_a)) - {"use", "don't", "do", "not", "avoid",
                                         "enable", "disable", "add", "remove",
                                         "always", "never", "prefer"}
    words_b = set(_tokenize(text_b)) - {"use", "don't", "do", "not", "avoid",
                                         "enable", "disable", "add", "remove",
                                         "always", "never", "prefer"}
    return bool(words_a & words_b)


def _detect_temporal(decision_a: dict, decision_b: dict) -> bool:
    """Detect temporal contradictions: newer decision supersedes older one on same topic."""
    ts_a = decision_a.get("timestamp", "")
    ts_b = decision_b.get("timestamp", "")
    if not ts_a or not ts_b:
        return False

    text_a = decision_a.get("decision", "").lower()
    text_b = decision_b.get("decision", "").lower()

    reversal_keywords = {"revert", "undo", "roll back", "switch back",
                         "replaced", "changed", "updated", "migrated"}
    has_reversal = any(kw in text_a or kw in text_b for kw in reversal_keywords)
    if not has_reversal:
        return False

    shared = set(_tokenize(text_a)) & set(_tokenize(text_b))
    return len(shared) >= 2


def _make_id(id_a: str, id_b: str) -> str:
    """Deterministic contradiction ID from two decision IDs."""
    pair = tuple(sorted([id_a, id_b]))
    raw = f"{pair[0]}:{pair[1]}"
    return "ctr-" + hashlib.sha256(raw.encode()).hexdigest()[:12]


def _severity_rank(severity: str) -> int:
    """Numeric rank for sorting (high=0 first)."""
    return {"high": 0, "medium": 1, "low": 2}.get(severity, 3)


def _suggest_for_type(ctype: str, text_a: str, text_b: str) -> str:
    """Generate resolution suggestion based on contradiction type."""
    if ctype == "direct":
        return (
            f"These decisions directly conflict. Review both and supersede the "
            f"outdated one: '{text_a[:60]}' vs '{text_b[:60]}'"
        )
    if ctype == "temporal":
        return (
            "A newer decision may have superseded an older one. "
            "Confirm the latest is still valid and mark the old one as superseded."
        )
    return (
        "These decisions appear related but may conflict implicitly. "
        "Review for overlap and clarify scope if needed."
    )
