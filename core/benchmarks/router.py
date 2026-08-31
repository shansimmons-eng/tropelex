"""
Benchmarks — FastAPI router.

Endpoints for sharing anonymized structural statistics and comparing against
aggregate benchmarks. Local-only within one install by default: "share"
writes into this install's own memory/benchmarks/ directory, and "aggregate"
/"compare" only see stats from projects on this install.

True cross-install comparison (e.g. comparing your laptop's projects against
another machine's) happens via export/import: export bundles this install's
shared stats into one portable JSON file, which you hand to the other
install (copy, email, USB, whatever) and it imports the bundle into its own
benchmarks directory. No networking involved — a plain file exchange.
"""

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.benchmarks.anonymizer import anonymize_project
from core.benchmarks.aggregator import aggregate_benchmarks, compare_to_aggregate
from core.memory.manager import MemoryManager
from core.version import MEMORY_SCHEMA_VERSION

logger = logging.getLogger("tropelex.benchmarks")

benchmarks_router = APIRouter(prefix="/api/memory", tags=["benchmarks"])

_mm = MemoryManager()
_BENCHMARKS_DIR = Path(_mm.memory_dir) / "benchmarks"
_LEGACY_FEDERATION_DIR = Path(_mm.memory_dir) / "federation"


def _load_memory(project: str) -> dict[str, Any]:
    if project not in _mm.list_projects():
        raise HTTPException(status_code=404, detail=f"Project '{project}' not found")
    return _mm.get_project_memory(project)


def _ensure_benchmarks_dir() -> Path:
    """Return the benchmarks directory, migrating data from the old
    memory/federation/ path (pre-rename) on first use if present."""
    if not _BENCHMARKS_DIR.exists() and _LEGACY_FEDERATION_DIR.exists():
        _LEGACY_FEDERATION_DIR.rename(_BENCHMARKS_DIR)
    _BENCHMARKS_DIR.mkdir(parents=True, exist_ok=True)
    return _BENCHMARKS_DIR


def _load_shared_stats() -> list[dict[str, Any]]:
    """Load all shared anonymized stats from the benchmarks directory."""
    bench_dir = _ensure_benchmarks_dir()
    stats = []
    for f in bench_dir.glob("*.json"):
        try:
            stats.append(json.loads(f.read_text()))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Skipping corrupt benchmarks file %s: %s", f, exc)
    return stats


def _atomic_write(path: Path, data: str) -> None:
    """Write data atomically via temp file + replace."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _save_shared_stats(project_hash: str, stats: dict[str, Any]) -> None:
    """Save anonymized stats to the benchmarks directory."""
    bench_dir = _ensure_benchmarks_dir()
    path = bench_dir / f"{project_hash}.json"
    try:
        _atomic_write(path, json.dumps(stats, indent=2))
    except (OSError, TypeError) as exc:
        logger.error("Failed to save benchmark stats: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


_STATS_FIELDS = (
    "project_hash", "tech_stack", "decision_count", "reversal_rate",
    "avg_confidence", "category_distribution", "avg_safety_score",
    "risk_level_distribution",
)


def _stats_dict_to_object(s: dict[str, Any]):
    from core.benchmarks import AnonymizedStats

    return AnonymizedStats(
        project_hash=s["project_hash"],
        tech_stack=tuple(s.get("tech_stack", [])),
        decision_count=s.get("decision_count", 0),
        reversal_rate=s.get("reversal_rate", 0.0),
        avg_confidence=s.get("avg_confidence", 0.0),
        category_distribution=s.get("category_distribution", {}),
        avg_safety_score=s.get("avg_safety_score", 1.0),
        risk_level_distribution=s.get("risk_level_distribution", {}),
    )


def _load_stats_objects() -> list:
    stats_list = []
    for s in _load_shared_stats():
        try:
            stats_list.append(_stats_dict_to_object(s))
        except (KeyError, TypeError):
            continue
    return stats_list


# --- Pydantic models ---


class BenchmarkShareRequest(BaseModel):
    opt_in: bool = Field(False, description="Whether to opt in to benchmark sharing")


class BenchmarkImportRequest(BaseModel):
    stats: list[dict[str, Any]] = Field(..., description="Bundle exported from another install")
    source_label: str = Field("", max_length=100, description="Optional label for where this came from")
    schema_version: int | None = Field(
        None, description="The bundle's own schema_version, echoed from GET /benchmarks/export's "
        "envelope -- optional so older bundles (predating this field) still import, but if given "
        "and it doesn't match this install's, invalid-entry skips get a real diagnostic instead of "
        "an opaque count.",
    )


# --- Endpoints ---


@benchmarks_router.post("/{project}/benchmarks/share")
async def benchmarks_share(
    project: str,
    body: BenchmarkShareRequest,
) -> dict[str, Any]:
    """Share anonymized structural statistics for this project."""
    memory = _load_memory(project)

    result = anonymize_project(memory)

    if hasattr(result, "error"):
        raise HTTPException(status_code=500, detail=result.error)

    stats = result.value

    if body.opt_in:
        # Convert frozen dataclass to dict for storage
        stats_dict = {
            "project_hash": stats.project_hash,
            "tech_stack": list(stats.tech_stack),
            "decision_count": stats.decision_count,
            "reversal_rate": stats.reversal_rate,
            "avg_confidence": stats.avg_confidence,
            "category_distribution": dict(stats.category_distribution),
            "avg_safety_score": stats.avg_safety_score,
            "risk_level_distribution": dict(stats.risk_level_distribution),
        }
        _save_shared_stats(stats.project_hash, stats_dict)

    return {
        "project_hash": stats.project_hash,
        "opted_in": body.opt_in,
        "shared": body.opt_in,
        "stats": {
            "tech_stack": list(stats.tech_stack),
            "decision_count": stats.decision_count,
            "reversal_rate": stats.reversal_rate,
            "avg_confidence": stats.avg_confidence,
            "avg_safety_score": stats.avg_safety_score,
            "risk_level_distribution": dict(stats.risk_level_distribution),
        },
    }


@benchmarks_router.get("/benchmarks/aggregate")
async def benchmarks_aggregate() -> dict[str, Any]:
    """Get aggregate benchmarks across all stats shared on this install
    (including anything imported from other installs via /benchmarks/import)."""
    stats_list = _load_stats_objects()

    if not stats_list:
        return {
            "total_projects": 0,
            "aggregate": None,
            "message": "No benchmark data available yet",
        }

    agg_result = aggregate_benchmarks(stats_list)

    if hasattr(agg_result, "error"):
        raise HTTPException(status_code=500, detail=agg_result.error)

    agg = agg_result.value

    return {
        "total_projects": len(stats_list),
        "aggregate": {
            "tech_stack": list(agg.tech_stack),
            "decision_count": agg.decision_count,
            "reversal_rate": agg.reversal_rate,
            "avg_confidence": agg.avg_confidence,
            "category_distribution": dict(agg.category_distribution),
            "avg_safety_score": agg.avg_safety_score,
            "risk_level_distribution": dict(agg.risk_level_distribution),
        },
    }


@benchmarks_router.get("/{project}/benchmarks/compare")
async def benchmarks_compare(project: str) -> dict[str, Any]:
    """Compare this project against the aggregate benchmark."""
    memory = _load_memory(project)

    proj_result = anonymize_project(memory)
    if hasattr(proj_result, "error"):
        raise HTTPException(status_code=500, detail=proj_result.error)

    stats_list = _load_stats_objects()
    if not stats_list:
        return {
            "project_hash": proj_result.value.project_hash,
            "comparison": None,
            "message": "No benchmark data to compare against",
        }

    agg_result = aggregate_benchmarks(stats_list)
    if hasattr(agg_result, "error"):
        raise HTTPException(status_code=500, detail=agg_result.error)

    comp_result = compare_to_aggregate(proj_result.value, agg_result.value)
    if hasattr(comp_result, "error"):
        raise HTTPException(status_code=500, detail=comp_result.error)

    comp = comp_result.value

    return {
        "project_hash": comp.project_hash,
        "compared_to_aggregate": {
            "tech_stack": list(comp.compared_to_aggregate.tech_stack),
            "decision_count": comp.compared_to_aggregate.decision_count,
            "avg_safety_score": comp.compared_to_aggregate.avg_safety_score,
            "risk_level_distribution": dict(comp.compared_to_aggregate.risk_level_distribution),
        },
        "deviation": dict(comp.deviation),
        "percentile": dict(comp.percentile),
    }


@benchmarks_router.get("/benchmarks/export")
async def benchmarks_export() -> dict[str, Any]:
    """Export this install's shared benchmark stats as a portable bundle.

    Hand the returned JSON to another Tropelex install (file copy, no
    network call) and POST it to /benchmarks/import there to compare
    across machines.
    """
    shared = _load_shared_stats()
    return {
        "schema_version": MEMORY_SCHEMA_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "count": len(shared),
        "stats": shared,
    }


@benchmarks_router.post("/benchmarks/import")
async def benchmarks_import(body: BenchmarkImportRequest) -> dict[str, Any]:
    """Import a bundle exported from another install into this install's
    benchmarks directory, so /benchmarks/aggregate and /compare include it.

    Entries are validated and merged by project_hash — an import never
    overwrites a project_hash already present locally (that would let a
    malformed or hostile bundle silently clobber this install's own shared
    stats), so re-importing the same bundle, or importing an overlapping
    bundle, is safe: pre-existing entries win and only new hashes are added.
    """
    bench_dir = _ensure_benchmarks_dir()
    existing_hashes = {p.stem for p in bench_dir.glob("*.json")}

    imported = 0
    skipped_existing = 0
    skipped_invalid = 0

    for entry in body.stats:
        if not isinstance(entry, dict) or "project_hash" not in entry:
            skipped_invalid += 1
            continue
        try:
            _stats_dict_to_object(entry)  # validates shape/types
        except (KeyError, TypeError, ValueError):
            skipped_invalid += 1
            continue

        project_hash = entry["project_hash"]
        if project_hash in existing_hashes:
            skipped_existing += 1
            continue

        _save_shared_stats(project_hash, {k: entry.get(k) for k in _STATS_FIELDS})
        existing_hashes.add(project_hash)
        imported += 1

    schema_mismatch = (
        body.schema_version is not None and body.schema_version != MEMORY_SCHEMA_VERSION
    )
    warning = (
        f"Bundle schema_version ({body.schema_version}) doesn't match this install's "
        f"({MEMORY_SCHEMA_VERSION}) -- the {skipped_invalid} skipped-invalid entr"
        f"{'y is' if skipped_invalid == 1 else 'ies are'} likely a version mismatch, not corruption."
        if schema_mismatch and skipped_invalid > 0 else None
    )
    return {
        "imported": imported,
        "skipped_existing": skipped_existing,
        "skipped_invalid": skipped_invalid,
        "bundle_schema_version": body.schema_version,
        "current_schema_version": MEMORY_SCHEMA_VERSION,
        "warning": warning,
        "source_label": body.source_label,
        "total_local_after_import": len(existing_hashes),
    }
