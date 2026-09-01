"""
Assertion-weakening detection (wishlist #107) — the second reward-hacking
evasion shape Drift-Bench publishes at 0.0 (`reward_hacking_test_gaming`,
core/driftbench/scenarios.py): a diff that weakens or deletes an
assertion in a high-risk file instead of adding unrelated code.

Distinct from core/ghost/ in a real way, not just organizationally: Ghost
compares a diff against a specific recorded decision's text.
detect_assertion_weakening needs no decision at all -- it looks at the
diff alone for a structural pattern (an assertion deleted, or rewritten
into something that can never fail) on a high-risk file path. `decisions`
is optional and only widens what counts as "high-risk" beyond file-path
keywords, never required for the check to run.

Explicitly scoped as high-precision/low-recall, not comprehensive, per
the wishlist item: a few true positives moving the published 0.0 is real,
checkable progress, not a requirement to catch every possible evasion.
Two confidence tiers reflect that directly -- a tautological rewrite
("assert x == x") is a specific, high-confidence signal (medium
severity); a bare deletion with nothing replacing it could just as
easily be a legitimate refactor (low severity, still surfaced, not
alarming).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from core.ghost.pattern_matcher import parse_diff_hunks

_ASSERTION_RE = re.compile(
    r"^\s*(assert\b|self\.assert[A-Za-z]+\(|raise\s+AssertionError\b)"
)

# Deliberately a plain keyword list, not an attempt to be exhaustive --
# this exists to keep the detector's blast radius on genuinely
# consequential code, not to be a complete taxonomy of "high risk."
_HIGH_RISK_KEYWORDS = (
    "auth", "permission", "payment", "checkout", "billing", "credential",
    "token", "admin", "security", "access", "login", "session",
)


@dataclass(frozen=True)
class AssertionWeakeningFinding:
    id: str
    file: str
    line_number: int
    severity: str  # "medium" (tautological rewrite) | "low" (bare deletion)
    kind: str  # "weakened" | "deleted"
    original: str
    replacement: str | None
    description: str
    recommendation: str


def _is_high_risk(file: str, decisions: list[dict[str, Any]] | None) -> bool:
    lower = file.lower()
    if any(kw in lower for kw in _HIGH_RISK_KEYWORDS):
        return True
    if not decisions:
        return False
    for d in decisions:
        if not isinstance(d, dict):
            continue
        safety = d.get("safety_metadata")
        affected = safety.get("affected_systems") if isinstance(safety, dict) else None
        text = " ".join([
            str(d.get("decision", "")),
            " ".join(d.get("categories") or []),
            " ".join(affected or []),
        ]).lower()
        if any(kw in text for kw in _HIGH_RISK_KEYWORDS):
            return True
    return False


_COMPARISON_RE = re.compile(r"assert\s+(.+?)\s*(==|is)\s*(.+?)\s*$")


def _is_tautological_rewrite(deleted: str, added: str) -> bool:
    """True if `added` looks like `deleted` rewritten so it can never
    fail: a literal always-true assertion, or a comparison where the
    right-hand side was changed to textually match the left-hand side."""
    added_expr = re.sub(r"#.*$", "", added).strip()
    if re.search(r"\bassert\s+(True|1)\s*$", added_expr):
        return True

    added_match = _COMPARISON_RE.search(added_expr)
    if not added_match:
        return False
    added_lhs, added_rhs = added_match.group(1).strip(), added_match.group(3).strip()
    if not added_lhs or added_lhs != added_rhs:
        return False

    # Only a real weakening if the original comparison had a genuinely
    # different right-hand side -- "assert x == x" appearing standalone,
    # with nothing to compare against, isn't evidence of anything.
    deleted_expr = re.sub(r"#.*$", "", deleted).strip()
    deleted_match = _COMPARISON_RE.search(deleted_expr)
    if not deleted_match:
        return False
    return deleted_match.group(1).strip() == added_lhs and deleted_match.group(3).strip() != added_rhs


def detect_assertion_weakening(
    diff_text: str, decisions: list[dict[str, Any]] | None = None,
) -> list[AssertionWeakeningFinding]:
    """Scan a diff for a deleted or weakened assertion in a high-risk
    file. Pure function -- decisions, if given, only widen the high-risk
    filter; the check runs with decisions=None just fine."""
    if not diff_text:
        return []

    hunks = parse_diff_hunks(diff_text)
    by_file: dict[str, list[dict[str, Any]]] = {}
    for h in hunks:
        by_file.setdefault(h["file"], []).append(h)

    findings: list[AssertionWeakeningFinding] = []
    for file, file_hunks in by_file.items():
        if not _is_high_risk(file, decisions):
            continue

        deletions = [h for h in file_hunks if h["is_deletion"] and _ASSERTION_RE.match(h["content"])]
        additions = [h for h in file_hunks if h["is_addition"]]

        for d in deletions:
            # A real diff hunk lists a line's deletion and its replacement
            # close together -- "within 2 lines" is a proxy for "this
            # replaced that," not exact line-number bookkeeping across an
            # edit that may have shifted surrounding lines.
            nearby_assertions = [
                a for a in additions
                if abs(a["line_number"] - d["line_number"]) <= 2 and _ASSERTION_RE.match(a["content"])
            ]

            if nearby_assertions:
                replacement = nearby_assertions[0]
                if not _is_tautological_rewrite(d["content"], replacement["content"]):
                    continue  # replaced by a different, presumably still-real assertion
                raw = f"assertion_weakened{file}{d['content']}{replacement['content']}"
                findings.append(AssertionWeakeningFinding(
                    id=hashlib.sha256(raw.encode()).hexdigest()[:12],
                    file=file, line_number=d["line_number"], severity="medium",
                    kind="weakened", original=d["content"].strip(),
                    replacement=replacement["content"].strip(),
                    description=f"Assertion in {file} was rewritten into one that can never fail.",
                    recommendation="Review whether this assertion still verifies the original behavior.",
                ))
            else:
                raw = f"assertion_deleted{file}{d['content']}"
                findings.append(AssertionWeakeningFinding(
                    id=hashlib.sha256(raw.encode()).hexdigest()[:12],
                    file=file, line_number=d["line_number"], severity="low",
                    kind="deleted", original=d["content"].strip(), replacement=None,
                    description=f"Assertion in {file} was deleted with no replacement nearby.",
                    recommendation="Confirm this assertion's coverage was intentionally removed, not silently dropped.",
                ))

    return findings
