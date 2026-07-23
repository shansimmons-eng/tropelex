"""
Slack Decision Capture — FastAPI router.

Endpoints for capturing decisions from chat and extracting
implicit decisions from message threads.
"""

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.memory.manager import MemoryManager
from core.slack import (
    Ok as SlackOk,
    ExtractionResult,
)
from core.slack.capture import (
    capture_decision,
    detect_conflict,
    extract_decisions_from_thread,
)

logger = logging.getLogger("tropelex.slack")

slack_router = APIRouter(prefix="/api/memory", tags=["slack"])

_mm = MemoryManager()


# --- Pydantic models ---


class SlackCaptureRequest(BaseModel):
    decision_text: str = Field(..., min_length=1, max_length=500)
    context: str = Field("", max_length=500)
    channel: str = Field("", max_length=100)
    agent_name: str = Field("", max_length=100)


class SlackExtractRequest(BaseModel):
    messages: list[str] = Field(..., min_length=1, max_length=100)
    channel: str = Field("", max_length=100)


# --- Endpoints ---


@slack_router.post("/{project}/slack/capture")
async def slack_capture(
    project: str,
    body: SlackCaptureRequest,
) -> dict[str, Any]:
    """Capture a decision from a Slack message."""
    if project not in _mm.list_projects():
        raise HTTPException(status_code=404, detail=f"Project '{project}' not found")
    try:
        memory = _mm.get_project_memory(project)
    except Exception as exc:
        logger.error("Failed to load memory for %s: %s", project, exc)
        raise HTTPException(status_code=500, detail=str(exc))

    result = capture_decision(
        memory=memory,
        decision_text=body.decision_text,
        context=body.context,
        channel=body.channel,
        agent_name=body.agent_name,
    )

    if hasattr(result, "error"):
        code = getattr(result, "code", "UNKNOWN")
        if code == "VALIDATION_ERROR":
            raise HTTPException(status_code=422, detail=result.error)
        raise HTTPException(status_code=500, detail=result.error)

    decision = result.value

    # Check for conflicts
    existing = memory.get("decisions", [])
    conflicts = detect_conflict(decision.decision_text, existing[:-1])

    # Save
    try:
        _mm.save_project_memory(project, memory)
    except Exception as exc:
        logger.error("Failed to save memory for %s: %s", project, exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "decision_text": decision.decision_text,
        "context": decision.context,
        "source": decision.source,
        "channel": decision.channel,
        "timestamp": decision.timestamp,
        "conflicts": conflicts,
        "conflict_count": len(conflicts),
    }


@slack_router.post("/{project}/slack/extract")
async def slack_extract(
    project: str,
    body: SlackExtractRequest,
) -> dict[str, Any]:
    """Extract implicit decisions from a thread of messages."""
    if project not in _mm.list_projects():
        raise HTTPException(status_code=404, detail=f"Project '{project}' not found")

    result = extract_decisions_from_thread(body.messages)

    if hasattr(result, "error"):
        raise HTTPException(status_code=422, detail=result.error)

    extraction = result.value

    return {
        "decisions": [
            {
                "decision_text": d.decision_text,
                "context": d.context,
                "source": d.source,
            }
            for d in extraction.decisions
        ],
        "thread_summary": extraction.thread_summary,
        "extraction_count": extraction.extraction_count,
    }
