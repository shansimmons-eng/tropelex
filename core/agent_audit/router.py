"""
Agent Surface Audit — FastAPI router.

Mount into the main app:
    from core.agent_audit.router import agent_audit_router
    app.include_router(agent_audit_router)
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from core.agent_audit.scanner import audit_agent_surface

logger = logging.getLogger("tropelex.agent_audit")

agent_audit_router = APIRouter(prefix="/api/agent-audit", tags=["agent-audit"])


@agent_audit_router.post("/scan")
async def scan_agent_surface(
    repo_path: str = Query("", max_length=500,
                            description="Repo to scan; defaults to the Tropelex repo itself"),
) -> dict[str, Any]:
    """Scan an agent harness configuration for risk.

    Checks CLAUDE.md/AGENTS.md, .mcp.json, .claude/settings*.json, agent
    definitions, and skill definitions across five categories: secrets,
    permission auditing, hook injection risk, MCP server risk profiling, and
    agent/skill config review. Defaults to auditing Tropelex's own repo when
    no repo_path is given.
    """
    from core.tropebook.web.server import BASE_DIR

    path = repo_path.strip()[:500] or str(BASE_DIR)

    try:
        report = audit_agent_surface(path)
    except Exception as exc:
        logger.error("agent surface audit failed for %s: %s", path, exc)
        raise HTTPException(500, f"Agent surface audit failed: {exc}")

    return {
        "repo_path": path,
        "grade": report.grade,
        "files_scanned": report.files_scanned,
        "category_counts": report.category_counts,
        "severity_distribution": report.severity_distribution,
        "total_findings": len(report.findings),
        "findings": [
            {
                "id": f.id,
                "category": f.category,
                "severity": f.severity,
                "file": f.file,
                "line": f.line,
                "description": f.description,
                "recommendation": f.recommendation,
            }
            for f in report.findings
        ],
    }
