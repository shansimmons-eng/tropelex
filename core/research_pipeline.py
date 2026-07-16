"""
Tropelex Research Pipeline
Auto-research, staleness detection, and semantic deduplication.
"""

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("tropelex.research")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _age_days(iso_date: str) -> float | None:
    try:
        dt = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).days
    except Exception:
        return None


# ── Staleness Detection ───────────────────────────────────────────────────────


def check_staleness(citations: dict, max_age_days: int = 90) -> list[dict]:
    """
    Return citations that are stale (older than max_age_days with no recent access).
    """
    stale = []
    for cid, c in citations.items():
        age = _age_days(c.get("created_at", ""))
        if age is not None and age > max_age_days:
            stale.append(
                {
                    "id": cid,
                    "title": c.get("title", ""),
                    "url": c.get("url", ""),
                    "age_days": age,
                    "reason": f"Created {age} days ago, never reviewed"
                    if not c.get("last_accessed")
                    else f"Last accessed {_age_days(c['last_accessed'])} days ago",
                }
            )
    stale.sort(key=lambda x: x["age_days"], reverse=True)
    return stale


# ── Semantic Deduplication ────────────────────────────────────────────────────


async def find_semantic_duplicates(
    tropebook,
    embed_store,
    threshold: float = 0.92,
) -> list[dict]:
    """
    Find citation pairs that are semantically similar above threshold.
    Uses existing embedding store — only checks already-embedded citations.
    """
    duplicates = []
    cids = list(tropebook.citations.keys())
    scored: list[tuple] = []  # (score, cid_a, cid_b)

    for i, cid_a in enumerate(cids):
        if not embed_store.has(cid_a):
            continue
        entry_a = embed_store._store[cid_a]
        vec_a = entry_a["vector"]

        for cid_b in cids[i + 1 :]:
            if not embed_store.has(cid_b):
                continue
            entry_b = embed_store._store[cid_b]
            vec_b = entry_b["vector"]

            from core.embeddings import _cosine

            score = _cosine(vec_a, vec_b)
            if score >= threshold:
                scored.append((score, cid_a, cid_b))

    scored.sort(reverse=True)
    for score, cid_a, cid_b in scored:
        c_a = tropebook.citations.get(cid_a)
        c_b = tropebook.citations.get(cid_b)
        if c_a and c_b:
            duplicates.append(
                {
                    "score": round(score, 4),
                    "id_a": cid_a,
                    "title_a": c_a.title,
                    "url_a": c_a.url,
                    "id_b": cid_b,
                    "title_b": c_b.title,
                    "url_b": c_b.url,
                }
            )

    return duplicates


# ── Auto Research ─────────────────────────────────────────────────────────────


async def auto_research(query: str, tropebook, max_results: int = 5) -> dict[str, Any]:
    """
    Search the web for a query and auto-add results as citations.
    Uses DuckDuckGo (free) or Brave if key is configured.
    """
    import os

    results = []

    # Try Brave first
    brave_key = os.environ.get("BRAVE_SEARCH_API_KEY", "")
    if brave_key:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params={"q": query, "count": max_results},
                    headers={
                        "Accept": "application/json",
                        "X-Subscription-Token": brave_key,
                    },
                )
                if r.status_code == 200:
                    for item in (
                        r.json().get("web", {}).get("results", [])[:max_results]
                    ):
                        results.append(
                            {
                                "title": item.get("title", ""),
                                "url": item.get("url", ""),
                                "summary": item.get("description", ""),
                            }
                        )
        except Exception as e:
            logger.warning("Brave search failed: %s", e)

    # Fall back to DuckDuckGo
    if not results:
        try:
            try:
                from ddgs import DDGS
            except ImportError:
                from duckduckgo_search import DDGS

            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=max_results):
                    results.append(
                        {
                            "title": r.get("title", ""),
                            "url": r.get("href", ""),
                            "summary": r.get("body", ""),
                        }
                    )
        except Exception as e:
            logger.warning("DuckDuckGo search failed: %s", e)
            return {"added": 0, "error": str(e), "results": []}

    # Add to tropebook
    added = 0
    for item in results:
        if item["url"]:
            from core.tropebook.tropebook import SourceType

            tropebook.add(
                title=item["title"][:500],
                url=item["url"][:2000],
                summary=item["summary"][:5000],
                tags=[t.strip().lower() for t in query.split() if len(t) > 3][:5],
                source_type=SourceType.SCRAPED,
            )
            added += 1

    return {"added": added, "results": results, "query": query}


# ── Related Suggestions ───────────────────────────────────────────────────────


async def suggest_related(
    cid: str, tropebook, embed_store, top_k: int = 5
) -> list[dict]:
    """
    Given a citation, find semantically related citations via embeddings.
    Falls back to tag matching if no embedding exists.
    """
    citation = tropebook.citations.get(cid)
    if not citation:
        return []

    # Try embedding-based search
    if embed_store.has(cid):
        vec = embed_store._store[cid]["vector"]
        hits = embed_store.search(vec, top_k=top_k + 1, min_score=0.5)
        return [h for h in hits if h["id"] != cid][:top_k]

    # Fall back to tag overlap
    if not citation.tags:
        return []
    related = []
    for other_cid, other in tropebook.citations.items():
        if other_cid == cid:
            continue
        overlap = set(citation.tags) & set(other.tags)
        if overlap:
            related.append(
                {
                    "id": other_cid,
                    "score": len(overlap) / max(len(citation.tags), 1),
                    "text": other.title,
                    "meta": {"title": other.title, "url": other.url, "match": "tags"},
                }
            )
    related.sort(key=lambda x: x["score"], reverse=True)
    return related[:top_k]
