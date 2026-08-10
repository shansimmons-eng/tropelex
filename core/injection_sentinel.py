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

import re

# Canonical home for these patterns -- core/agent_audit/scanner.py imports
# from here instead of keeping its own copy (same "shared module beats two
# copies" move as core/audit.py did for the write-time hash chain).
INJECTION_MARKERS: list[tuple[str, re.Pattern]] = [
    ("ignore_instructions", re.compile(r"(?i)ignore (all )?(previous|prior|above) instructions")),
    ("disregard_system_prompt", re.compile(r"(?i)disregard (your|the) (system prompt|instructions|guidelines)")),
    ("disable_safety", re.compile(r"(?i)disable (safety|security|guardrails)")),
    ("silence_the_user", re.compile(r"(?i)do not (tell|inform|mention this to) the user")),
    ("exfiltration", re.compile(r"(?i)exfiltrat")),
]

_SNIPPET_MAX_LEN = 160


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

    findings: list[dict[str, str]] = []
    for line in text.splitlines():
        for name, pattern in INJECTION_MARKERS:
            if pattern.search(line):
                findings.append({
                    "pattern": name,
                    "severity": "high",
                    "snippet": line.strip()[:_SNIPPET_MAX_LEN],
                })
    return findings
