"""
Compaction — FastAPI router for memory compaction.

Mount into the main app:
    from core.compaction.router import compaction_router
    app.include_router(compaction_router)
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.compaction import Err, Result
from core.compaction.compactor import CompactionResult, compact_memory
from core.compaction.epoch import EpochRecord
from core.memory.manager import MemoryManager

logger = logging.getLogger("tropelex.compaction")

compaction_router = APIRouter(prefix="/api/memory", tags=["compaction"])


# ── Domain exceptions ──────────────────────────────────────────────────────


class CompactionError(Exception):
    """Raised at IO boundaries for compaction failures."""

    def __init__(
        self,
        message: str,
        code: str = "COMPACTION_ERROR",
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.details = details or {}


class MemoryNotFoundError(Exception):
    """Raised when project memory file does not exist."""

    def __init__(self, project: str):
        super().__init__(f"Project '{project}' not found")
        self.project = project


class ValidationError(Exception):
    """Raised on invalid input at API boundary."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.details = details or {}


# ── Pydantic models ────────────────────────────────────────────────────────


class CompactRequest(BaseModel):
    """Optional body for POST /compact — force compaction past staleness gate."""

    force: bool = Field(default=False, description="Force compaction even when nothing is stale")


# ── Pure helpers ────────────────────────────────────────────────────────────


def _validate_project(project: str) -> None:
    """Raise ValidationError if project name contains disallowed characters."""
    if not re.match(r"^[a-zA-Z0-9_\-]+$", project):
        raise ValidationError(
            f"Invalid project name: {project!r}",
            details={"allowed": "alphanumeric, hyphens, underscores"},
        )


def _load_memory(project: str) -> dict[str, Any]:
    """Load project memory or raise MemoryNotFoundError at IO boundary."""
    mm = MemoryManager()
    path: Path = mm.memory_dir / f"{project}.json"
    if not path.exists():
        raise MemoryNotFoundError(project)
    return mm.get_project_memory(project)


def _compaction_status(memory: dict[str, Any]) -> dict[str, Any]:
    """Compute compaction stats from memory — pure, no I/O."""
    decisions = memory.get("decisions", [])
    archived = memory.get("archived_decisions", [])
    epochs = memory.get("epochs", [])

    last_compaction: str | None = None
    if epochs:
        last_compaction = epochs[-1].get("date_range", [None, None])[-1]

    return {
        "total_decisions": len(decisions),
        "archived_count": len(archived),
        "epoch_count": len(epochs),
        "last_compaction": last_compaction,
    }


def _serialize_epoch(epoch: EpochRecord) -> dict[str, Any]:
    """Serialize an EpochRecord to a JSON-friendly dict."""
    return {
        "epoch_id": epoch.epoch_id,
        "summary": {
            "text": epoch.summary.text,
            "topic": epoch.summary.topic,
            "count": epoch.summary.count,
            "resolution": epoch.summary.resolution,
            "date_range": list(epoch.date_range),
            "key_decision_id": epoch.summary.key_decision_id,
        },
        "archived_decision_ids": epoch.archived_decision_ids,
        "date_range": list(epoch.date_range),
        "confidence_range": list(epoch.confidence_range),
    }


def _result_to_http(result: Err) -> HTTPException:
    """Translate a domain Err to the appropriate HTTP status code."""
    status_map = {
        "NOT_FOUND": 404,
        "VALIDATION_ERROR": 422,
        "IO_ERROR": 500,
    }
    status = status_map.get(result.code, 500)
    return HTTPException(status_code=status, detail=result.error)


# ── Endpoints ───────────────────────────────────────────────────────────────


@compaction_router.post("/{project}/compact")
async def trigger_compaction(
    project: str,
    body: CompactRequest | None = None,
) -> dict[str, Any]:
    """Trigger a memory compaction pass for the given project.

    Finds stale supersession chains, merges them into epoch summaries,
    and archives originals without deletion. Returns the compaction report.
    """
    try:
        _validate_project(project)
        memory = _load_memory(project)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except MemoryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("compaction load failed for %s: %s", project, exc)
        raise HTTPException(status_code=500, detail=f"Failed to load memory: {exc}")

    result: Result = compact_memory(project, memory)

    if isinstance(result, Err):
        raise _result_to_http(result)

    cr: CompactionResult = result.value
    return {
        "epochs_created": cr.epochs_created,
        "decisions_archived": cr.decisions_archived,
        "token_savings_estimate": cr.token_savings_estimate,
        "epoch_summaries": [_serialize_epoch(e) for e in cr.epoch_summaries],
    }


@compaction_router.get("/{project}/compaction/status")
async def compaction_status(project: str) -> dict[str, Any]:
    """Return current compaction stats for a project.

    Reports total active decisions, archived count, epoch count,
    and timestamp of the most recent compaction.
    """
    try:
        _validate_project(project)
        memory = _load_memory(project)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except MemoryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("compaction status load failed for %s: %s", project, exc)
        raise HTTPException(status_code=500, detail=f"Failed to load memory: {exc}")

    return _compaction_status(memory)
