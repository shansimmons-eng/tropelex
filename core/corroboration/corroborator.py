"""Corroboration orchestrator — ties research, scoring, and memory
into a CorroborationReport pipeline.

IO is isolated to corroborate_decision. extract_rationale and
build_research_query are pure functions.
"""

from __future__ import annotations

from datetime import datetime, timezone

from core.corroboration import (
    CorroborationReport,
    CorroborationStatus,
    Err,
    Ok,
    ResearchFinding,
    Result,
)
from core.corroboration.scorer import (
    ResearchFinding as ScorerFinding,
    compute_relevance,
    score_corroboration,
)
from core.memory.manager import MemoryManager
from core.tropebook.research import ResearchTool, SearchResult


def extract_rationale(decision: dict) -> str:
    """Extract rationale/reason from a decision dict.

    Checks 'rationale', 'reason', 'context', 'because' fields.
    Falls back to 'decision' field. Returns '' if nothing found.
    """
    for field_name in ("rationale", "reason", "context", "because"):
        value = decision.get(field_name, "")
        if isinstance(value, str) and len(value.strip()) > 5:
            return value.strip()
    fallback = decision.get("decision", "")
    return fallback.strip() if isinstance(fallback, str) else ""


def build_research_query(decision: dict, rationale: str) -> str:
    """Construct a focused search query from decision text + rationale.

    Removes stopwords and caps at 15 tokens for targeted web lookups.
    """
    _stop = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "have",
        "has", "had", "do", "does", "did", "will", "would", "could", "should",
        "may", "might", "can", "to", "of", "in", "for", "on", "with", "at",
        "by", "from", "as", "and", "but", "or", "not", "so", "if", "then",
        "that", "this", "it", "its", "we", "our", "i", "my",
    }
    raw = f"{decision.get('decision', '')} {rationale}"
    words = [
        w.strip(".,;:!?\"'()[]{}")
        for w in raw.lower().split()
        if w.strip(".,;:!?\"'()[]{}") not in _stop and len(w) > 2
    ]
    return " ".join(words[:15])


def _find_decision(memory: dict, decision_id: str) -> Result[dict, Err]:
    """Look up a decision by index or text substring. Pure data lookup."""
    decisions = memory.get("decisions", [])
    if not decisions:
        return Err(error="No decisions in project memory", code="NOT_FOUND")

    if decision_id.isdigit():
        idx = int(decision_id)
        if 0 <= idx < len(decisions):
            return Ok(value=decisions[idx])
        return Err(
            error=f"Index {idx} out of range (0-{len(decisions) - 1})",
            code="NOT_FOUND",
        )

    query = decision_id.lower()
    for dec in decisions:
        if query in str(dec.get("decision", "")).lower():
            return Ok(value=dec)

    return Err(error=f"Decision '{decision_id}' not found", code="NOT_FOUND")


def _to_scorer_findings(results: list[SearchResult]) -> list[ScorerFinding]:
    """Convert SearchResult objects to scorer-compatible ResearchFinding."""
    return [
        ScorerFinding(title=r.title, url=r.url, description=r.description)
        for r in results
    ]


def _to_report_findings(
    results: list[SearchResult], rationale: str,
) -> tuple[ResearchFinding, ...]:
    """Convert search results to report findings with relevance scores."""
    return tuple(
        ResearchFinding(
            title=r.title,
            url=r.url,
            description=r.description,
            source=r.source,
            relevance_score=compute_relevance(
                rationale,
                ScorerFinding(title=r.title, url=r.url, description=r.description),
            ),
        )
        for r in results
    )


def corroborate_decision(
    project: str,
    decision_id: str,
    research_tool: ResearchTool,
    memory_manager: MemoryManager,
    force_refresh: bool = False,
) -> Result[CorroborationReport, Err]:
    """Orchestrate rationale corroboration for a single decision.

    Loads memory, extracts rationale, searches web, scores findings,
    and builds a CorroborationReport. All IO isolated to this function.
    """
    try:
        memory = memory_manager.get_project_memory(project)
    except (OSError, ValueError, KeyError) as exc:
        return Err(
            error=f"Failed loading project '{project}': {exc}",
            code="MEMORY_ERROR",
        )

    dec_result = _find_decision(memory, decision_id)
    if isinstance(dec_result, Err):
        return dec_result

    rationale = extract_rationale(dec_result.value)
    if not rationale or len(rationale) < 10:
        return Ok(value=CorroborationReport(
            decision_id=decision_id,
            rationale=rationale,
            research_findings=(),
            status=CorroborationStatus.unverifiable,
            confidence_adjustment=0.0,
            evidence_urls=(),
            checked_at=datetime.now(timezone.utc).isoformat(),
        ))

    query = build_research_query(dec_result.value, rationale)
    try:
        results = research_tool.research(
            query, num_results=5, scrape=False, add_to_tropebook=False,
        )
    except (ConnectionError, TimeoutError, OSError) as exc:
        return Err(error=f"Research API failed: {exc}", code="RESEARCH_ERROR")

    scored = score_corroboration(rationale, _to_scorer_findings(results))

    return Ok(value=CorroborationReport(
        decision_id=decision_id,
        rationale=rationale,
        research_findings=_to_report_findings(results, rationale),
        status=CorroborationStatus(scored.status),
        confidence_adjustment=scored.confidence_adjustment,
        evidence_urls=tuple(scored.evidence_urls),
        checked_at=datetime.now(timezone.utc).isoformat(),
    ))
