"""Shared agent-identity normalization for Tropelex.

Every subsystem that tags a record with an `agent_name`/`agent` string
(Agent Skills, Session Replay, Friction Mining, Decision Market, Personas,
Slack Capture) should route through normalize_agent_name() at write time
instead of reimplementing its own `.strip() or "unspecified"` guard.
"""

from __future__ import annotations


def _fold(s: str) -> str:
    """Case/whitespace-insensitive key for alias lookup."""
    return " ".join(s.strip().lower().split())


# Canonical display name -> known spelling/casing variants. Populated
# conservatively from this repo's own docs/integrations plus the reported
# "claude-sonnet-5" vs "Claude" bug, not guessed or fuzzy-matched. Extend
# only with confirmed real values.
_AGENT_ALIASES: dict[str, tuple[str, ...]] = {
    "Claude": ("claude", "claude code", "claude desktop", "claude-sonnet-5"),
    "Cursor": ("cursor",),
    "Gemini": ("gemini",),
    "OpenCode": ("opencode",),
}


def _build_lookup() -> dict[str, str]:
    lookup: dict[str, str] = {}
    for canonical, aliases in _AGENT_ALIASES.items():
        lookup[_fold(canonical)] = canonical
        for alias in aliases:
            lookup[_fold(alias)] = canonical
    return lookup


_AGENT_ALIAS_LOOKUP = _build_lookup()


def normalize_agent_name(raw: str | None) -> str:
    """Canonicalize a freeform agent-name string for storage/lookup.

    1. Trim; empty/None -> "unspecified" (existing convention, unchanged).
    2. Case/whitespace-insensitive lookup against the known-alias table so
       spelling/casing variants of the SAME agent collapse to one name.
    3. Anything not in the table is returned trimmed, as-authored -- no
       fuzzy/heuristic matching, so two genuinely different unknown agents
       never get silently merged.
    """
    cleaned = (raw or "").strip()
    if not cleaned:
        return "unspecified"
    return _AGENT_ALIAS_LOOKUP.get(_fold(cleaned), cleaned)
