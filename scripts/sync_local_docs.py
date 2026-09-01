#!/usr/bin/env python3
"""
Sync the deployed docs (site/*.html, GitHub Pages) into the local,
FastAPI-served mirrors (core/tropebook/web/static/*.html).

Why a sync step exists at all, instead of the local routes just reading
site/*.html directly: the local pages carry a few deliberate differences
from the deployed ones -- internal nav links point at extension-less
local routes (/guide, /faq, ...) instead of the static site's own
*.html filenames, asset paths are absolute (/images/...) since these
pages are served from route paths rather than a site/ subdirectory, and
the header nav gets a "Dashboard" link + a "Back to Dashboard" action
that only make sense when there's a live instance to go back to.

Run this whenever site/*.html changes (core/triggers/checks.py's
check_local_docs_in_sync warns on push if you forget):

    python3 scripts/sync_local_docs.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SITE_DIR = _REPO_ROOT / "site"
_STATIC_DIR = _REPO_ROOT / "core" / "tropebook" / "web" / "static"

# (site filename, local mirror filename)
_PAGES = (
    ("index.html", "docs.html"),
    ("faq.html", "faq.html"),
    ("getting-started.html", "getting_started.html"),
    ("api-reference.html", "api_ref.html"),
)

_NAV_LINK_REWRITES = (
    ('href="index.html"', 'href="/guide"'),
    ('href="faq.html"', 'href="/faq"'),
    ('href="getting-started.html"', 'href="/getting-started"'),
    ('href="api-reference.html"', 'href="/api-reference"'),
)

_ASSET_PATH_REWRITES = (
    ('src="images/', 'src="/images/'),
    ('href="images/', 'href="/images/'),
    # search-highlight.js is copied alongside the synced HTML (see main()
    # below) into core/tropebook/web/static/, which the app already
    # serves at /static via StaticFiles -- reusing that existing mount
    # rather than adding a new route for one file.
    ('src="search-highlight.js"', 'src="/static/search-highlight.js"'),
)

# The image-logo pages (index.html, faq.html, getting-started.html) share
# this exact logo <a> markup; the text-logo page (api-reference.html) has
# its own. Both get: href -> "/" (Dashboard, not /guide), title -> "Go to
# Dashboard", and a "Dashboard" nav link inserted as the first nav item.
_IMAGE_LOGO_RE = re.compile(
    r'(<a class="flex items-center gap-2\.5" href=")/guide(" title=")Tropelex Documentation(">)',
)
_TEXT_LOGO_RE = re.compile(
    r'(<a class="font-display-xl[^"]*" href=")/guide(">)',
)
_NAV_OPEN_RE = re.compile(r'(<nav class="hidden md:flex gap-6"(?: aria-label="Main navigation")?>)')
_DASHBOARD_LINK = (
    '<a class="nav-link text-on-surface-variant font-medium hover:text-primary '
    'transition-colors text-sm flex items-center gap-1.5" href="/">'
    '<span class="material-symbols-outlined text-[16px]">dashboard</span> Dashboard</a>'
)
_GITHUB_LINK_RE = re.compile(
    r'<a class="text-on-surface-variant font-medium hover:text-primary transition-colors '
    r'text-sm hidden md:flex items-center gap-1\.5" href="https://github\.com/shansimmons-eng/tropelex" '
    r'target="_blank" rel="noopener"><span class="material-symbols-outlined text-\[16px\]">code</span> '
    r'View on GitHub</a>',
)
_BACK_TO_DASHBOARD_LINK = (
    '<a class="text-on-surface-variant font-medium hover:text-primary transition-colors text-sm '
    'hidden md:flex items-center gap-1.5" href="/"><span class="material-symbols-outlined '
    'text-[16px]">arrow_back</span> Back to Dashboard</a>'
)

# api-reference.html's "View on GitHub" is a button-styled variant (its
# own template, not the shared nav-link style the other 3 pages use) --
# swapped for the same button style.
_GITHUB_BUTTON_RE = re.compile(
    r'<a class="px-4 py-2 rounded-xl bg-purple-500/15 border border-purple-500/30 text-purple-200 '
    r'text-xs font-semibold hover:bg-purple-500/25 transition-all flex items-center gap-2" '
    r'href="https://github\.com/shansimmons-eng/tropelex" target="_blank" rel="noopener">\s*'
    r'<span class="material-symbols-outlined text-\[16px\]">code</span> View on GitHub\s*</a>',
)
_BACK_TO_DASHBOARD_BUTTON = (
    '<a class="px-4 py-2 rounded-xl bg-purple-500/15 border border-purple-500/30 text-purple-200 '
    'text-xs font-semibold hover:bg-purple-500/25 transition-all flex items-center gap-2" href="/">\n'
    '<span class="material-symbols-outlined text-[16px]">arrow_back</span> Back to Dashboard\n</a>'
)

# api-reference.html only: a link to FastAPI's own auto-generated Swagger
# UI, meaningful only when there's a live instance to query -- not
# present in site/api-reference.html at all, so it can't come from a
# mechanical rewrite; inserted right after the shared FAQ nav link.
_OPENAPI_SPEC_LINK = (
    '<a class="nav-link text-on-surface-variant font-medium hover:text-primary transition-colors '
    'text-sm flex items-center gap-1.5" href="/docs" target="_blank">'
    '<span class="material-symbols-outlined text-[16px]">code</span> OpenAPI Spec</a>'
)
_FAQ_NAV_LINK_RE = re.compile(
    r'(<a class="nav-link text-on-surface-variant font-medium hover:text-primary transition-colors '
    r'text-sm flex items-center gap-1\.5" href="/faq"><span class="material-symbols-outlined '
    r'text-\[16px\]">help</span> FAQ</a>)',
)


def _rewrite_for_local(html: str, *, is_api_reference: bool = False) -> str:
    for old, new in _NAV_LINK_REWRITES:
        html = html.replace(old, new)
    for old, new in _ASSET_PATH_REWRITES:
        html = html.replace(old, new)

    # Logo -> Dashboard (its href was just rewritten to /guide by the
    # nav-link pass above, since its source href is literally index.html;
    # correct it to / for the local, "there's a live app" context).
    html = _IMAGE_LOGO_RE.sub(r"\1/\2Go to Dashboard\3", html)
    html = _TEXT_LOGO_RE.sub(r"\1/\2", html)

    # Insert a Dashboard nav link as the first item, once (avoid
    # double-inserting if this script runs twice on an already-synced file).
    if "Dashboard</a>" not in html:
        html = _NAV_OPEN_RE.sub(lambda m: m.group(1) + "\n" + _DASHBOARD_LINK, html, count=1)

    # The deployed site's "View on GitHub" action isn't useful once
    # you're already looking at a live local instance -- swap it for a
    # way back to the dashboard. Two possible markups depending on page
    # template (plain nav-link vs. api-reference.html's button style).
    html = _GITHUB_LINK_RE.sub(_BACK_TO_DASHBOARD_LINK, html)
    html = _GITHUB_BUTTON_RE.sub(_BACK_TO_DASHBOARD_BUTTON, html)

    if is_api_reference and "OpenAPI Spec</a>" not in html:
        html = _FAQ_NAV_LINK_RE.sub(lambda m: m.group(1) + "\n" + _OPENAPI_SPEC_LINK, html, count=1)

    return html


def main() -> int:
    _STATIC_DIR.mkdir(parents=True, exist_ok=True)
    for site_name, local_name in _PAGES:
        site_path = _SITE_DIR / site_name
        if not site_path.exists():
            print(f"skip: {site_path} not found", file=sys.stderr)
            continue
        local_html = _rewrite_for_local(
            site_path.read_text(encoding="utf-8"),
            is_api_reference=(site_name == "api-reference.html"),
        )
        (_STATIC_DIR / local_name).write_text(local_html, encoding="utf-8")
        print(f"synced {site_name} -> core/tropebook/web/static/{local_name}")

    js_path = _SITE_DIR / "search-highlight.js"
    if js_path.exists():
        (_STATIC_DIR / "search-highlight.js").write_text(
            js_path.read_text(encoding="utf-8"), encoding="utf-8",
        )
        print("synced search-highlight.js -> core/tropebook/web/static/search-highlight.js")
    else:
        print(f"skip: {js_path} not found", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
