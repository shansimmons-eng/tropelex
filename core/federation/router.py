"""
Federated Benchmarking — FastAPI router.

Endpoints for sharing anonymized structural statistics
and comparing against aggregate benchmarks.
"""

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.federation import (
    Ok as FedOk,
    FederationRequest,
)
from core.federation.anonymizer import anonymize_project
from core.federation.aggregator import aggregate_benchmarks, compare_to_aggregate
from core.memory.manager import MemoryManager

logger = logging.getLogger("tropelex.federation")

federation_router = APIRouter(prefix="/api/memory", tags=["federation"])

_mm = MemoryManager()
_FEDERATION_DIR = Path(_mm.memory_dir) / "federation"


def _load_memory(project: str) -> dict[str, Any]:
    if project not in _mm.list_projects():
        raise HTTPException(status_code=404, detail=f"Project '{project}' not found")
    return _mm.get_project_memory(project)


def _ensure_federation_dir() -> Path:
    _FEDERATION_DIR.mkdir(parents=True, exist_ok=True)
    return _FEDERATION_DIR


def _load_shared_stats() -> list[dict[str, Any]]:
    """Load all shared anonymized stats from federation directory."""
    fed_dir = _ensure_federation_dir()
    stats = []
    for f in fed_dir.glob("*.json"):
        try:
            stats.append(json.loads(f.read_text()))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Skipping corrupt federation file %s: %s", f, exc)
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
    """Save anonymized stats to federation directory."""
    fed_dir = _ensure_federation_dir()
    path = fed_dir / f"{project_hash}.json"
    try:
        _atomic_write(path, json.dumps(stats, indent=2))
    except (OSError, TypeError) as exc:
        logger.error("Failed to save federation stats: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# --- Pydantic models ---


class FederationShareRequest(BaseModel):
    opt_in: bool = Field(False, description="Whether to opt in to federation")


# --- Endpoints ---


@federation_router.post("/{project}/federation/share")
async def federation_share(
    project: str,
    body: FederationShareRequest,
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
        },
    }


@federation_router.get("/federation/benchmarks")
async def federation_benchmarks() -> dict[str, Any]:
    """Get aggregate benchmarks across all federated installs."""
    shared = _load_shared_stats()

    if not shared:
        return {
            "total_projects": 0,
            "aggregate": None,
            "message": "No federated data available yet",
        }

    # Convert dicts back to AnonymizedStats for aggregation
    from core.federation import AnonymizedStats
    stats_list = []
    for s in shared:
        try:
            stats_list.append(AnonymizedStats(
                project_hash=s["project_hash"],
                tech_stack=tuple(s.get("tech_stack", [])),
                decision_count=s.get("decision_count", 0),
                reversal_rate=s.get("reversal_rate", 0.0),
                avg_confidence=s.get("avg_confidence", 0.0),
                category_distribution=s.get("category_distribution", {}),
            ))
        except (KeyError, TypeError):
            continue

    if not stats_list:
        return {"total_projects": 0, "aggregate": None}

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
        },
    }


@federation_router.get("/{project}/federation/compare")
async def federation_compare(project: str) -> dict[str, Any]:
    """Compare this project against aggregate benchmarks."""
    memory = _load_memory(project)

    proj_result = anonymize_project(memory)
    if hasattr(proj_result, "error"):
        raise HTTPException(status_code=500, detail=proj_result.error)

    shared = _load_shared_stats()
    if not shared:
        return {
            "project_hash": proj_result.value.project_hash,
            "comparison": None,
            "message": "No federated data to compare against",
        }

    from core.federation import AnonymizedStats
    stats_list = []
    for s in shared:
        try:
            stats_list.append(AnonymizedStats(
                project_hash=s["project_hash"],
                tech_stack=tuple(s.get("tech_stack", [])),
                decision_count=s.get("decision_count", 0),
                reversal_rate=s.get("reversal_rate", 0.0),
                avg_confidence=s.get("avg_confidence", 0.0),
                category_distribution=s.get("category_distribution", {}),
            ))
        except (KeyError, TypeError):
            continue

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
        },
        "deviation": dict(comp.deviation),
        "percentile": dict(comp.percentile),
    }
