"""
Tropelex Sync API — FastAPI router for memory export/import/status.

Mount into the main app:
    from core.sync.router import sync_router
    app.include_router(sync_router)
"""

import base64
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from core.sync.exporter import export_memory_data
from core.sync.importer import import_memory_data

logger = logging.getLogger("tropelex.sync")

sync_router = APIRouter(prefix="/api/sync", tags=["sync"])

# --- Paths (computed relative to this file, matching server.py pattern) ---
_CORE_DIR = Path(__file__).parent.parent  # core/
BASE_DIR = _CORE_DIR.parent              # project root

# --- In-memory sync timestamps ---
_sync_state: dict[str, Any] = {
    "last_export": None,
    "last_import": None,
}


# --- Request / response models ---


class SyncImportRequest(BaseModel):
    """Body for POST /api/sync/import."""

    data: str = Field(..., description="Base64-encoded gzip or plain JSON export payload")
    overwrite: bool = Field(False, description="Overwrite existing projects instead of merging")


class SyncStatusResponse(BaseModel):
    """Response for GET /api/sync/status."""

    last_export: str | None = None
    last_import: str | None = None
    export_count: int = 0
    import_count: int = 0
    memory_dir_exists: bool = False
    project_count: int = 0


class SyncImportResponse(BaseModel):
    """Response for POST /api/sync/import."""

    projects_imported: int
    files_written: int
    errors: list[str]


# --- Endpoints ---


@sync_router.get("/export")
async def sync_export() -> Response:
    """Export all memory as gzip-compressed JSON.

    Returns raw gzip bytes with Content-Encoding: gzip so clients
    can transparently decompress.
    """
    try:
        raw = export_memory_data(str(BASE_DIR))
    except Exception as exc:
        logger.error("sync_export failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Export failed: {exc}")

    _sync_state["last_export"] = datetime.now(timezone.utc).isoformat()

    return Response(
        content=raw,
        media_type="application/json",
        headers={"Content-Encoding": "gzip"},
    )


@sync_router.post("/import")
async def sync_import(req: SyncImportRequest) -> SyncImportResponse:
    """Import memory from a base64-encoded export payload.

    ``data`` is a base64 string produced by an export call (or any
    compatible export source).  When ``overwrite`` is false (default)
    the importer merges decisions and session history; when true it
    replaces entire project files.
    """
    try:
        decoded = base64.b64decode(req.data)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid base64 data: {exc}",
        )

    try:
        summary = import_memory_data(decoded, str(BASE_DIR), overwrite=req.overwrite)
    except Exception as exc:
        logger.error("sync_import failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Import failed: {exc}")

    if summary.get("errors"):
        logger.warning("sync_import completed with errors: %s", summary["errors"])

    _sync_state["last_import"] = datetime.now(timezone.utc).isoformat()

    return SyncImportResponse(
        projects_imported=summary["projects_imported"],
        files_written=summary["files_written"],
        errors=summary["errors"],
    )


@sync_router.get("/status")
async def sync_status() -> SyncStatusResponse:
    """Return sync status: timestamps and memory directory info."""
    memory_dir = BASE_DIR / "memory"
    projects: list[str] = []
    if memory_dir.exists():
        projects = [f.stem for f in memory_dir.glob("*.json") if f.is_file()]

    return SyncStatusResponse(
        last_export=_sync_state["last_export"],
        last_import=_sync_state["last_import"],
        export_count=1 if _sync_state["last_export"] else 0,
        import_count=1 if _sync_state["last_import"] else 0,
        memory_dir_exists=memory_dir.exists(),
        project_count=len(projects),
    )
