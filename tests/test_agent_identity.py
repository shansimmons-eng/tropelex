"""Tests for core.agent_identity.normalize_agent_name."""

from __future__ import annotations

import pytest

from core.agent_identity import normalize_agent_name


class TestEmptyAndMissing:
    @pytest.mark.parametrize("raw", [None, "", "   "])
    def test_falls_back_to_unspecified(self, raw):
        assert normalize_agent_name(raw) == "unspecified"


class TestClaudeAliases:
    @pytest.mark.parametrize(
        "raw",
        ["Claude", "claude", " CLAUDE ", "claude-sonnet-5", "Claude Code", "claude desktop", "  claude   code  "],
    )
    def test_collapses_to_canonical_claude(self, raw):
        assert normalize_agent_name(raw) == "Claude"


class TestOtherKnownAgents:
    @pytest.mark.parametrize("raw,expected", [
        ("Cursor", "Cursor"),
        ("cursor", "Cursor"),
        ("Gemini", "Gemini"),
        ("gemini", "Gemini"),
        ("OpenCode", "OpenCode"),
        ("opencode", "OpenCode"),
    ])
    def test_collapses_to_canonical(self, raw, expected):
        assert normalize_agent_name(raw) == expected


class TestUnknownAgentsPassThrough:
    def test_unknown_name_trimmed_but_case_preserved(self):
        assert normalize_agent_name("  Big Pickle  ") == "Big Pickle"

    def test_unknown_model_variant_not_fuzzy_matched(self):
        # Must NOT be silently merged into "Gemini" -- no confirmed alias,
        # so two potentially-different agents stay distinct.
        assert normalize_agent_name("gemini-3.6-flash") == "gemini-3.6-flash"

    def test_internal_whitespace_not_collapsed_for_unknown_names(self):
        assert normalize_agent_name("My   Bot") == "My   Bot"
