"""
Memory Search API — keyword + optional semantic search across project memory.

Provides natural language search across decisions, sessions, and patterns.
Uses keyword matching as baseline; falls back to embeddings if available.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger("tropelex.search")

search_router = APIRouter(prefix="/api/memory", tags=["search"])

_CORE_DIR = Path(__file__).parent.parent
BASE_DIR = _CORE_DIR.parent


def _load_memory(project: str) -> dict[str, Any]:
    path = BASE_DIR / "memory" / f"{project}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Project '{project}' not found")
    return json.loads(path.read_text())


_STOP = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "have", "has",
    "had", "do", "does", "did", "will", "would", "could", "should", "may",
    "might", "can", "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "as", "and", "but", "or", "not", "so", "if", "then", "that", "this", "it",
    "its", "we", "our", "i", "my", "you", "your", "about", "what", "which",
}


def _tokenize(text: str) -> set[str]:
    """Lowercase alphanumeric tokens, minus stopwords."""
    words = re.findall(r"[a-z][a-z0-9]+", text.lower())
    return {w for w in words if w not in _STOP and len(w) > 2}


def _keyword_score(query_tokens: set[str], text: str) -> float:
    """Fraction of query tokens found in text."""
    if not query_tokens:
        return 0.0
    text_tokens = _tokenize(text)
    overlap = query_tokens & text_tokens
    return len(overlap) / len(query_tokens)


def search_memory(
    memory: dict, query: str, limit: int = 10, min_score: float = 0.1
) -> list[dict[str, Any]]:
    """Search decisions, sessions, and patterns by keyword relevance.

    Returns list of {type, text, score, timestamp, context}.
    """
    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    results: list[dict[str, Any]] = []

    # Search decisions
    for d in memory.get("decisions", []):
        text = d.get("decision", "")
        ctx = d.get("context", "")
        score = max(
            _keyword_score(query_tokens, text),
            _keyword_score(query_tokens, ctx) * 0.7,
        )
        if score >= min_score:
            results.append({
                "type": "decision",
                "text": text[:200],
                "context": ctx[:200],
                "score": round(score, 3),
                "timestamp": d.get("timestamp", ""),
            })

    # Search sessions
    for s in memory.get("session_history", []):
        text = s.get("summary", "")
        score = _keyword_score(query_tokens, text)
        if score >= min_score:
            results.append({
                "type": "session",
                "text": text[:200],
                "context": "",
                "score": round(score, 3),
                "timestamp": s.get("date", ""),
            })

    # Search patterns
    for p in memory.get("patterns", []):
        text = p.get("name", "")
        score = _keyword_score(query_tokens, text)
        if score >= min_score:
            results.append({
                "type": "pattern",
                "text": text,
                "context": f"Seen {p.get('count', 0)} times",
                "score": round(score, 3),
                "timestamp": p.get("last_seen", ""),
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]


@search_router.get("/{project}/search")
async def memory_search(
    project: str,
    q: str = Query(..., min_length=1, max_length=500),
    limit: int = Query(default=10, ge=1, le=50),
    min_score: float = Query(default=0.1, ge=0.0, le=1.0),
) -> dict[str, Any]:
    """Natural language search across a project's memory."""
    try:
        memory = _load_memory(project)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("search load failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    results = search_memory(memory, q, limit=limit, min_score=min_score)
    return {
        "query": q,
        "project": project,
        "results": results,
        "count": len(results),
    }
