"""
Prefetch — FastAPI router for predictive context prefetch.

Mount into the main app:
    from core.prefetch.router import prefetch_router
    app.include_router(prefetch_router)
"""

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.prefetch.assembler import (
    Err as AssemblerErr,
    ScoredItem,
    assemble_budget_bundle,
    estimate_tokens,
)
from core.prefetch.genealogy import (
    Ok as GenealogyOk,
    PrefetchError,
    load_genealogy,
    record_bundle_outcome,
)
from core.prefetch.relevance import DEFAULT_WEIGHTS, compute_relevance_score
from core.knowledge_decay import score_decision
from core.prefetch.tuner import Ok as TunerOk, tune_for_task
from core.memory.manager import MemoryManager

logger = logging.getLogger("tropelex.prefetch")

prefetch_router = APIRouter(prefix="/api/memory", tags=["prefetch"])

_mm = MemoryManager()
_GENEALOGY_DIR = Path(_mm.memory_dir) / "prefetch"


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class PrefetchRequest(BaseModel):
    """Request body for predictive context prefetch."""

    task: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Natural-language task description for relevance scoring",
    )
    token_budget: int = Field(
        ...,
        ge=500,
        le=50_000,
        description="Maximum token budget for the assembled bundle",
    )
    role: str | None = Field(
        default=None,
        description="Optional agent role for profile-aware tuning",
    )


class PrefetchOutcomeRequest(BaseModel):
    """Request body for recording bundle usage outcome."""

    referenced_ids: list[str] = Field(
        default_factory=list,
        description="IDs of included items that were actually used",
    )
    requested_but_missing: list[str] = Field(
        default_factory=list,
        description="IDs of items requested but absent from the bundle",
    )
    outcome: str | None = Field(
        default=None,
        description="Optional outcome label: referenced, partially_used, unused",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_memory(project: str) -> dict[str, Any]:
    """Load a project's memory, or raise 404."""
    if project not in _mm.list_projects():
        raise HTTPException(status_code=404, detail=f"Project '{project}' not found")
    return _mm.get_project_memory(project)


def _genealogy_path(project: str) -> Path:
    """Resolve genealogy storage path for a project."""
    return _GENEALOGY_DIR / f"{project}_genealogy.json"


def _score_decisions(
    decisions: list[dict],
    task: str,
    weights: dict[str, float],
) -> list[ScoredItem]:
    """Score all decisions against the task, return ScoredItems sorted by relevance."""
    scored: list[ScoredItem] = []
    for d in decisions:
        score = compute_relevance_score(d, task, decisions, weights)
        decision_text = d.get("decision", "")
        context_text = d.get("context", "")
        combined = f"{decision_text}\n{context_text}" if context_text else decision_text
        token_est = estimate_tokens(combined)
        scored.append(ScoredItem(
            text=combined,
            token_estimate=token_est,
            relevance_score=score,
            source_id=d.get("id", d.get("timestamp", "")),
            metadata={
                "decision_id": d.get("id", ""),
                "categories": d.get("categories", []),
                # #58: same info already folded into `score` via
                # compute_confidence_component -- surfaced explicitly so
                # ranking isn't a number with no explanation.
                "confidence_tier": score_decision(d, decisions).get("tier"),
            },
        ))
    return scored


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@prefetch_router.post("/{project}/prefetch")
async def prefetch_bundle(
    project: str,
    body: PrefetchRequest,
) -> dict[str, Any]:
    """Predictive context prefetch — assemble a budget-aware bundle.

    Flow: load memory → tune weights → score decisions → assemble bundle →
    record genealogy → return bundle with near-misses.
    """
    try:
        memory = _load_memory(project)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("prefetch load failed for %s: %s", project, exc)
        raise HTTPException(status_code=500, detail=str(exc))

    decisions = memory.get("decisions", [])
    if not decisions:
        return {
            "bundle_id": uuid.uuid4().hex[:16],
            "bundle": [],
            "near_misses": [],
            "token_count": 0,
            "item_count": 0,
            "near_miss_count": 0,
            "tuning_info": {"reasoning": "No decisions in memory"},
        }

    # Tune weights/budget based on agent skills
    agent_skills = memory.get("agent_skills", {})
    tuning_result = tune_for_task(
        task_text=body.task,
        agent_skills=agent_skills,
        base_budget=body.token_budget,
        base_weights=DEFAULT_WEIGHTS,
    )

    if isinstance(tuning_result, TunerOk):
        tuning = tuning_result.value
        effective_budget = tuning.adjusted_budget
        effective_weights = tuning.adjusted_weights
        tuning_reasoning = tuning.reasoning
    else:
        effective_budget = body.token_budget
        effective_weights = DEFAULT_WEIGHTS
        tuning_reasoning = f"Tuning skipped: {tuning_result.error}"

    # Score decisions and assemble bundle
    scored_items = _score_decisions(decisions, body.task, effective_weights)

    bundle_result = assemble_budget_bundle(scored_items, effective_budget)

    if isinstance(bundle_result, AssemblerErr):
        raise HTTPException(status_code=500, detail=bundle_result.error)

    bundle = bundle_result.value
    bundle_id = uuid.uuid4().hex[:16]

    # Record in genealogy (best-effort, non-blocking)
    try:
        record_bundle_outcome(
            bundle_id=bundle_id,
            task=body.task,
            included_ids=[it.source_id for it in bundle.included],
            referenced_ids=[],
            requested_but_missing=[],
            storage_path=_genealogy_path(project),
        )
    except (PrefetchError, Exception) as exc:
        logger.warning("genealogy record failed for %s: %s", project, exc)

    # Format response
    items_out = [
        {
            "text": it.text,
            "token_estimate": it.token_estimate,
            "relevance_score": it.relevance_score,
            "source_id": it.source_id,
            "metadata": it.metadata,
        }
        for it in bundle.included
    ]
    misses_out = [
        {
            "text": it.text,
            "token_estimate": it.token_estimate,
            "relevance_score": it.relevance_score,
            "source_id": it.source_id,
        }
        for it in bundle.near_misses
    ]

    return {
        "bundle_id": bundle_id,
        "bundle": items_out,
        "near_misses": misses_out,
        "token_count": bundle.total_tokens,
        "item_count": bundle.item_count,
        "near_miss_count": bundle.near_miss_count,
        "tuning_info": {
            "adjusted_budget": effective_budget,
            "compression_level": (
                tuning.compression_level
                if isinstance(tuning_result, TunerOk)
                else 1
            ),
            "reasoning": tuning_reasoning,
        },
    }


@prefetch_router.post("/{project}/prefetch/{bundle_id}/outcome")
async def record_prefetch_outcome(
    project: str,
    bundle_id: str,
    body: PrefetchOutcomeRequest,
) -> dict[str, Any]:
    """Record bundle usage outcome for genealogy feedback loop.

    Computes precision and recall-proxy from referenced vs missing items.
    """
    if not bundle_id or not bundle_id.strip():
        raise HTTPException(status_code=422, detail="bundle_id must not be empty")

    # Verify project exists (will raise 404 if not)
    _load_memory(project)

    storage_path = _genealogy_path(project)

    # Load existing genealogy to find the bundle's task
    genealogy = load_genealogy(storage_path)
    bundle_task = ""
    for b in genealogy.get("bundles", []):
        if b.get("bundle_id") == bundle_id:
            bundle_task = b.get("task", "")
            break

    result = record_bundle_outcome(
        bundle_id=bundle_id,
        task=bundle_task or f"unknown-{bundle_id}",
        included_ids=[],
        referenced_ids=body.referenced_ids,
        requested_but_missing=body.requested_but_missing,
        storage_path=storage_path,
    )

    if isinstance(result, GenealogyOk):
        record = result.value
        return {
            "precision": record.precision,
            "recall_proxy": record.recall_proxy,
            "message": (
                f"Outcome recorded for bundle {bundle_id}: "
                f"precision={record.precision:.2f}, "
                f"recall_proxy={record.recall_proxy:.2f}"
            ),
        }

    # Err case
    raise HTTPException(status_code=500, detail=result.error)
