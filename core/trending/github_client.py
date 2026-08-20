"""
GitHub Search client for Trending — a single sorted-by-stars call over
recently-pushed repos, standing in for github.com/trending's algorithm
(which isn't exposed by any GitHub API).

Discovery uses `pushed:>{cutoff}` rather than `created:>{cutoff}`: a
5-year-old repo that just shipped something can be genuinely trending,
while a repo created today with one star isn't. `pushed:>` also
naturally excludes abandoned repos from the result set.
"""

from __future__ import annotations

import logging
import warnings
from datetime import datetime, timedelta, timezone
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
from core.reposeek.models import RepoResult
from core.result import Err, Ok, Result

logger = logging.getLogger("trending.github_client")

WINDOW_DAYS = {"today": 1, "week": 7, "month": 30}
_MAX_TOPICS = 4


def window_cutoff(window: str) -> str:
    """Return the `pushed:>` cutoff date (YYYY-MM-DD) for a window key."""
    days = WINDOW_DAYS.get(window, WINDOW_DAYS["week"])
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return cutoff.strftime("%Y-%m-%d")


def build_query(language: str | None, topics: list[str], window: str) -> str:
    """Build the single GitHub search query string for a trending pull."""
    parts = [f"pushed:>{window_cutoff(window)}"]
    if language:
        parts.append(f"language:{language}")
    for topic in topics[:_MAX_TOPICS]:
        parts.append(f"topic:{topic}")
    return " ".join(parts)


async def search_trending(
    language: str | None,
    topics: list[str],
    window: str,
    limit: int = 25,
) -> Result[list[RepoResult], Err]:
    """Search GitHub for repos matching the trending proxy query, sorted by
    stars descending. Returns Ok(list[RepoResult]) on success, Err on
    failure. Not deduplicated across multiple queries (only one query is
    issued), but still runs raw items through deduplicate_results for
    consistency with reposeek's client and defense against duplicate
    entries GitHub's own pagination has been known to return."""
    token = get_token()
    if not token:
        warnings.warn(
            "No GITHUB_TOKEN or GH_TOKEN set — using unauthenticated requests (60 req/hr limit)",
            stacklevel=2,
        )

    query = build_query(language, topics, window)
    headers = auth_headers(token)

    async with httpx.AsyncClient(headers=headers, timeout=DEFAULT_TIMEOUT) as client:
        result = await fetch_search_page(
            client, query, per_page=limit, extra_params={"sort": "stars", "order": "desc"}
        )

    if isinstance(result, Err):
        return result

    unique_items: list[dict[str, Any]] = deduplicate_results(result.value)
    repo_results = [parse_item(item) for item in unique_items[:limit]]
    return Ok(value=repo_results)
