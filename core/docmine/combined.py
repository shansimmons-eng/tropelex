"""
Combined Doc Mining + Ghost drift alert (#55).

Doc Mining and Preventive Ghost Checks each independently flag a decision
as drifted — one from its supporting docs, one from a proposed code diff.
Neither knows about the other. When BOTH fire for the *same* decision,
that's a stronger signal than either alone: the code is moving away from
the decision AND the docs describing it haven't caught up either — not
two unrelated, equally-weighted warnings.

This is a pure joining function: no I/O, no new detection logic, just
cross-referencing two detectors' already-computed output by decision_id.
Matches Goal Alignment's (#41) "thin aggregator over existing signals"
shape rather than building parallel detection logic.

Note: joins against Preventive Ghost Checks (core/ghost/preventive.py),
not the post-hoc Ghost Decisions endpoint (core/ghost/detector.py) — the
latter is currently wired with a hardcoded empty diff_data list in
core/ghost/router.py (git-diff integration isn't built yet), so it can
never actually surface anything today. Preventive checks take a real diff
directly, same input shape Doc Mining's scan already needs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2}


@dataclass(frozen=True)
class CombinedAlert:
    """A decision that both Doc Mining and Preventive Ghost Checks flagged."""
    decision_id: str
    decision_text: str
    doc_severity: str
    ghost_severity: str
    combined_severity: str  # always "critical" — stronger than either source alone
    doc_finding_ids: list[str]
    ghost_recommendation: str


def combine_doc_and_ghost_findings(
    doc_findings: list[dict[str, Any]],
    ghost_warnings: list[dict[str, Any]],
) -> list[CombinedAlert]:
    """Join doc_vs_decision findings and ghost warnings on decision_id.

    doc_findings: dicts shaped like DocFinding (core/docmine/__init__.py) —
        only kind == "doc_vs_decision" entries carry a decision_id (in
        claim_b_source); doc_vs_doc findings don't reference a decision at
        all and are ignored here.
    ghost_warnings: dicts shaped like check_diff_for_warnings's output
        (decision_id, decision_text, severity, recommendation, ...).

    Returns one CombinedAlert per decision flagged by both, sorted by
    decision_id for stable output.
    """
    doc_by_decision: dict[str, list[dict[str, Any]]] = {}
    for f in doc_findings:
        if f.get("kind") != "doc_vs_decision":
            continue
        did = f.get("claim_b_source")
        if not did:
            continue
        doc_by_decision.setdefault(did, []).append(f)

    ghost_by_decision: dict[str, dict[str, Any]] = {}
    for w in ghost_warnings:
        did = w.get("decision_id")
        if not did:
            continue
        existing = ghost_by_decision.get(did)
        if existing is None or _SEVERITY_RANK.get(w.get("severity", "low"), 0) > _SEVERITY_RANK.get(
            existing.get("severity", "low"), 0
        ):
            ghost_by_decision[did] = w

    combined: list[CombinedAlert] = []
    for did, docs in sorted(doc_by_decision.items()):
        ghost = ghost_by_decision.get(did)
        if ghost is None:
            continue
        worst_doc = max(docs, key=lambda f: _SEVERITY_RANK.get(f.get("severity", "low"), 0))
        combined.append(CombinedAlert(
            decision_id=did,
            decision_text=ghost.get("decision_text", ""),
            doc_severity=worst_doc.get("severity", "low"),
            ghost_severity=ghost.get("severity", "low"),
            combined_severity="critical",
            doc_finding_ids=[f.get("id") for f in docs if f.get("id")],
            ghost_recommendation=ghost.get("recommendation", ""),
        ))

    return combined
