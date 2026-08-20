"""
GitHub Search client for RepoSeek — parallel, deduplicated, with Result error handling.

Makes up to 3 parallel GitHub Search API calls (by query, by language, by topics),
deduplicates by repository URL, and returns typed Result values.
"""

from __future__ import annotations

import asyncio
import logging
import warnings
from typing import Any

import httpx

from core.github.search_client import (
    DEFAULT_TIMEOUT,
    auth_headers,
    deduplicate_results,
    fetch_search_page,
    get_token,
    parse_item,
)
from core.reposeek.models import RepoResult, SeekQuery
from core.result import Err, Ok, Result

logger = logging.getLogger("reposeek.github_client")


def _build_queries(query: SeekQuery) -> list[str]:
    """Return up to 3 GitHub search query strings from a SeekQuery.

    Each query targets a different search dimension:
    1. Short text search (always present) — core relevance
    2. Topic search (when topics provided) — breadth via ecosystem tags
    3. Language + topic combo (when both available) — precision

    Note: GitHub search is very literal — adding language: to text queries
    often kills recall. We keep language filtering to topic/combo queries only.
    """
    queries: list[str] = []

    # Primary: short text search (3 words max for best GitHub search results)
    words = query.query.split()
    short_query = " ".join(words[:3])
    queries.append(short_query)

    # Secondary: topic-only search for ecosystem breadth
    if query.topics:
        lang_lower = (query.language or "").lower()
        topics = [t for t in query.topics if t.lower() != lang_lower]
        if topics:
            queries.append(" ".join(f"topic:{t}" for t in topics[:4]))

    # Tertiary: text + language (separate query, not appended to text)
    if query.language and words:
        queries.append(f"{short_query} language:{query.language}")

    return queries


async def search_github(query: SeekQuery) -> Result[list[RepoResult], Err]:
    """Search GitHub with parallel API calls and return deduplicated results.

    Up to 3 parallel requests: by query text, by language, by topics.
    Returns Ok(list[RepoResult]) on success, Err on failure.
    """
    token = get_token()
    if not token:
        warnings.warn(
            "No GITHUB_TOKEN or GH_TOKEN set — using unauthenticated requests (60 req/hr limit)",
            stacklevel=2,
        )

    search_queries = _build_queries(query)
    headers = auth_headers(token)

    async with httpx.AsyncClient(
        headers=headers, timeout=DEFAULT_TIMEOUT
    ) as client:
        tasks = [fetch_search_page(client, q) for q in search_queries]
        results: list[Result[list[dict[str, Any]], Err]] = await asyncio.gather(*tasks)

    # Propagate first error encountered
    for r in results:
        if isinstance(r, Err):
            return r

    all_items: list[dict[str, Any]] = []
    for r in results:
        if isinstance(r, Ok):
            all_items.extend(r.value)

    unique_items = deduplicate_results(all_items)
    repo_results = [parse_item(item) for item in unique_items]
    return Ok(value=repo_results)
