"""
Tests for scripts/anchor_guide_subsections.py -- the one-time (but
idempotent, safe to re-run) retrofit that gives the GUIDE's idless <h3>
sub-headings their own ids, so search results for a specific sub-topic
land on that sub-topic instead of the top of its enclosing section.
"""

from __future__ import annotations

from scripts.anchor_guide_subsections import (
    _heading_text,
    _unique_slug,
    anchor_guide_subsections,
)


class TestHeadingText:
    def test_strips_material_symbols_icon_span(self):
        block = (
            '<h3 class="x"><span class="material-symbols-outlined text-[20px]">'
            "download</span> 1. System Prerequisites &amp; Installation</h3>"
        )
        assert _heading_text(block) == "1. System Prerequisites & Installation"

    def test_plain_heading_no_icon(self):
        block = '<h3 class="x">Navigation</h3>'
        assert _heading_text(block) == "Navigation"

    def test_collapses_whitespace(self):
        block = '<h3 class="x">\n  Multi\n  Line   Heading  \n</h3>'
        assert _heading_text(block) == "Multi Line Heading"


class TestUniqueSlug:
    def test_first_use_returns_base_slug(self):
        used = set()
        assert _unique_slug("Launch the Server", used) == "launch-the-server"

    def test_collision_gets_numeric_suffix(self):
        used = {"launch-the-server"}
        assert _unique_slug("Launch the Server", used) == "launch-the-server-2"

    def test_repeated_collisions_increment(self):
        used = {"launch-the-server", "launch-the-server-2"}
        assert _unique_slug("Launch the Server", used) == "launch-the-server-3"

    def test_used_set_is_mutated(self):
        used = set()
        _unique_slug("Launch the Server", used)
        assert "launch-the-server" in used


class TestAnchorGuideSubsections:
    def _html(self, *headings: str) -> str:
        body = "\n".join(f'<h3 class="x">{h}</h3>' for h in headings)
        return f'<html><body><section id="existing">{body}</section></body></html>'

    def test_adds_ids_to_idless_headings(self):
        html = self._html("First Topic", "Second Topic")
        rewritten, added = anchor_guide_subsections(html)
        assert added == 2
        assert 'id="first-topic"' in rewritten
        assert 'id="second-topic"' in rewritten

    def test_existing_ids_are_left_untouched(self):
        html = '<html><body><h3 id="keep-me" class="x">Already Anchored</h3></body></html>'
        rewritten, added = anchor_guide_subsections(html)
        assert added == 0
        assert rewritten == html

    def test_new_slugs_avoid_colliding_with_existing_page_ids(self):
        html = self._html("Existing")  # slugifies to "existing", already used by the <section>
        rewritten, added = anchor_guide_subsections(html)
        assert added == 1
        assert 'id="existing-2"' in rewritten

    def test_is_idempotent(self):
        html = self._html("First Topic", "Second Topic")
        once, added_once = anchor_guide_subsections(html)
        twice, added_twice = anchor_guide_subsections(once)
        assert added_once == 2
        assert added_twice == 0
        assert once == twice

    def test_real_guide_file_has_no_idless_h3_left(self):
        """Runs against the actual site/index.html, not a fixture --
        confirms the real retrofit already applied is complete and the
        script would find nothing left to do if run again."""
        from scripts.anchor_guide_subsections import _INDEX_HTML

        html = _INDEX_HTML.read_text(encoding="utf-8")
        _, added = anchor_guide_subsections(html)
        assert added == 0
