"""
GitHub Search client for RepoSeek — parallel, deduplicated, with Result error handling.

Makes up to 3 parallel GitHub Search API calls (by query, by language, by topics),
deduplicates by repository URL, and returns typed Result values.
"""

from __future__ import annotations

import asyncio
import logging
import os
import warnings
from typing import Any

import httpx

from core.reposeek.models import RepoResult, SeekQuery
from core.result import Err, Ok, Result

logger = logging.getLogger("reposeek.github_client")

_GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
_DEFAULT_TIMEOUT = 15  # seconds


def _get_token() -> str | None:
    """Read GitHub token from env (GITHUB_TOKEN preferred, GH_TOKEN fallback).

    Returns None if neither is set — caller decides whether to warn.
    """
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def _auth_headers(token: str | None) -> dict[str, str]:
    """Build request headers, including Bearer auth when token is available."""
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


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


def _parse_item(item: dict[str, Any]) -> RepoResult:
    """Convert a single GitHub Search API item into a RepoResult.

    similarity_score and match_reasons are left as defaults — the scoring
    layer fills those in after retrieval.
    """
    return RepoResult(
        title=item.get("full_name", ""),
        url=item.get("html_url", ""),
        description=item.get("description") or "",
        language=item.get("language"),
        stars=item.get("stargazers_count", 0),
        similarity_score=0.0,
        match_reasons=[],
    )


async def _fetch_search_page(
    client: httpx.AsyncClient,
    search_query: str,
) -> Result[list[dict[str, Any]], Err]:
    """Execute a single GitHub Search API call and return raw items.

    Maps HTTP status codes to domain error codes per the spec:
    403 → RATE_LIMITED, 404 → NOT_FOUND, network errors → NETWORK_ERROR.
    """
    params = {"q": search_query, "per_page": 30}
    try:
        resp = await client.get(_GITHUB_SEARCH_URL, params=params)
        if resp.status_code == 403:
            return Err(error="GitHub API rate limit exceeded", code="RATE_LIMITED")
        if resp.status_code == 404:
            return Err(error="GitHub search endpoint not found", code="NOT_FOUND")
        resp.raise_for_status()
        data = resp.json()
        return Ok(value=data.get("items", []))
    except httpx.ConnectError as exc:
        logger.warning("GitHub connection failed: %s", exc)
        return Err(error=f"Connection failed: {exc}", code="NETWORK_ERROR")
    except httpx.TimeoutException as exc:
        logger.warning("GitHub request timed out: %s", exc)
        return Err(error=f"Request timed out: {exc}", code="NETWORK_ERROR")


def _deduplicate_results(all_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate raw API items by html_url, keeping the first occurrence."""
    seen_urls: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in all_items:
        url = item.get("html_url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique.append(item)
    return unique


async def search_github(query: SeekQuery) -> Result[list[RepoResult], Err]:
    """Search GitHub with parallel API calls and return deduplicated results.

    Up to 3 parallel requests: by query text, by language, by topics.
    Returns Ok(list[RepoResult]) on success, Err on failure.
    """
    token = _get_token()
    if not token:
        warnings.warn(
            "No GITHUB_TOKEN or GH_TOKEN set — using unauthenticated requests (60 req/hr limit)",
            stacklevel=2,
        )

    search_queries = _build_queries(query)
    headers = _auth_headers(token)

    async with httpx.AsyncClient(
        headers=headers, timeout=_DEFAULT_TIMEOUT
    ) as client:
        tasks = [_fetch_search_page(client, q) for q in search_queries]
        results: list[Result[list[dict[str, Any]], Err]] = await asyncio.gather(*tasks)

    # Propagate first error encountered
    for r in results:
        if isinstance(r, Err):
            return r

    all_items: list[dict[str, Any]] = []
    for r in results:
        if isinstance(r, Ok):
            all_items.extend(r.value)

    unique_items = _deduplicate_results(all_items)
    repo_results = [_parse_item(item) for item in unique_items]
    return Ok(value=repo_results)
