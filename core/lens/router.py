"""
Memory Lens — FastAPI router.

Provides endpoints for annotating code with decision references
and scanning files for decision-related patterns.

Mount into the main app:
    from core.lens.router import lens_router
    app.include_router(lens_router)
"""

import logging
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.lens import Annotation, Err
from core.lens.annotator import map_code_to_decisions, scan_file_for_decisions
from core.memory.manager import MemoryManager

logger = logging.getLogger("tropelex.lens")

lens_router = APIRouter(prefix="/api/memory", tags=["lens"])

_mm = MemoryManager()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_memory(project: str) -> dict[str, Any]:
    """Load project memory, or raise HTTP 404."""
    if project not in _mm.list_projects():
        raise HTTPException(status_code=404, detail=f"Project '{project}' not found")
    return _mm.get_project_memory(project)


def _enrich_annotations(
    annotations: list[Annotation],
    file_path: str,
    line_offset: int | None = None,
) -> list[dict[str, Any]]:
    """Apply file_path (and optional line override) then serialize."""
    enriched: list[dict[str, Any]] = []
    for ann in annotations:
        enriched.append(asdict(Annotation(
            decision_id=ann.decision_id,
            decision_text=ann.decision_text,
            confidence=ann.confidence,
            line_number=line_offset if line_offset is not None else ann.line_number,
            file_path=file_path,
            relationship=ann.relationship,
            reference_count=ann.reference_count,
        )))
    return enriched


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class LensAnnotateRequest(BaseModel):
    """Request body for single-line annotation."""

    file_path: str = Field(..., min_length=1, max_length=500)
    line_number: int = Field(..., ge=1)
    code_content: str = Field(..., max_length=50_000)


class LensScanRequest(BaseModel):
    """Request body for full-file scan."""

    file_path: str = Field(..., min_length=1, max_length=500)
    code_content: str = Field(..., max_length=200_000)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@lens_router.post("/{project}/lens/annotate")
async def annotate_code(project: str, req: LensAnnotateRequest) -> dict[str, Any]:
    """Get decision annotations for a specific line of code.

    Accepts file_path, line_number, and code_content.
    Returns matching decision annotations ranked by confidence.
    """
    memory = _load_memory(project)
    decisions = memory.get("decisions", [])

    result = map_code_to_decisions(req.code_content, decisions)
    if isinstance(result, Err):
        if result.code == "VALIDATION_ERROR":
            raise HTTPException(status_code=422, detail=result.error)
        raise HTTPException(status_code=500, detail=result.error)

    return {
        "file_path": req.file_path,
        "line_number": req.line_number,
        "annotations": _enrich_annotations(
            result.value, req.file_path, req.line_number,
        ),
        "total": len(result.value),
    }


@lens_router.post("/{project}/lens/scan")
async def scan_file(project: str, req: LensScanRequest) -> dict[str, Any]:
    """Scan entire file content for decision references.

    Accepts file_path and code_content.
    Returns all annotations found across every line.
    """
    memory = _load_memory(project)
    decisions = memory.get("decisions", [])

    result = scan_file_for_decisions(req.code_content, decisions)
    if isinstance(result, Err):
        if result.code == "VALIDATION_ERROR":
            raise HTTPException(status_code=422, detail=result.error)
        raise HTTPException(status_code=500, detail=result.error)

    return {
        "file_path": req.file_path,
        "annotations": _enrich_annotations(result.value, req.file_path),
        "total": len(result.value),
    }
