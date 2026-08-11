"""
Ghost Pattern Matcher — pure-function module for detecting when code
contradicts recorded architectural decisions.

Compares decision keywords against unified-diff hunks and scores
the severity of each potential "ghost" (decision that was silently ignored).
"""

import re
from dataclasses import dataclass
from typing import Any

from core.embeddings import cosine_similarity

# Minimum semantic similarity for the #67 rescue path to fire -- deliberately
# conservative starting point, tuned empirically against the real tropelex
# project's decision set (wishlist #67) before this ever reaches production
# thresholds. A rescue match is capped to "medium" severity regardless
# (core/ghost/preventive.py), so this threshold only controls whether a
# semantic-only warning surfaces at all, not whether it can block a write.
_SEMANTIC_RESCUE_THRESHOLD = 0.5

# Stopwords — identical set to core/decision_tree.py _extract_keywords
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

# Unified diff header patterns
_DIFF_FILE_RE = re.compile(r"^(---|\+\+\+) ")
_DIFF_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

# Patterns for extract_decision_topics
_CASE_PATTERNS: list[tuple[str, str]] = [
    (r"\bsnake_case\b", "naming:snake_case"),
    (r"\bcamelCase\b", "naming:camelCase"),
    (r"(?<!\w)[A-Z][a-z]+[A-Z]\w*", "naming:PascalCase"),
    (r"\bkebab-case\b", "naming:kebab-case"),
    (r"\bUPPER_SNAKE_CASE\b", "naming:UPPER_SNAKE_CASE"),
]
_ERROR_PATTERNS: list[tuple[str, str]] = [
    (r"\btry\s*/\s*except\b", "error_handling:try_except"),
    (r"\braise\b", "error_handling:raise"),
    (r"\bException\b", "error_handling:Exception"),
    (r"\bError\b", "error_handling:Error"),
    (r"\bResult\b.*\bOk\b|\bErr\b", "error_handling:Result"),
]
_IMPORT_PATTERNS: list[tuple[str, str]] = [
    (r"\bfrom\s+\S+\s+import\b", "imports:from_import"),
    (r"\bimport\s+\S+\b", "imports:import"),
]
_ASYNC_PATTERNS: list[tuple[str, str]] = [
    (r"\basync\s+def\b", "async:async_def"),
    (r"\bawait\b", "async:await"),
]
_TYPE_PATTERNS: list[tuple[str, str]] = [
    (r"\b:\s*(str|int|float|bool|list|dict|set|tuple)\b", "types:builtin_hint"),
    (r"\bOptional\b", "types:Optional"),
    (r"\bUnion\b", "types:Union"),
    (r"\bTypeVar\b", "types:TypeVar"),
    (r"\bProtocol\b", "types:Protocol"),
]


@dataclass(frozen=True)
class MatchResult:
    """A single match between a decision and a diff hunk."""
    decision_text: str
    diff_file: str
    diff_line: int
    matched_keywords: list[str]
    overlap_score: float
    hunk_snippet: str
    is_addition: bool = True
    # "keyword" (default, unchanged behavior) or "semantic" (#67's rescue --
    # a decision/diff pair with zero keyword overlap but real embedding
    # similarity). Defaulted so every pre-#67 construction of this
    # dataclass (core/ghost/detector.py, existing tests) is unaffected.
    match_type: str = "keyword"


def extract_keywords(text: str) -> set[str]:
    """Extract meaningful keywords from text. Same stopword pattern as decision_tree.py."""
    words = re.findall(r"[a-z][a-z0-9+#_]{2,}", text.lower())
    return {w for w in words if w not in _STOPWORDS}


def parse_diff_hunks(diff_text: str) -> list[dict[str, Any]]:
    """Parse a unified diff into structured hunks.

    Returns list of {file, line_number, content, is_addition, is_deletion}.
    Only parse added lines (+) and context lines, skip file headers.
    """
    hunks: list[dict[str, Any]] = []
    current_file = ""
    current_line = 0

    for raw_line in diff_text.splitlines():
        # "+++ b/path/to/file" carries the new filename — everything else
        # under _DIFF_FILE_RE ("---"/"+++") is just skipped. Requires the
        # trailing space real diff headers always have, so an added content
        # line that happens to start with "++" (raw diff "+++i;" for a
        # pre-increment statement, or a TOML frontmatter "+++" delimiter)
        # isn't mistaken for a header.
        if raw_line.startswith("+++ "):
            path = raw_line[len("+++ "):].strip()
            if path and path != "/dev/null":
                current_file = path[2:] if path[:2] in ("a/", "b/") else path
            continue
        if _DIFF_FILE_RE.match(raw_line):
            continue

        # Detect hunk header — extract starting line number
        hunk_match = _DIFF_HUNK_RE.match(raw_line)
        if hunk_match:
            current_line = int(hunk_match.group(1))
            continue

        # Process content lines. The real "+++ "/"--- " headers (with
        # trailing space) already matched and continue'd above, so any
        # "+++"/"---"-without-space line reaching here is content, not a
        # header -- must not be excluded the same way.
        if raw_line.startswith("+") and not raw_line.startswith("+++ "):
            hunks.append({
                "file": current_file,
                "line_number": current_line,
                "content": raw_line[1:],
                "is_addition": True,
                "is_deletion": False,
            })
            current_line += 1
        elif raw_line.startswith("-") and not raw_line.startswith("--- "):
            # Deletions tracked but content excluded from keyword matching
            hunks.append({
                "file": current_file,
                "line_number": current_line,
                "content": raw_line[1:],
                "is_addition": False,
                "is_deletion": True,
            })
            # Don't increment line — deleted lines have no new line number
        else:
            # Context line (space-prefixed or blank)
            content = raw_line[1:] if raw_line.startswith(" ") else raw_line
            hunks.append({
                "file": current_file,
                "line_number": current_line,
                "content": content,
                "is_addition": False,
                "is_deletion": False,
            })
            current_line += 1

    return hunks


def match_decision_to_diff(
    decision_text: str,
    diff_hunks: list[dict[str, Any]],
    decision_embedding: list[float] | None = None,
    diff_embedding: list[float] | None = None,
) -> list[MatchResult]:
    """Compare a decision's keywords against diff hunks.

    For each hunk, compute keyword overlap. Return matches where overlap > 0.2.
    Each MatchResult includes the hunk snippet and overlap score.

    decision_embedding/diff_embedding (#67): optional. Only consulted when
    the keyword loop above finds *nothing* for this decision -- a rescue
    for real violations that share no vocabulary with the decision text
    (e.g. a backdoor diff against a decision about "bypassing auth"), not a
    replacement for or boost to keyword matching. Both default to None, so
    every existing caller that doesn't pass them gets byte-for-byte the
    same output as before this parameter existed.
    """
    decision_kw = extract_keywords(decision_text)
    if not decision_kw:
        return []

    matches: list[MatchResult] = []
    for hunk in diff_hunks:
        hunk_kw = extract_keywords(hunk.get("content", ""))
        if not hunk_kw:
            continue

        # Jaccard overlap
        intersection = decision_kw & hunk_kw
        union = decision_kw | hunk_kw
        overlap = len(intersection) / len(union) if union else 0.0

        if overlap > 0.2:
            matches.append(MatchResult(
                decision_text=decision_text,
                diff_file=hunk.get("file", ""),
                diff_line=hunk.get("line_number", 0),
                matched_keywords=sorted(intersection),
                overlap_score=round(overlap, 4),
                hunk_snippet=hunk.get("content", "").strip(),
                is_addition=hunk.get("is_addition", True),
            ))

    if not matches and decision_embedding is not None and diff_embedding is not None:
        similarity = cosine_similarity(decision_embedding, diff_embedding)
        if similarity >= _SEMANTIC_RESCUE_THRESHOLD:
            first_file = next((h.get("file", "") for h in diff_hunks if h.get("file")), "")
            added_snippet = " ".join(
                h.get("content", "").strip() for h in diff_hunks if h.get("is_addition")
            ).strip()
            matches.append(MatchResult(
                decision_text=decision_text,
                diff_file=first_file,
                diff_line=0,
                matched_keywords=[],
                overlap_score=round(similarity, 4),
                hunk_snippet=_truncate_snippet(added_snippet),
                is_addition=True,
                match_type="semantic",
            ))

    return matches


def _truncate_snippet(text: str, limit: int = 200) -> str:
    """Shorten a synthesized semantic-match snippet for display."""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


def score_ghost_severity(
    match: MatchResult, decision_confidence: float
) -> float:
    """Score how severe this ghost decision is (0.0 to 1.0).

    severity = overlap_score * decision_confidence * severity_multiplier
    where severity_multiplier:
      - 1.0 if hunk is an addition (new code contradicts decision)
      - 0.5 if hunk is a deletion (removing code that followed decision)
    """
    severity_multiplier = 1.0 if match.is_addition else 0.5
    clamped_confidence = max(0.0, min(1.0, decision_confidence))
    raw = match.overlap_score * clamped_confidence * severity_multiplier
    return round(max(0.0, min(1.0, raw)), 4)


def extract_decision_topics(decision_text: str) -> set[str]:
    """Extract coding-convention topics from decision text.

    Detects patterns like: snake_case, camelCase, PascalCase,
    error handling (try/except, raise, Exception), imports (from X import Y),
    type hints, async/await, etc.
    Returns a set of topic tags.
    """
    topics: set[str] = set()
    all_patterns = (
        _CASE_PATTERNS
        + _ERROR_PATTERNS
        + _IMPORT_PATTERNS
        + _ASYNC_PATTERNS
        + _TYPE_PATTERNS
    )
    for pattern, tag in all_patterns:
        if re.search(pattern, decision_text):
            topics.add(tag)
    return topics
