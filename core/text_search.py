"""
Shared keyword-search primitives -- token-overlap scoring against a query,
independent of what's being searched. Extracted out of core/search_router.py
once a second consumer (core/docs_search.py, static documentation search)
needed the exact same logic -- a shared module beats two independent
copies, same reasoning as core/result.py and core/audit.py.
"""

from __future__ import annotations

import re

_STOP = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "have", "has",
    "had", "do", "does", "did", "will", "would", "could", "should", "may",
    "might", "can", "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "as", "and", "but", "or", "not", "so", "if", "then", "that", "this", "it",
    "its", "we", "our", "i", "my", "you", "your", "about", "what", "which",
}


def tokenize(text: str) -> set[str]:
    """Lowercase alphanumeric tokens, minus stopwords."""
    words = re.findall(r"[a-z][a-z0-9]+", text.lower())
    return {w for w in words if w not in _STOP and len(w) > 2}


def keyword_score(query_tokens: set[str], text: str) -> float:
    """Fraction of query tokens found in text."""
    if not query_tokens:
        return 0.0
    text_tokens = tokenize(text)
    overlap = query_tokens & text_tokens
    return len(overlap) / len(query_tokens)
