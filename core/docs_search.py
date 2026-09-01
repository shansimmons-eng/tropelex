"""
Documentation search (dashboard sidebar search widget, "Documentation"
category) -- keyword search over the GUIDE, FAQ, Getting Started, API
Reference, and README, independent of the project-scoped search
core/search_router.py does over decisions/sessions/patterns.

Reads the canonical source files directly (site/*.html, README.md at the
repo root) rather than the locally-served core/tropebook/web/static/
mirrors -- the mirror files exist only because their internal nav links
are rewritten for local routing (see scripts/sync_local_docs.py), the
actual text content is identical, and reading the canonical copy means
this index can never itself go stale relative to what's deployed.

No markdown/HTML library dependency: README.md is a flat "split on
heading lines" pass, and the HTML pages use the stdlib html.parser --
both are simple enough that a real dependency would be overkill, and it
keeps this consistent with the rest of the codebase's "avoid unnecessary
dependencies" posture (core/driftbench, core/reward_hacking, etc. are
all stdlib-only too).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from core.text_search import keyword_score, tokenize

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SITE_DIR = _REPO_ROOT / "site"

# (site filename, display source label, local route the search widget should link to)
_HTML_SOURCES = (
    ("index.html", "Guide", "/guide"),
    ("faq.html", "FAQ", "/faq"),
    ("getting-started.html", "Getting Started", "/getting-started"),
    ("api-reference.html", "API Reference", "/api-reference"),
)

_README_URL = "https://github.com/shansimmons-eng/tropelex"

_VOID_TAGS = {
    "br", "img", "input", "hr", "meta", "link", "area", "base",
    "col", "embed", "source", "track", "wbr",
}
_HEADING_TAGS = {"h1", "h2", "h3", "h4"}


@dataclass(frozen=True)
class DocEntry:
    """One searchable section: a heading plus the text that follows it,
    up to the next heading. `anchor` is None for a section whose heading
    (and every ancestor) has no id -- still indexed for search, just not
    deep-linkable, so the result links to the page without a fragment."""
    source: str
    title: str
    anchor: str | None
    url: str
    text: str


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug


class _SectionParser(HTMLParser):
    """Streaming HTML walk producing an ordered list of heading/text
    blocks. Doesn't build a DOM tree -- a heading "owns" every text block
    between itself and the next heading (any level), which is simple,
    robust to these pages' varied nesting, and good enough for search
    snippets without needing a real outline algorithm.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._stack: list[dict[str, Any]] = []
        self._skip_count = 0
        self._current_heading: dict[str, Any] | None = None
        self.blocks: list[dict[str, Any]] = []

    def _nearest_id(self) -> str | None:
        for frame in reversed(self._stack):
            if frame["id"]:
                return frame["id"]
        return None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _VOID_TAGS:
            return
        attrs_d = dict(attrs)
        id_ = attrs_d.get("id")
        is_skip = tag in ("script", "style") or (
            tag == "span" and "material-symbols" in (attrs_d.get("class") or "")
        )
        self._stack.append({"tag": tag, "id": id_, "skip": is_skip})
        if is_skip:
            self._skip_count += 1
        if tag in _HEADING_TAGS:
            anchor = id_ or self._nearest_id()
            self._current_heading = {
                "kind": "heading", "level": int(tag[1]), "id": anchor, "text": "",
            }

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        pass  # self-closed void-ish tags (<br/>, <img/>) -- nothing to track

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID_TAGS:
            return
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i]["tag"] == tag:
                popped = self._stack.pop(i)
                if popped["skip"]:
                    self._skip_count = max(0, self._skip_count - 1)
                break
        if tag in _HEADING_TAGS and self._current_heading is not None:
            self.blocks.append(self._current_heading)
            self._current_heading = None

    def handle_data(self, data: str) -> None:
        if self._skip_count > 0:
            return
        text = data.strip()
        if not text:
            return
        if self._current_heading is not None:
            self._current_heading["text"] = (self._current_heading["text"] + " " + text).strip()
        elif self.blocks and self.blocks[-1]["kind"] == "text":
            self.blocks[-1]["text"] += " " + text
        else:
            self.blocks.append({"kind": "text", "text": text})


def _blocks_to_entries(blocks: list[dict[str, Any]], source: str, base_url: str) -> list[DocEntry]:
    entries: list[DocEntry] = []
    current_heading: dict[str, Any] | None = None
    current_text: list[str] = []

    def _flush() -> None:
        if current_heading is None:
            return
        title = current_heading["text"].strip()
        if not title:
            return
        anchor = current_heading["id"]
        url = f"{base_url}#{anchor}" if anchor else base_url
        entries.append(DocEntry(
            source=source, title=title, anchor=anchor, url=url,
            text=" ".join(current_text).strip(),
        ))

    for block in blocks:
        if block["kind"] == "heading":
            _flush()
            current_heading = block
            current_text = []
        else:
            current_text.append(block["text"])
    _flush()
    return entries


def _parse_html_page(path: Path, source: str, base_url: str) -> list[DocEntry]:
    parser = _SectionParser()
    parser.feed(path.read_text(encoding="utf-8"))
    return _blocks_to_entries(parser.blocks, source, base_url)


_HEADING_LINE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


def _parse_readme(path: Path) -> list[DocEntry]:
    """Flat heading-split, no markdown parser -- README.md's own
    structure (headings starting a line with 1-6 #s) is simple enough
    that a real dependency would be overkill."""
    content = path.read_text(encoding="utf-8")
    matches = list(_HEADING_LINE.finditer(content))
    entries: list[DocEntry] = []
    for i, m in enumerate(matches):
        title = m.group(2).strip()
        if not title:
            continue
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        body = content[start:end].strip()
        anchor = _slugify(title)
        entries.append(DocEntry(
            source="README", title=title, anchor=anchor,
            url=f"{_README_URL}#{anchor}", text=body,
        ))
    return entries


def build_docs_index() -> list[DocEntry]:
    """Parse every documentation source into a flat list of searchable
    entries. Call once and cache -- these files only change on a deploy,
    which restarts the process anyway (see search_docs_router for the
    module-level cache)."""
    entries: list[DocEntry] = []
    for filename, source, base_url in _HTML_SOURCES:
        path = _SITE_DIR / filename
        if not path.exists():
            continue
        try:
            entries.extend(_parse_html_page(path, source, base_url))
        except Exception:
            # A malformed page must not break the whole index -- skip it,
            # same "degrade, don't crash" posture as every other defensive
            # loop in this codebase.
            continue

    readme_path = _REPO_ROOT / "README.md"
    if readme_path.exists():
        try:
            entries.extend(_parse_readme(readme_path))
        except Exception:
            pass

    return entries


def search_docs(index: list[DocEntry], query: str, limit: int = 10, min_score: float = 0.1) -> list[dict[str, Any]]:
    """Rank index entries by keyword overlap against title (weighted
    higher) and body text."""
    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    scored: list[tuple[float, DocEntry]] = []
    for entry in index:
        score = max(
            keyword_score(query_tokens, entry.title),
            keyword_score(query_tokens, entry.text) * 0.6,
        )
        if score >= min_score:
            scored.append((score, entry))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [
        {
            "source": entry.source,
            "title": entry.title,
            "url": entry.url,
            "snippet": entry.text[:200],
            "score": round(score, 3),
        }
        for score, entry in scored[:limit]
    ]
