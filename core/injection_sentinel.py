"""
Injection Sentinel — screens externally-sourced content for injected
instructions before it's written into memory a future agent session will
read back as trusted context (wishlist #40).

Distinct from Agent Surface Audit (core/agent_audit/), which scans the
harness's own config; this screens content flowing *through* the harness
(web-research summaries, Slack/Emacs-captured decision text). Pure
functions only — flag, don't block: a hit attaches a `content_flags`
marker to the stored item, it never rejects the write.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# Canonical home for these patterns -- core/agent_audit/scanner.py imports
# from here instead of keeping its own copy (same "shared module beats two
# copies" move as core/audit.py did for the write-time hash chain). Every
# pattern here is deliberately narrow (specific trailing structure, not a
# bare keyword) -- P7 (gap E) added a handful of new high-signal phrasings
# and widened two existing ones to close small, real gaps (verified: e.g.
# "disable all safety" didn't match "disable (safety|security|guardrails)"
# since "all" sat between the two words), while keeping every marker a
# genuine attack phrase rather than a false-positive magnet.
INJECTION_MARKERS: list[tuple[str, re.Pattern]] = [
    ("ignore_instructions", re.compile(r"(?i)ignore (all )?(previous|prior|above) instructions")),
    ("disregard_system_prompt", re.compile(r"(?i)disregard (your|the) (system prompt|instructions|guidelines)")),
    ("disable_safety", re.compile(r"(?i)disable (all )?(safety|security|guardrails)")),
    ("silence_the_user", re.compile(r"(?i)do not (tell|inform|mention (this|it) to) (the user|anyone)")),
    ("exfiltration", re.compile(r"(?i)exfiltrat")),
    ("start_over_new_instructions", re.compile(r"(?i)start over with (new|different) instructions")),
    ("override_rules", re.compile(r"(?i)override (your|the) (rules|guidelines|restrictions|instructions)")),
    ("roleplay_no_restrictions", re.compile(r"(?i)act as if you (are|were) .{0,40}(no|without any) (restrictions|rules|filters|guardrails)")),
    ("data_uri_executable_stub", re.compile(r"(?i)data:(text/html|application/(x-)?javascript)\s*[;,]")),
]

_SNIPPET_MAX_LEN = 160
_CONFIG_PATH = Path(__file__).resolve().parent.parent / "memory" / "config" / "injection_markers.json"


def _load_additional_markers() -> list[tuple[str, re.Pattern]]:
    """Operator-configurable additions to INJECTION_MARKERS (wishlist
    #73-2), loaded from memory/config/injection_markers.json if present.

    Additive only by construction: this only ever returns *new* entries
    appended after the base list in scan_content, so a malformed or
    missing config degrades to exactly the base list -- it can never
    remove or shadow a base-list pattern. Re-read on every scan (not
    cached at import time) so config edits take effect without a restart;
    call volume here (decision/goal/session writes) is nowhere near hot
    enough for that to matter.
    """
    if not _CONFIG_PATH.exists():
        return []
    try:
        data = json.loads(_CONFIG_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, dict):
        return []

    extra: list[tuple[str, re.Pattern]] = []
    for entry in data.get("additional_markers", []):
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        pattern_str = entry.get("pattern")
        if not isinstance(name, str) or not name or not isinstance(pattern_str, str) or not pattern_str:
            continue
        try:
            extra.append((name, re.compile(pattern_str, re.IGNORECASE)))
        except re.error:
            continue
    return extra


def scan_content(text: str) -> list[dict[str, str]]:
    """Scan freeform ingested text for injection markers. Pure function.

    Returns a list of {"pattern", "severity", "snippet"} dicts, one per
    matching line per marker -- empty list for clean text. All matches are
    "high" severity: the marker list only contains genuinely high-signal
    phrasing (same as agent_audit's existing behavior for these same
    patterns), not an invented lower tier with no real signal behind it.
    """
    if not text:
        return []

    markers = INJECTION_MARKERS + _load_additional_markers()
    findings: list[dict[str, str]] = []
    for line in text.splitlines():
        for name, pattern in markers:
            if pattern.search(line):
                findings.append({
                    "pattern": name,
                    "severity": "high",
                    "snippet": line.strip()[:_SNIPPET_MAX_LEN],
                })
    return findings
