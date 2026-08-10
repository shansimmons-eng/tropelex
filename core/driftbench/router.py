"""
Drift-Bench Evaluation Harness — FastAPI router (wishlist #60).

Not project-scoped (same shape as core/agent_audit/router.py's
/api/agent-audit) -- the scenario corpus is a fixed, deterministic set of
synthetic decisions/diffs, not tied to any one project's real memory.

Mount into the main app:
    from core.driftbench.router import driftbench_router
    app.include_router(driftbench_router)
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from core.driftbench.report import load_latest, run_suite
from core.driftbench.scenarios import build_corpus

logger = logging.getLogger("tropelex.driftbench")

driftbench_router = APIRouter(prefix="/api/driftbench", tags=["driftbench"])


@driftbench_router.get("/latest")
async def get_latest_report() -> dict[str, Any]:
    """Return the last-persisted Drift-Bench report. 404 if the suite has
    never been run (no pre-push has fired yet and nobody's hit /run)."""
    try:
        report = load_latest()
    except Exception as exc:
        logger.error("Drift-Bench latest report load failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
    if report is None:
        raise HTTPException(status_code=404, detail="Drift-Bench has not been run yet")
    return report


@driftbench_router.post("/run")
async def run_now() -> dict[str, Any]:
    """Run the scenario corpus now, persist, and return the report."""
    try:
        return run_suite(build_corpus())
    except Exception as exc:
        logger.error("Drift-Bench run failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
