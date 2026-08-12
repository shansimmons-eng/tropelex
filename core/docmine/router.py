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

from dataclasses import asdict

from core.docmine.combined import combine_doc_and_ghost_findings
from core.docmine.detector import mine_markdown_files
from core.docmine.extractor import extract_claims
from core.ghost.preventive import check_diff_for_warnings
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

    A human already reviewed this decision at least once — respect that
    resolution rather than re-flagging it every time the doc drift is
    re-scanned. Without this check, approving a decision (which sets
    requires_review=False) gets undone on the very next /docmine/scan call
    as long as the doc/decision mismatch is still there — this router's own
    copy of the exact bug already fixed once in Contradiction Detection's
    _escalate_to_review and in _apply_persona_market_escalation, just never
    applied here too. Confirmed live against the real tropelex project:
    4 previously-approved decisions were still matched by current
    high-severity doc_vs_decision findings, meaning the next approval would
    have been silently undone on the next scan.
    """
    escalated = 0
    for d in memory.get("decisions", []):
        if d.get("id") not in decision_ids:
            continue
        safety = d.setdefault("safety_metadata", {})
        if safety.get("requires_review"):
            continue
        if d.get("safety_reviews"):
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


def _resolve_scan_targets(paths: list[str], scan_root: Path) -> list[Path]:
    """Resolve a docmine request's `paths` (or, if empty, every .md file
    under scan_root) into a concrete list of files to read. Shared by
    scan_markdown and combined_drift_check so the "no scope-escape, no
    missing target" validation only lives in one place.
    """
    if paths:
        targets: list[Path] = []
        for raw in paths:
            candidate = (scan_root / raw).resolve()
            if scan_root.resolve() not in candidate.parents and candidate != scan_root.resolve():
                raise HTTPException(status_code=422, detail=f"Path escapes repo root: {raw}")
            if candidate.is_dir():
                targets.extend(_discover_markdown_files(candidate))
            elif candidate.is_file() and candidate.suffix == ".md":
                targets.append(candidate)
            else:
                raise HTTPException(status_code=404, detail=f"Not a markdown file or directory: {raw}")
    else:
        targets = _discover_markdown_files(scan_root)

    if not targets:
        raise HTTPException(status_code=404, detail="No markdown files found to scan")
    return targets


def _run_docmine(paths: list[str], decisions: list[dict[str, Any]], scan_root: Path):
    """Resolve targets, extract claims, and run the detector — the part of
    scan_markdown that combined_drift_check also needs. Returns a
    DocMineReport (core/docmine/__init__.py)."""
    targets = _resolve_scan_targets(paths, scan_root)

    claims = []
    for path in targets:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("docmine: skipping unreadable file %s: %s", path, exc)
            continue
        rel_path = str(path.relative_to(scan_root))
        claims.extend(extract_claims(text, rel_path))

    return mine_markdown_files(claims, decisions)


def _scan_root_for(memory: dict[str, Any]) -> tuple[Path, str]:
    """Pick the markdown scan root for a project: its own synced repo if
    known, else this Tropelex install's own repo -- and say which one, so
    callers can surface it rather than silently mixing the wrong repo's
    docs into a project's findings (see get_project_repo_path).
    """
    from core.git_integration import get_project_repo_path

    project_repo = get_project_repo_path(memory)
    if project_repo:
        return Path(project_repo), "project_repo"
    return BASE_DIR, "tropelex_repo_fallback"


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
    scan_root, scan_root_source = _scan_root_for(memory)

    report = _run_docmine(body.paths, decisions, scan_root)
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
        "scan_root": str(scan_root),
        "scan_root_source": scan_root_source,
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


class CombinedDriftRequest(BaseModel):
    """Request body for the combined Doc Mining + Ghost drift check (#55).

    diff: unified diff text to check against decisions, same as ghost-check.
    paths: same as DocMineRequest — specific files/directories to scan,
        relative to the repo root; omit to scan every .md file in the repo.
    """
    diff: str = Field(..., min_length=1, max_length=100000)
    paths: list[str] = Field(default_factory=list, max_length=200)


@docmine_router.post("/{project}/drift/combined-check")
async def combined_drift_check(project: str, body: CombinedDriftRequest) -> dict[str, Any]:
    """Run Doc Mining and Preventive Ghost Checks together and flag any
    decision both independently drifted from (#55).

    A single-source finding is a signal; the same decision getting flagged
    by both an out-of-date doc AND a proposed code diff at once is
    stronger evidence than either alone. This is a pure join over the two
    detectors' existing output — no new detection logic, no persistence
    beyond what each detector already does (Doc Mining's own
    high-severity auto-escalation still runs exactly as it does in
    /docmine/scan; this endpoint doesn't add a second escalation path).
    """
    memory = _load_memory(project)
    decisions = memory.get("decisions", [])
    scan_root, scan_root_source = _scan_root_for(memory)

    doc_report = _run_docmine(body.paths, decisions, scan_root)

    ghost_result = check_diff_for_warnings(memory, body.diff)
    if hasattr(ghost_result, "error"):
        code = getattr(ghost_result, "code", "UNKNOWN")
        status = 404 if code == "NOT_FOUND" else 500
        raise HTTPException(status_code=status, detail=ghost_result.error)
    ghost_warnings = ghost_result.value

    combined = combine_doc_and_ghost_findings(
        [asdict(f) for f in doc_report.findings],
        ghost_warnings,
    )

    return {
        "project": project,
        "scan_root": str(scan_root),
        "scan_root_source": scan_root_source,
        "combined_alerts": [asdict(c) for c in combined],
        "total_combined": len(combined),
        "doc_findings_total": len(doc_report.findings),
        "ghost_warnings_total": len(ghost_warnings),
    }
