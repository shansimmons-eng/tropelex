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
    # Concealment / circumvention vocabulary — added after noticing the
    # original list only covered generic add/remove-style phrasing, not
    # the "quietly work around or hide a safety-relevant change" language
    # this system's whole purpose (Ghost Decisions, #52's audit trail,
    # #53's override gate) is aimed at catching.
    ("hide", "expose"),
    ("obscure", "clarify"),
    ("obfuscate", "clarify"),
    ("cloak", "reveal"),
    ("spoof", "verify"),
    ("override", "respect"),
    ("bypass", "enforce"),
    ("skip", "enforce"),
    ("omit", "include"),
    ("ignore", "address"),
    ("authorize", "revoke"),
    ("escalate", "deescalate"),
    ("escalate", "de-escalate"),
    ("delete", "preserve"),
    ("inject", "validate"),
    ("inject", "sanitize"),
    ("strip", "preserve"),
    ("prioritize", "deprioritize"),
    ("suppress", "surface"),
    ("mask", "reveal"),
    ("redact", "disclose"),
    ("withhold", "disclose"),
    ("conceal", "disclose"),
    ("elevate", "restrict"),
    ("relax", "tighten"),
    ("weaken", "strengthen"),
    ("circumvent", "enforce"),
    ("evade", "comply"),
    ("waive", "require"),
    ("grant", "deny"),
    ("tamper", "preserve"),
    ("purge", "retain"),
    ("discard", "retain"),
    ("throttle", "saturate"),
    ("dismiss", "flag"),
    ("destruct", "preserve"),
    ("drain", "refill"),
    ("decommission", "keep"),
    ("sidestep", "address"),
    ("establish", "dismantle"),
    ("connect", "isolate"),
    ("silence", "alert"),
    ("brick", "restore"),
    ("distort", "clarify"),
    ("guess", "verify"),
    ("overwrite", "preserve"),
    ("forge", "verify"),
    ("pause", "resume"),
    ("freeze", "unfreeze"),
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


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two embedding vectors, 0.0-1.0-ish range
    (can go slightly negative for genuinely opposed vectors, which is fine
    — hybrid_similarity below just feeds it into a weighted blend)."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def hybrid_similarity(
    text_a: str,
    text_b: str,
    embedding_a: list[float] | None = None,
    embedding_b: list[float] | None = None,
) -> float:
    """Blend keyword (Jaccard) similarity with semantic (cosine) similarity
    when embeddings are available for both texts (#57).

    Keyword-only matching has a real, verified failure mode: two decisions
    that clearly conflict but share little literal vocabulary (e.g. "use
    JWT for auth" vs "store sessions server-side") score near-zero Jaccard
    similarity and never even reach classify_contradiction's similarity
    gate. Embeddings catch that; keyword overlap stays more precise for
    exact-term conflicts (tech-opposition pairs), so this blends both
    rather than replacing one with the other.

    Falls back to pure compute_similarity when either embedding is
    missing — the common case for any project without OPENAI_API_KEY
    configured, or before a decision has been embedded yet. That fallback
    is exact, not approximate: behavior is bit-for-bit identical to before
    this function existed.
    """
    keyword_score = compute_similarity(text_a, text_b)
    if embedding_a is None or embedding_b is None:
        return keyword_score
    semantic_score = max(0.0, _cosine_similarity(embedding_a, embedding_b))
    return round(0.4 * keyword_score + 0.6 * semantic_score, 4)


def _contains_phrase(text: str, phrase: str) -> bool:
    """Whole-word/phrase containment check, not raw substring.

    Bug found while verifying #57 live: raw `phrase in text` matched
    "add" inside "added" and "remove" inside "removed", so any two
    decisions that both happened to be phrased as past-tense change logs
    ("Added X" / "Removed Y") tripped the "add"/"remove" opposing pair
    regardless of whether X and Y were related at all. Word-boundary
    matching is the fix; multi-word phrases (e.g. "don't use") still
    match as a literal boundaried substring, which is correct for them.
    """
    return re.search(rf"\b{re.escape(phrase)}\b", text) is not None


def detect_direct_contradiction(text_a: str, text_b: str) -> bool:
    """Check for opposing keywords indicating a direct contradiction.

    Detects patterns like "use X" vs "don't use X" and
    mutually exclusive technology choices.
    """
    lower_a = text_a.lower()
    lower_b = text_b.lower()

    # Check opposing verb pairs
    for pos, neg in _OPPOSING_PAIRS:
        if (_contains_phrase(lower_a, pos) and _contains_phrase(lower_b, neg)) or (
            _contains_phrase(lower_a, neg) and _contains_phrase(lower_b, pos)
        ):
            # Verify they reference the same subject
            if _share_subject(lower_a, lower_b):
                return True

    # Check mutually exclusive technologies
    for tech_a, tech_b in _TECH_OPPOSITIONS:
        if (_contains_phrase(lower_a, tech_a) and _contains_phrase(lower_b, tech_b)) or (
            _contains_phrase(lower_a, tech_b) and _contains_phrase(lower_b, tech_a)
        ):
            return True

    return False


def classify_contradiction(
    decision_a: dict,
    decision_b: dict,
    similarity: float,
    keyword_similarity: float | None = None,
) -> Contradiction | None:
    """Classify the type and severity of a contradiction between two decisions.

    similarity: the score used to decide whether to even look at this pair
        (gate 1, below). May be the keyword/semantic hybrid (#57) — a
        generous gate is safe here because getting past it still requires
        an independent, keyword/date-based signal (detect_direct_contradiction,
        _detect_temporal) for anything but the small "implicit" category.
    keyword_similarity: pure keyword similarity, defaults to `similarity`
        when not given (preserves old callers/tests calling this with one
        plain float). Used for the "implicit" classification's own bar and
        severity bump (gate 2) — deliberately NOT the hybrid score. Found
        live: general-purpose text embeddings have a real same-domain
        baseline similarity (two unrelated but same-topic decisions can
        score 0.5+ on raw cosine) that's too close to genuine-conflict
        territory to trust without calibration data this project doesn't
        have yet. Gating "implicit" (the one category with no independent
        keyword/date signal backing it) on pure keyword overlap keeps that
        category exactly as conservative as it was before embeddings
        existed, while gate 1 still lets embeddings rescue real opposition
        pairs (like "JWT" vs "session storage") that share little
        vocabulary but are caught by detect_direct_contradiction once
        they're not filtered out before ever reaching it.

    Returns a Contradiction if one is detected, None otherwise.
    """
    text_a = decision_a.get("decision", "")
    text_b = decision_b.get("decision", "")
    id_a = decision_a.get("id", "unknown")
    id_b = decision_b.get("id", "unknown")
    keyword_similarity = similarity if keyword_similarity is None else keyword_similarity

    # Only consider pairs with some similarity
    if similarity < 0.15:
        return None

    is_direct = detect_direct_contradiction(text_a, text_b)
    is_temporal = _detect_temporal(decision_a, decision_b)

    if not is_direct and not is_temporal and keyword_similarity < 0.4:
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

    # Adjust severity by similarity — keyword-only for the same reason as
    # the gate above.
    if severity == "low" and keyword_similarity > 0.6:
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


def detect_contradictions(
    decisions: list[dict],
    embeddings: dict[str, list[float]] | None = None,
) -> ContradictionReport:
    """Scan all decision pairs for contradictions.

    embeddings: optional {decision_id: vector} lookup (#57). When a pair's
    vectors are both present, similarity is the keyword/semantic hybrid
    (hybrid_similarity); otherwise it's pure keyword (compute_similarity),
    identical to this function's behavior before embeddings existed. This
    function stays pure either way — callers (core/contradictions/router.py)
    own the actual embedding I/O and pass the results in as plain data.

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
        emb_a = embeddings.get(da.get("id", "")) if embeddings else None
        emb_b = embeddings.get(db.get("id", "")) if embeddings else None
        keyword_similarity = compute_similarity(text_a, text_b)
        similarity = hybrid_similarity(text_a, text_b, emb_a, emb_b)
        result = classify_contradiction(da, db, similarity, keyword_similarity=keyword_similarity)
        if result is not None:
            contradictions.append(result)

    contradictions.sort(key=lambda c: _severity_rank(c.severity))

    return ContradictionReport(
        contradictions=contradictions,
        total_checked=pair_count,
        unresolved_count=len(contradictions),
    )


def detect_contradictions_for_candidate(
    candidate: dict,
    existing: list[dict],
    embeddings: dict[str, list[float]] | None = None,
) -> list[Contradiction]:
    """Check one candidate decision against every existing decision — O(n),
    not detect_contradictions' O(n^2) full pairwise scan (#72).

    Built for a real-time write-path gate (add_decision): checking a new
    decision against a growing project's full decision history can't
    afford the periodic-scan-shaped cost of re-checking every existing
    pair too. `candidate` need not have an "id" yet — classify_contradiction
    defaults to "unknown" for a missing one; callers that need a stable id
    on the result should supply one explicitly.
    """
    text_candidate = candidate.get("decision", "")
    found: list[Contradiction] = []
    for other in existing:
        text_other = other.get("decision", "")
        emb_a = embeddings.get(candidate.get("id", "")) if embeddings else None
        emb_b = embeddings.get(other.get("id", "")) if embeddings else None
        keyword_similarity = compute_similarity(text_candidate, text_other)
        similarity = hybrid_similarity(text_candidate, text_other, emb_a, emb_b)
        result = classify_contradiction(candidate, other, similarity, keyword_similarity=keyword_similarity)
        if result is not None:
            found.append(result)
    found.sort(key=lambda c: _severity_rank(c.severity))
    return found


# --- Private helpers ---


def _tokenize(text: str) -> list[str]:
    """Lowercase, split on non-alphanumeric, drop short tokens."""
    stop_words = {
        "the", "a", "an", "to", "and", "of", "in", "for", "is", "on",
        "that", "it", "with", "as", "at", "by", "from", "or", "be",
    }
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [w for w in words if len(w) > 1 and w not in stop_words]


def _opposing_pair_tokens() -> frozenset[str]:
    """Every individual token appearing anywhere in _OPPOSING_PAIRS.

    _share_subject strips these before checking topic overlap — the
    action verbs themselves (use/remove/hide/expose/...) shouldn't count
    as "sharing a subject," only the actual topic words should. This is
    *derived* from _OPPOSING_PAIRS rather than hand-maintained: the
    original hand-written exclusion set silently fell out of sync with
    _OPPOSING_PAIRS (missing over half its terms — include, allow, must,
    should, keep, stop, and more) with nothing to catch the drift.
    Deriving it means it can't go stale again as _OPPOSING_PAIRS grows.
    """
    tokens: set[str] = set()
    for pos, neg in _OPPOSING_PAIRS:
        tokens.update(_tokenize(pos))
        tokens.update(_tokenize(neg))
    return frozenset(tokens)


_OPPOSING_PAIR_TOKENS = _opposing_pair_tokens()

# Generic decision-logging boilerplate ("Added feature: X", "Fixed: Y") that
# shows up as the only "shared" word between two otherwise-unrelated
# decisions purely because of a shared note-taking convention, not a shared
# topic. Found live, at scale, once #57's semantic gate started surfacing
# far more candidate pairs than pure keyword similarity ever had — e.g. two
# unrelated "Added feature: ..." decisions sharing "added"/"feature" was
# enough to pass a naive 2-shared-words bar. Separate from
# _OPPOSING_PAIR_TOKENS because these aren't opposing-pair verbs, they're
# meta-words describing that *a* change happened, not what it's about.
_STRUCTURAL_NOISE_WORDS = frozenset({
    "added", "add", "feature", "features", "fixed", "fix", "changed",
    "change", "decided", "decide", "reworked", "rework", "completed",
    "complete", "exception", "docs", "update", "updated", "implement",
    "implemented", "build", "built",
})

_SUBJECT_EXCLUDED_TOKENS = _OPPOSING_PAIR_TOKENS | _STRUCTURAL_NOISE_WORDS


def _share_subject(text_a: str, text_b: str) -> bool:
    """Check if two texts share a real topic (beyond stop words), not just
    one coincidental word.

    Found live, at scale, once #57's semantic gate started letting more
    pairs reach this check: a single shared incidental word ("feed" in
    "Use sqlite for feed persistence" vs a long, unrelated multi-clause
    decision that happened to also mention "feed creation") was enough to
    pass, combined with a generic opposing-pair match like ("use",
    "remove"), to misclassify two unrelated decisions as directly
    contradicting.

    Two shared words is a safe bar on its own. A single shared word is
    only trusted when it's a substantial fraction of the *shorter* side's
    remaining vocabulary — i.e. that word is plausibly what the terser
    decision is actually about ("Don't use React" vs "We should use
    React" — "react" is half of "react"'s own 2-word remainder), not one
    incidental match buried in an otherwise-unrelated, much longer
    sentence (3 words vs 13, only one of which overlaps).
    """
    words_a = set(_tokenize(text_a)) - _SUBJECT_EXCLUDED_TOKENS
    words_b = set(_tokenize(text_b)) - _SUBJECT_EXCLUDED_TOKENS
    shared = words_a & words_b
    if len(shared) >= 2:
        return True
    if len(shared) == 1 and words_a and words_b:
        return len(shared) / min(len(words_a), len(words_b)) >= 0.5
    return False


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
    # Word-boundary, not raw substring — found live: "undo" matched inside
    # "undocumented", same bug class already fixed in
    # detect_direct_contradiction (see _contains_phrase).
    has_reversal = any(_contains_phrase(text_a, kw) or _contains_phrase(text_b, kw) for kw in reversal_keywords)
    if not has_reversal:
        return False

    # Reuses _share_subject rather than its own separate raw-token overlap
    # check — that duplicate inline check (len(shared) >= 2 on unfiltered
    # _tokenize output, no structural-noise or opposing-pair exclusion) had
    # the exact same "added"/"feature" boilerplate false-positive problem,
    # just never noticed because it's a second, independent copy of the
    # same logic _share_subject already had to fix once.
    return _share_subject(text_a, text_b)


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
