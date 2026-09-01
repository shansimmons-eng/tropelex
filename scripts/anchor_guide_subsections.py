#!/usr/bin/env python3
"""
Retrofit ids onto the GUIDE's (site/index.html) idless <h3> sub-headings.

Why this exists: core/docs_search.py's _SectionParser already resolves a
heading's own id, or falls back to its nearest ancestor's, when building
the search index. That works for the GUIDE's top-level sections (each
wrapped in <section id="...">) but not for sub-topics *within* a
section -- those are plain <h3> tags with no id of their own, so several
genuinely distinct topics (e.g. "1. System Prerequisites & Installation",
"2. Launch the Tropelex Server", ... under "Getting Started") all
resolve to the same coarse /guide#getting-started anchor. A search
result for one specific sub-topic can only ever land at the top of the
whole section it happens to live in.

Idempotent: an <h3> that already has an id is left untouched, so this is
safe to re-run after new idless headings are added to the page later.

Usage:
    python3 scripts/anchor_guide_subsections.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.docs_search import _slugify

_INDEX_HTML = Path(__file__).resolve().parent.parent / "site" / "index.html"

_H3_RE = re.compile(r"<h3\b[^>]*>.*?</h3>", re.DOTALL)
_ID_ATTR_RE = re.compile(r'\bid="([^"]*)"')
_MATERIAL_SYMBOLS_SPAN_RE = re.compile(
    r'<span class="material-symbols-outlined[^"]*"[^>]*>.*?</span>', re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")


def _heading_text(h3_block: str) -> str:
    """Inner text of an <h3>...</h3> block, with any Material Symbols
    icon span (icon glyph rendered via ligature text, not a word) and
    all other tags stripped."""
    inner = h3_block.split(">", 1)[1].rsplit("<", 1)[0]
    inner = _MATERIAL_SYMBOLS_SPAN_RE.sub("", inner)
    inner = _TAG_RE.sub("", inner)
    inner = inner.replace("&amp;", "&").replace("&#x27;", "'")
    return " ".join(inner.split())


def _unique_slug(text: str, used: set[str]) -> str:
    base = _slugify(text) or "section"
    slug = base
    suffix = 2
    while slug in used:
        slug = f"{base}-{suffix}"
        suffix += 1
    used.add(slug)
    return slug


def anchor_guide_subsections(html: str) -> tuple[str, int]:
    """Returns (rewritten_html, count_of_ids_added)."""
    used_ids = set(_ID_ATTR_RE.findall(html))

    pieces: list[str] = []
    last_end = 0
    added = 0
    for match in _H3_RE.finditer(html):
        block = match.group(0)
        pieces.append(html[last_end:match.start()])
        last_end = match.end()

        if "id=" in block[: block.index(">") + 1]:
            pieces.append(block)
            continue

        text = _heading_text(block)
        if not text:
            pieces.append(block)
            continue

        slug = _unique_slug(text, used_ids)
        rewritten = block.replace("<h3 ", f'<h3 id="{slug}" ', 1)
        pieces.append(rewritten)
        added += 1

    pieces.append(html[last_end:])
    return "".join(pieces), added


def main() -> int:
    html = _INDEX_HTML.read_text(encoding="utf-8")
    rewritten, added = anchor_guide_subsections(html)
    if added:
        _INDEX_HTML.write_text(rewritten, encoding="utf-8")
    print(f"Added {added} new heading id(s) to {_INDEX_HTML}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
