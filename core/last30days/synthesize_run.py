#!/usr/bin/env python3
"""
Deep research driver — multi-source pipeline + LLM synthesis + HTML render.

Merges evidence from three sources before synthesis:
  1. last30days engine — Reddit, X, YouTube, GitHub, HN, Polymarket
  2. Brave Search API — broad web snippets
  3. Full page extraction — readable content from top results
  4. Academic search — Semantic Scholar papers (optional)

The LLM sees all evidence, deduplicates, and writes an analytical brief.
"""

from __future__ import annotations

import html as html_lib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))

from lib import env, html_render, pipeline, render  # noqa: E402

_EVIDENCE_RE = re.compile(
    r"<!-- EVIDENCE FOR SYNTHESIS:.*?-->(.*?)<!-- END EVIDENCE FOR SYNTHESIS -->",
    re.DOTALL,
)

_MAX_SOCIAL_CHARS = 16000
_MAX_WEB_CHARS = 8000
_MAX_PAGE_CHARS = 4000
_LLM_TIMEOUT = 120
_FETCH_TIMEOUT = 10

_SYNTH_SYSTEM = """You are an expert research analyst. You receive evidence from multiple sources:
1. SOCIAL/COMMUNITY EVIDENCE — ranked findings from Reddit, X, YouTube, GitHub, HackerNews, Polymarket (what people are actually saying and doing)
2. WEB SEARCH RESULTS — snippets from broad web search
3. FULL PAGE CONTENT — readable text extracted from the most relevant pages
4. ACADEMIC PAPERS — peer-reviewed research from Semantic Scholar (when available)

Your job is to synthesize ALL sources into a single analytical brief richer than any source alone. Draw connections between what the community is discussing and what authoritative/academic sources confirm or contradict.

VOICE CONTRACT (non-negotiable):
1. The first line of the body must be exactly "What I learned:" on its own line.
2. Write 4-8 analytical paragraphs. Each paragraph:
   - Leads with a bolded key insight (**bold**)
   - Draws connections between sources (community + authoritative + academic)
   - Includes inline source tags like [reddit], [hackernews], [github], [x], [grounding], [arxiv], [paper]
   - Uses inline markdown links [name](url) when citing specific content
3. NO em-dashes or en-dashes. Use " - " (hyphen with spaces).
4. NO trailing "Sources:" list. The engine footer IS the sources list.
5. After the prose, emit "KEY PATTERNS from the research:" followed by 4-6 numbered patterns.
6. Stop after the patterns. No "All agents reported back" footer.
7. Never dump raw evidence clusters or scores. Transform into analytical prose.
8. When community sentiment and authoritative/academic sources disagree, highlight the tension."""


def _extract(pattern: re.Pattern, text: str) -> str:
    m = pattern.search(text)
    return m.group(1).strip() if m else ""


def _llm_config(config: dict) -> tuple[str, str, str] | None:
    """Resolve (base_url, api_key, model) for an OpenAI-compatible provider."""
    override = os.environ.get("L30D_SYNTH_MODEL")
    if config.get("OPENAI_API_KEY"):
        return ("https://api.openai.com/v1", config["OPENAI_API_KEY"],
                override or "gpt-4o-mini")
    if config.get("XAI_API_KEY"):
        return ("https://api.x.ai/v1", config["XAI_API_KEY"],
                override or "grok-3-mini")
    if config.get("OPENROUTER_API_KEY"):
        return ("https://openrouter.ai/api/v1", config["OPENROUTER_API_KEY"],
                override or "openai/gpt-4o-mini")
    return None


def _fetch_url(url: str) -> str | None:
    """Fetch a URL and return readable text content."""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; Tropelex/1.2)",
            "Accept": "text/html,application/xhtml+xml,text/plain",
        })
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
            content_type = resp.headers.get("Content-Type", "")
            if "text" not in content_type and "html" not in content_type:
                return None
            raw = resp.read(200_000).decode("utf-8", errors="replace")
        return _extract_readable_text(raw)
    except Exception:
        return None


def _extract_readable_text(html_content: str) -> str:
    """Extract readable text from HTML. Strips tags, scripts, styles."""
    # Remove script/style blocks
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html_content, flags=re.DOTALL | re.IGNORECASE)
    # Remove HTML comments
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    # Remove tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Decode HTML entities
    text = html_lib.unescape(text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _brave_search(query: str, api_key: str, count: int = 8) -> list[dict]:
    """Call Brave Search API and return result dicts."""
    url = f"https://api.search.brave.com/res/v1/web/search?q={urllib.parse.quote(query)}&count={count}"
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "Accept-Encoding": "identity",
        "X-Subscription-Token": api_key,
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        results = []
        for r in data.get("web", {}).get("results", [])[:count]:
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "description": r.get("description", ""),
            })
        return results
    except Exception as exc:
        sys.stderr.write(f"[synthesize_run] Brave search failed: {exc}\n")
        return []


def _academic_search(query: str, limit: int = 5) -> list[dict]:
    """Search Semantic Scholar for academic papers (free, no key required)."""
    url = (
        f"https://api.semanticscholar.org/graph/v1/paper/search"
        f"?query={urllib.parse.quote(query)}&limit={limit}"
        f"&fields=title,year,abstract,url,citationCount"
    )
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        papers = []
        for p in data.get("data", [])[:limit]:
            papers.append({
                "title": p.get("title", ""),
                "year": p.get("year", ""),
                "abstract": (p.get("abstract") or "")[:500],
                "url": p.get("url", ""),
                "citations": p.get("citationCount", 0),
            })
        return papers
    except Exception as exc:
        sys.stderr.write(f"[synthesize_run] Academic search failed: {exc}\n")
        return []


def _gather_web_research(topic: str, config: dict) -> tuple[list[dict], list[dict], dict[int, str]]:
    """Gather web research: Brave snippets + full page content + academic papers.

    Returns: (brave_results, academic_results, page_contents)
    where page_contents maps result index -> extracted text.
    """
    brave_results: list[dict] = []
    academic_results: list[dict] = []
    page_contents: dict[int, str] = {}

    # Brave Search — check config first, then os.environ directly as fallback
    # (the engine's config loader may not see keys bridged by the runner)
    api_key = config.get("BRAVE_API_KEY") or config.get("BRAVE_SEARCH_API_KEY")
    if not api_key:
        api_key = os.environ.get("BRAVE_API_KEY") or os.environ.get("BRAVE_SEARCH_API_KEY") or ""
    if api_key:
        sys.stderr.write(f"[synthesize_run] Brave search for: {topic}\n")
        brave_results = _brave_search(topic, api_key, count=8)
        sys.stderr.write(f"[synthesize_run] Got {len(brave_results)} web results\n")

        # Full page extraction for top 3 results
        for i, r in enumerate(brave_results[:3]):
            if r["url"]:
                text = _fetch_url(r["url"])
                if text and len(text) > 200:
                    page_contents[i] = text[:_MAX_PAGE_CHARS]
                    sys.stderr.write(f"[synthesize_run] Extracted {len(page_contents[i])} chars from: {r['url'][:60]}\n")
    else:
        sys.stderr.write("[synthesize_run] No Brave API key; skipping web grounding\n")

    # Academic search (free, no key)
    sys.stderr.write(f"[synthesize_run] Academic search for: {topic}\n")
    academic_results = _academic_search(topic, limit=5)
    sys.stderr.write(f"[synthesize_run] Got {len(academic_results)} academic papers\n")

    return brave_results, academic_results, page_contents


def _format_web_evidence(
    brave_results: list[dict],
    academic_results: list[dict],
    page_contents: dict[int, str],
) -> str:
    """Format all web evidence into a single string for the LLM."""
    parts: list[str] = []

    # Brave Search snippets
    if brave_results:
        parts.append("=== WEB SEARCH RESULTS ===")
        for i, r in enumerate(brave_results):
            parts.append(f"[{i+1}] {r['title']}")
            parts.append(f"    URL: {r['url']}")
            if r['description']:
                parts.append(f"    {r['description'][:300]}")
        parts.append("")

    # Full page content from top results
    if page_contents:
        parts.append("=== FULL PAGE CONTENT (top results) ===")
        for idx, text in sorted(page_contents.items()):
            r = brave_results[idx]
            parts.append(f"--- {r['title']} ({r['url']}) ---")
            parts.append(text)
            parts.append("")

    # Academic papers
    if academic_results:
        parts.append("=== ACADEMIC PAPERS (Semantic Scholar) ===")
        for p in academic_results:
            parts.append(f"[paper] {p['title']} ({p['year']}, {p['citations']} citations)")
            if p['url']:
                parts.append(f"    URL: {p['url']}")
            if p['abstract']:
                parts.append(f"    Abstract: {p['abstract']}")
        parts.append("")

    return "\n".join(parts)


def _synthesize(
    topic: str,
    social_evidence: str,
    web_evidence: str,
    config: dict,
) -> str | None:
    """Call an OpenAI-compatible LLM to write the research brief."""
    llm = _llm_config(config)
    if not llm:
        sys.stderr.write("[synthesize_run] No LLM key configured; emitting sparse HTML\n")
        return None
    base_url, api_key, model = llm

    user = f"TOPIC: {topic}\n\n"

    if social_evidence:
        user += (
            "=== SOCIAL/COMMUNITY EVIDENCE (Reddit, X, YouTube, GitHub, HN, Polymarket) ===\n"
            f"{social_evidence[:_MAX_SOCIAL_CHARS]}\n\n"
        )

    if web_evidence:
        user += f"{web_evidence[:_MAX_WEB_CHARS]}\n\n"

    user += "Synthesize all sources into an analytical brief now."

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYNTH_SYSTEM},
            {"role": "user", "content": user},
        ],
        "temperature": 0.4,
    }
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_LLM_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
        text = data["choices"][0]["message"]["content"].strip()
        if text:
            sys.stderr.write(f"[synthesize_run] Synthesis written via {model} ({len(text)} chars)\n")
            return text
        return None
    except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError, TimeoutError) as exc:
        sys.stderr.write(f"[synthesize_run] LLM synthesis failed: {exc}\n")
        return None


def run(topic: str, depth: str = "default") -> str:
    """Run the full deep-research pipeline and return final HTML."""
    config = env.get_config()
    report = pipeline.run(
        topic=topic,
        config=config,
        depth=depth,
        requested_sources=None,
        mock=False,
        web_backend="auto",
        lookback_days=30,
    )

    # Extract social/community evidence from last30days engine.
    compact = render.render_compact(report)
    social_evidence = _extract(_EVIDENCE_RE, compact)

    # Gather web research (Brave + page extraction + academic).
    brave_results, academic_results, page_contents = _gather_web_research(topic, config)
    web_evidence = _format_web_evidence(brave_results, academic_results, page_contents)

    synthesis = _synthesize(topic, social_evidence, web_evidence, config) if (social_evidence or web_evidence) else None

    synthesis_md = None
    if synthesis:
        body = synthesis
        cut = body.find("✅ All agents reported back")
        if cut != -1:
            body = body[:cut].rstrip().rstrip("-").rstrip()
        synthesis_md = body

    return html_render.render_html(report, synthesis_md=synthesis_md)


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.stderr.write("usage: synthesize_run.py <topic> [--quick|--deep]\n")
        return 2
    depth = "quick" if "--quick" in sys.argv else "deep" if "--deep" in sys.argv else "default"
    try:
        sys.stdout.write(run(args[0], depth))
        sys.stdout.write("\n")
        return 0
    except Exception as exc:
        sys.stderr.write(f"[synthesize_run] failed: {type(exc).__name__}: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
