"""
Explainable Memory — FastAPI router.

Mount into the main app:
    from core.explain.router import explain_router
    app.include_router(explain_router)
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.explain.explainer import ExplanationReport, explain_why
from core.decision_tree import DecisionTree
from core.memory.manager import MemoryManager

logger = logging.getLogger("tropelex.explain")

explain_router = APIRouter(prefix="/api/memory", tags=["explain"])

_mm = MemoryManager()


def _load_memory(project: str) -> dict[str, Any]:
    """Load a project's memory, or raise 404."""
    if project not in _mm.list_projects():
        raise HTTPException(status_code=404, detail=f"Project '{project}' not found")
    return _mm.get_project_memory(project)


class ExplainRequest(BaseModel):
    question: str


@explain_router.post("/{project}/explain")
async def explain_decision(project: str, req: ExplainRequest) -> dict[str, Any]:
    """Answer a 'why' question about a decision."""
    try:
        memory = _load_memory(project)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("explain load failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    # Build decision tree from memory
    decisions = memory.get("decisions", [])
    tree = DecisionTree.from_decisions(decisions) if decisions else DecisionTree()

    report: ExplanationReport = explain_why(req.question, memory, tree)

    return {
        "question": report.question,
        "answer": report.answer,
        "causal_chain": report.causal_chain,
        "provenance": report.provenance,
        "supersession_chain": report.supersession_chain,
        "downstream_impact": report.downstream_impact,
        "source_citations": report.source_citations,
        "confidence": report.confidence,
    }
