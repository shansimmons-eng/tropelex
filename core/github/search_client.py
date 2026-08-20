"""
Shared low-level GitHub Search API primitives.

Extracted from core/reposeek/github_client.py so a second feature
(core/trending/) doesn't have to duplicate auth, single-page fetch with
its 403/404/network error mapping, dedup-by-url, and raw-item parsing.
Callers own their own query-string construction and multi-query merge
logic on top of these.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from core.reposeek.models import RepoResult
from core.result import Err, Ok, Result

logger = logging.getLogger("github.search_client")

GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
DEFAULT_TIMEOUT = 15  # seconds


def get_token() -> str | None:
    """Read GitHub token from env (GITHUB_TOKEN preferred, GH_TOKEN fallback).

    Returns None if neither is set — caller decides whether to warn.
    """
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def auth_headers(token: str | None) -> dict[str, str]:
    """Build request headers, including Bearer auth when token is available."""
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def parse_item(item: dict[str, Any]) -> RepoResult:
    """Convert a single GitHub Search API item into a RepoResult.

    similarity_score and match_reasons are left as defaults — callers that
    need scoring apply core.reposeek.scoring.score_results afterward.
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


async def fetch_search_page(
    client: httpx.AsyncClient,
    search_query: str,
    per_page: int = 30,
    extra_params: dict[str, str] | None = None,
) -> Result[list[dict[str, Any]], Err]:
    """Execute a single GitHub Search API call and return raw items.

    extra_params merges in additional query params (e.g. sort/order) on
    top of q/per_page -- used by callers that want a specific ranking
    rather than the API's default best-match relevance order.

    Maps HTTP status codes to domain error codes:
    403 → RATE_LIMITED, 404 → NOT_FOUND, network errors → NETWORK_ERROR.
    """
    params = {"q": search_query, "per_page": per_page, **(extra_params or {})}
    try:
        resp = await client.get(GITHUB_SEARCH_URL, params=params)
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


def deduplicate_results(all_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate raw API items by html_url, keeping the first occurrence."""
    seen_urls: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in all_items:
        url = item.get("html_url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique.append(item)
    return unique
