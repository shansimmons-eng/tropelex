"""Doc Mining detector — pure functions comparing markdown claims against a
project's decision graph and against each other.

Reuses core.contradictions.detector's matching logic (Jaccard similarity +
opposing-keyword/tech-opposition classification) rather than re-implementing
it — a doc claim and a decision are both just "a sentence someone asserted,"
so the same classifier applies to both comparisons.
"""

from __future__ import annotations

from itertools import combinations

from core.contradictions.detector import classify_contradiction, compute_similarity
from core.docmine import DocClaim, DocFinding, DocMineReport, UncapturedClaim

# Cap on total claims considered for cross-doc pairwise comparison — this
# comparison is O(n^2); a real repo's docs stay well under this in practice.
_MAX_CLAIMS_FOR_CROSS_DOC = 3000

_DECISION_LIKE_KEYWORDS = {
    "use", "uses", "using", "must", "should", "always", "never", "require",
    "requires", "decided", "decide", "choose", "chose", "prefer", "prefers",
    "avoid", "adopt", "adopted", "reject", "enable", "enabled", "disable",
    "disabled", "will", "won't", "don't", "do not",
}

_UNCAPTURED_SIMILARITY_THRESHOLD = 0.15


def _is_decision_like(text: str) -> bool:
    lower = text.lower()
    return any(f" {kw} " in f" {lower} " for kw in _DECISION_LIKE_KEYWORDS)


def mine_markdown_files(
    claims: list[DocClaim], decisions: list[dict]
) -> DocMineReport:
    """Compare extracted doc claims against a project's decisions and each
    other. Pure function — no I/O.
    """
    files_scanned = sorted({c.source_file for c in claims})
    findings: list[DocFinding] = []
    uncaptured: list[UncapturedClaim] = []

    for claim in claims:
        claim_as_decision = {"id": claim.id, "decision": claim.text}
        best_similarity = 0.0
        for decision in decisions:
            similarity = compute_similarity(claim.text, decision.get("decision", ""))
            best_similarity = max(best_similarity, similarity)
            result = classify_contradiction(claim_as_decision, decision, similarity)
            if result is not None:
                findings.append(DocFinding(
                    id=result.id,
                    kind="doc_vs_decision",
                    claim_a_text=claim.text,
                    claim_a_source=f"{claim.source_file}:{claim.line_number}",
                    claim_b_text=decision.get("decision", ""),
                    claim_b_source=decision.get("id", "unknown"),
                    contradiction_type=result.contradiction_type,
                    severity=result.severity,
                    similarity_score=result.similarity_score,
                    resolution_suggestion=result.resolution_suggestion,
                ))

        if best_similarity < _UNCAPTURED_SIMILARITY_THRESHOLD and _is_decision_like(claim.text):
            uncaptured.append(UncapturedClaim(
                text=claim.text,
                source_file=claim.source_file,
                line_number=claim.line_number,
            ))

    if len(claims) <= _MAX_CLAIMS_FOR_CROSS_DOC:
        for claim_a, claim_b in combinations(claims, 2):
            if claim_a.source_file == claim_b.source_file:
                continue
            similarity = compute_similarity(claim_a.text, claim_b.text)
            result = classify_contradiction(
                {"id": claim_a.id, "decision": claim_a.text},
                {"id": claim_b.id, "decision": claim_b.text},
                similarity,
            )
            if result is not None:
                findings.append(DocFinding(
                    id=result.id,
                    kind="doc_vs_doc",
                    claim_a_text=claim_a.text,
                    claim_a_source=f"{claim_a.source_file}:{claim_a.line_number}",
                    claim_b_text=claim_b.text,
                    claim_b_source=f"{claim_b.source_file}:{claim_b.line_number}",
                    contradiction_type=result.contradiction_type,
                    severity=result.severity,
                    similarity_score=result.similarity_score,
                    resolution_suggestion=result.resolution_suggestion,
                ))

    findings.sort(key=lambda f: {"high": 0, "medium": 1, "low": 2}.get(f.severity, 3))

    return DocMineReport(
        files_scanned=files_scanned,
        claims_extracted=len(claims),
        findings=findings,
        uncaptured_claims=uncaptured,
    )
