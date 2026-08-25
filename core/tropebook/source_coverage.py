"""
Research Source Coverage (wishlist #88).

Per-project view of which sources actually contribute useful citations vs.
noise. Classification is purely domain-based (classify_source_domain),
computed at read time from each citation's own URL -- not from per-engine
"source" tags. Checked before building: BraveSearch-sourced citations only
ever carry source="brave"/"duckduckgo" (core/tropebook/research.py), and
last30days' richer [reddit]/[github]/[x] platform tags exist only as
unstructured inline text in its raw report markdown, never attached to
individual extracted citations (core/last30days/runner.py's
run_query_and_extract_citations only ever produces title/url, nothing
platform-specific). Domain classification works uniformly across every
citation regardless of which engine produced it, and needs zero new
instrumentation.

"Useful vs noise" is measured by whether a citation has ever been
referenced by one of THIS project's own decisions (Decision.citation_ids,
#82/#91) -- not Citation.access_count, which is declared on the Citation
dataclass but never actually incremented anywhere in this codebase
(checked before building on it too). A citation a real decision cites is a
far more grounded "this mattered" signal than a permanently-zero counter.

Pure functions, no I/O -- same shape as core/prevention_report.py.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

_PLATFORM_DOMAINS: dict[str, str] = {
    "reddit.com": "reddit",
    "github.com": "github",
    "x.com": "x", "twitter.com": "x",
    "youtube.com": "youtube", "youtu.be": "youtube",
    "news.ycombinator.com": "hackernews",
    "stackoverflow.com": "stackoverflow",
    "arxiv.org": "academic", "scholar.google.com": "academic",
    "ncbi.nlm.nih.gov": "academic", "ssrn.com": "academic",
    "medium.com": "blog", "dev.to": "blog", "substack.com": "blog",
}


def classify_source_domain(url: str) -> str:
    """Best-effort platform label from a citation's URL. Falls back to the
    bare registrable domain (not a generic "other" bucket) when it isn't
    one of the recognized platforms -- preserves signal instead of
    collapsing every unrecognized source into one undifferentiated pile.
    """
    if not url:
        return "unknown"
    try:
        netloc = urlparse(url).netloc.lower()
    except ValueError:
        return "unknown"
    netloc = netloc.removeprefix("www.")
    if not netloc:
        return "unknown"
    if netloc in _PLATFORM_DOMAINS:
        return _PLATFORM_DOMAINS[netloc]
    for domain, label in _PLATFORM_DOMAINS.items():
        if netloc.endswith("." + domain):
            return label
    return netloc


def compute_source_coverage(
    citations: list[dict[str, Any]],
    useful_ids: set[str],
    disabled_sources: set[str] | None = None,
) -> dict[str, Any]:
    """citations: Citation.to_dict(id=...)-shaped dicts (must carry 'id'
    and 'url'). useful_ids: citation ids referenced by at least one of this
    project's own decisions.

    Returns per-source {count, useful_count, value_rate, disabled}, sorted
    by count descending, plus an overall summary. Malformed citation
    entries are skipped rather than raising -- this reads across a
    project's whole citation pool, not internal data with a fully
    guaranteed shape.
    """
    disabled_sources = disabled_sources or set()
    by_source: dict[str, dict[str, int]] = {}
    for c in citations:
        if not isinstance(c, dict):
            continue
        source = classify_source_domain(c.get("url", ""))
        bucket = by_source.setdefault(source, {"count": 0, "useful_count": 0})
        bucket["count"] += 1
        if c.get("id") in useful_ids:
            bucket["useful_count"] += 1

    sources = []
    for source, stats in by_source.items():
        value_rate = round(stats["useful_count"] / stats["count"], 3) if stats["count"] else 0.0
        sources.append({
            "source": source,
            "count": stats["count"],
            "useful_count": stats["useful_count"],
            "value_rate": value_rate,
            "disabled": source in disabled_sources,
        })
    sources.sort(key=lambda s: s["count"], reverse=True)

    return {
        "sources": sources,
        "total_citations": len(citations),
        "total_useful": sum(s["useful_count"] for s in sources),
    }
