"""
Narrative Mode — FastAPI router.

Generates prose narratives of project decisions for non-technical audiences
(investor, new_hire, pm).

Mount into the main app:
    from core.narrative.router import narrative_router
    app.include_router(narrative_router)
"""

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.memory.manager import MemoryManager
from core.narrative import Err, NarrativeReport
from core.narrative.story_builder import build_narrative

logger = logging.getLogger("tropelex.narrative")

narrative_router = APIRouter(prefix="/api/memory", tags=["narrative"])

_BASE_DIR = Path(__file__).parent.parent.parent


class NarrativeRequest(BaseModel):
    """Request body for narrative generation."""

    audience: str = Field(
        default="new_hire",
        pattern=r"^(investor|new_hire|pm)$",
        description="Target audience: investor, new_hire, or pm",
    )


def _serialize_report(report: NarrativeReport) -> dict[str, Any]:
    """Convert NarrativeReport dataclass to JSON-serializable dict."""
    return {
        "title": report.title,
        "sections": [
            {"heading": s.heading, "body": s.body, "section_type": s.section_type}
            for s in report.sections
        ],
        "summary": report.summary,
        "audience": report.audience,
        "word_count": report.word_count,
        "project_name": report.project_name,
        "generated_at": report.generated_at,
    }


@narrative_router.post("/{project}/narrative")
async def generate_narrative(project: str, body: NarrativeRequest) -> dict[str, Any]:
    """Generate a prose narrative of project decisions for a target audience.

    Loads project memory via MemoryManager, builds audience-specific
    narrative sections (origin, pivots, resolution), and returns a
    structured NarrativeReport as JSON.
    """
    # Load project memory
    try:
        mm = MemoryManager(str(_BASE_DIR))
        memory = mm.get_project_memory(project)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("Failed to load memory for '%s': %s", project, exc)
        raise HTTPException(status_code=500, detail=f"Failed to load project memory: {exc}")

    # Build narrative (returns Result type)
    result = build_narrative(memory, body.audience)

    if isinstance(result, Err):
        if result.code == "NOT_FOUND":
            raise HTTPException(status_code=404, detail=result.error)
        if result.code == "VALIDATION_ERROR":
            raise HTTPException(status_code=422, detail=result.error)
        logger.error("Narrative build failed for '%s': %s", project, result.error)
        raise HTTPException(status_code=500, detail=result.error)

    return _serialize_report(result.value)
