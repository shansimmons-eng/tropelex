"""Doc Mining — FastAPI router.

Mount into the main app:
    from core.docmine.router import docmine_router
    app.include_router(docmine_router)
"""

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.docmine.detector import mine_markdown_files
from core.docmine.extractor import extract_claims
from core.memory.manager import MemoryManager

logger = logging.getLogger("tropelex.docmine")

docmine_router = APIRouter(prefix="/api/memory", tags=["docmine"])

_CORE_DIR = Path(__file__).parent.parent
BASE_DIR = _CORE_DIR.parent
_mm = MemoryManager()

# Directories never worth scanning for doc claims.
_EXCLUDED_DIR_NAMES = {
    "node_modules", ".venv", "venv", ".git", "__pycache__",
    ".ruff_cache", ".pytest_cache", ".ropeproject", "memory",
    ".tmp", "templates",
}


def _load_memory(project: str) -> dict[str, Any]:
    if project not in _mm.list_projects():
        raise HTTPException(status_code=404, detail=f"Project '{project}' not found")
    return _mm.get_project_memory(project)


def _escalate_to_review(memory: dict[str, Any], decision_ids: set[str]) -> int:
    """Flip requires_review=True on decisions a high-severity doc-vs-decision
    finding contradicts, if not already flagged. Same escalation rule as
    Contradictions — mutates memory in place, returns count newly escalated.
    """
    escalated = 0
    for d in memory.get("decisions", []):
        if d.get("id") not in decision_ids:
            continue
        safety = d.setdefault("safety_metadata", {})
        if safety.get("requires_review"):
            continue
        safety["requires_review"] = True
        if safety.get("risk_level", "low") == "low":
            safety["risk_level"] = "medium"
        escalated += 1
    return escalated


def _discover_markdown_files(base: Path) -> list[Path]:
    found: list[Path] = []
    for path in base.rglob("*.md"):
        if any(part in _EXCLUDED_DIR_NAMES for part in path.parts):
            continue
        found.append(path)
    return sorted(found)


class DocMineRequest(BaseModel):
    """Request body for a doc-mining scan.

    paths: specific files/directories to scan, relative to the repo root.
    Omit to scan every .md file in the repo (excluding node_modules, venvs,
    .git, caches, and memory/).
    """
    paths: list[str] = Field(default_factory=list, max_length=200)


@docmine_router.post("/{project}/docmine/scan")
async def scan_markdown(project: str, body: DocMineRequest) -> dict[str, Any]:
    """Mine markdown files for drift, contradictions, and undocumented
    decisions against a project's decision graph.

    Compares every extracted claim against every recorded decision (reusing
    the same matching logic as Contradiction Detection), against claims from
    every *other* markdown file, and flags decision-shaped claims that don't
    match anything in the decision graph at all — knowledge sitting in prose
    docs that never made it into tracked decisions.
    """
    memory = _load_memory(project)
    decisions = memory.get("decisions", [])

    if body.paths:
        targets: list[Path] = []
        for raw in body.paths:
            candidate = (BASE_DIR / raw).resolve()
            if BASE_DIR.resolve() not in candidate.parents and candidate != BASE_DIR.resolve():
                raise HTTPException(status_code=422, detail=f"Path escapes repo root: {raw}")
            if candidate.is_dir():
                targets.extend(_discover_markdown_files(candidate))
            elif candidate.is_file() and candidate.suffix == ".md":
                targets.append(candidate)
            else:
                raise HTTPException(status_code=404, detail=f"Not a markdown file or directory: {raw}")
    else:
        targets = _discover_markdown_files(BASE_DIR)

    if not targets:
        raise HTTPException(status_code=404, detail="No markdown files found to scan")

    claims = []
    for path in targets:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("docmine: skipping unreadable file %s: %s", path, exc)
            continue
        rel_path = str(path.relative_to(BASE_DIR))
        claims.extend(extract_claims(text, rel_path))

    report = mine_markdown_files(claims, decisions)
    severity_distribution = {"high": 0, "medium": 0, "low": 0}
    for f in report.findings:
        if f.severity in severity_distribution:
            severity_distribution[f.severity] += 1

    # Safety Review integration: a high-severity doc-vs-decision finding
    # means a committed doc actively contradicts a recorded decision — that
    # decision auto-escalates into the review queue. doc_vs_doc findings
    # don't reference a decision at all, so only doc_vs_decision counts here.
    high_severity_decision_ids = {
        f.claim_b_source
        for f in report.findings
        if f.severity == "high" and f.kind == "doc_vs_decision"
    }
    escalated_count = 0
    if high_severity_decision_ids:
        escalated_count = _escalate_to_review(memory, high_severity_decision_ids)
        if escalated_count:
            _mm.save_project_memory(project, memory)

    return {
        "project": project,
        "files_scanned": report.files_scanned,
        "file_count": len(report.files_scanned),
        "claims_extracted": report.claims_extracted,
        "severity_distribution": severity_distribution,
        "findings": [
            {
                "id": f.id,
                "kind": f.kind,
                "claim_a_text": f.claim_a_text,
                "claim_a_source": f.claim_a_source,
                "claim_b_text": f.claim_b_text,
                "claim_b_source": f.claim_b_source,
                "contradiction_type": f.contradiction_type,
                "severity": f.severity,
                "similarity_score": f.similarity_score,
                "resolution_suggestion": f.resolution_suggestion,
            }
            for f in report.findings
        ],
        "finding_count": len(report.findings),
        "uncaptured_claims": [
            {"text": c.text, "source_file": c.source_file, "line_number": c.line_number}
            for c in report.uncaptured_claims[:100]
        ],
        "uncaptured_count": len(report.uncaptured_claims),
        "escalated_to_review": escalated_count,
    }
