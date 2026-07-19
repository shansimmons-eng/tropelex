"""
Prefetch Genealogy — tracks bundle assembly outcomes for feedback loops.

Records what was included in a prefetch bundle, what was referenced in use,
and what was requested but missing. Computes precision and recall-proxy to
guide future assembly.  Mirrors PromptGenealogy from agent_skills.py.

All business logic is pure; I/O is isolated in load/save helpers.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generic, TypeVar, Union

logger = logging.getLogger("tropelex.prefetch.genealogy")

T = TypeVar("T")

# ── Result types (mirrors core/ghost/preventive.py) ──────────────────────


@dataclass(frozen=True)
class Ok(Generic[T]):
    """Success wrapper — carries the resulting value."""
    value: T


@dataclass(frozen=True)
class Err:
    """Error wrapper — carries an error message and code."""
    error: str
    code: str = "UNKNOWN"
    details: dict[str, Any] | None = None


Result = Union[Ok[T], Err]


# ── Domain exception ─────────────────────────────────────────────────────


class PrefetchError(Exception):
    """Raised at IO boundaries for prefetch genealogy failures."""

    def __init__(
        self, message: str, code: str = "UNKNOWN", details: dict[str, Any] | None = None
    ):
        super().__init__(message)
        self.code = code
        self.details = details or {}


# ── Data models ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BundleRecord:
    """Outcome of a single prefetch bundle assembly."""

    bundle_id: str
    task: str
    included_ids: list[str]
    referenced_ids: list[str]
    requested_but_missing: list[str]
    precision: float
    recall_proxy: float
    timestamp: str


@dataclass(frozen=True)
class GenealogyStats:
    """Aggregated statistics across all recorded bundles."""

    total_bundles: int
    avg_precision: float
    avg_recall: float
    improvement_trend: float  # positive = getting better


# ── Pure computation helpers (< 50 lines each) ──────────────────────────


def compute_precision(included_ids: list[str], referenced_ids: list[str]) -> float:
    """Fraction of included_ids that were actually referenced.

    1.0 means everything included was useful; 0.0 means nothing was.
    Returns 1.0 when included_ids is empty (vacuously true).
    """
    if not included_ids:
        return 1.0
    referenced_set = set(referenced_ids)
    hits = sum(1 for iid in included_ids if iid in referenced_set)
    return hits / len(included_ids)


def compute_recall_proxy(
    included_ids: list[str], requested_but_missing: list[str]
) -> float:
    """Proxy for recall: fraction of (included + missing) that were missing.

    Lower is better — 0.0 means nothing was missing.
    Returns 0.0 when both lists are empty (nothing to miss).
    """
    total = len(included_ids) + len(requested_but_missing)
    if total == 0:
        return 0.0
    return len(requested_but_missing) / total


def _now_iso() -> str:
    """Current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


# ── I/O helpers (isolated, raise PrefetchError) ──────────────────────────


def _ensure_parent(path: Path) -> None:
    """Create parent directories for *path* if they don't exist."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PrefetchError(
            f"Cannot create directory {path.parent}: {exc}",
            code="IO_ERROR",
        ) from exc


def load_genealogy(storage_path: Path) -> dict:
    """Load existing genealogy JSON, return empty structure if missing/corrupt."""
    if not storage_path.exists():
        return {"bundles": [], "stats": {}, "created": _now_iso()}
    try:
        raw = json.loads(storage_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {"bundles": [], "stats": {}, "created": _now_iso()}
        raw.setdefault("bundles", [])
        raw.setdefault("stats", {})
        raw.setdefault("created", _now_iso())
        return raw
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Corrupt genealogy at %s, starting fresh: %s", storage_path, exc)
        return {"bundles": [], "stats": {}, "created": _now_iso()}


def _save_genealogy(storage_path: Path, data: dict) -> None:
    """Persist genealogy dict to JSON. Raises PrefetchError on failure."""
    _ensure_parent(storage_path)
    try:
        storage_path.write_text(
            json.dumps(data, indent=2, default=str), encoding="utf-8"
        )
    except OSError as exc:
        raise PrefetchError(
            f"Failed to write genealogy to {storage_path}: {exc}",
            code="IO_ERROR",
        ) from exc


# ── Public API ───────────────────────────────────────────────────────────


def record_bundle_outcome(
    bundle_id: str,
    task: str,
    included_ids: list[str],
    referenced_ids: list[str],
    requested_but_missing: list[str],
    storage_path: Path,
) -> Result[BundleRecord]:
    """Record what happened after a bundle was assembled.

    Computes precision and recall_proxy, persists to *storage_path*, and
    returns the resulting BundleRecord wrapped in Ok, or Err on failure.
    """
    if not bundle_id:
        return Err(error="bundle_id must not be empty", code="VALIDATION_ERROR")
    if not task:
        return Err(error="task must not be empty", code="VALIDATION_ERROR")

    precision = compute_precision(included_ids, referenced_ids)
    recall = compute_recall_proxy(included_ids, requested_but_missing)

    record = BundleRecord(
        bundle_id=bundle_id,
        task=task,
        included_ids=list(included_ids),
        referenced_ids=list(referenced_ids),
        requested_but_missing=list(requested_but_missing),
        precision=round(precision, 4),
        recall_proxy=round(recall, 4),
        timestamp=_now_iso(),
    )

    try:
        data = load_genealogy(storage_path)
        data["bundles"].append(_bundle_to_dict(record))
        # Keep last 500 bundles
        if len(data["bundles"]) > 500:
            data["bundles"] = data["bundles"][-500:]
        _save_genealogy(storage_path, data)
        return Ok(value=record)
    except PrefetchError as exc:
        return Err(error=str(exc), code=exc.code, details=exc.details)


def _bundle_to_dict(record: BundleRecord) -> dict[str, Any]:
    """Convert a BundleRecord to a plain dict for JSON serialisation."""
    return {
        "bundle_id": record.bundle_id,
        "task": record.task,
        "included_ids": record.included_ids,
        "referenced_ids": record.referenced_ids,
        "requested_but_missing": record.requested_but_missing,
        "precision": record.precision,
        "recall_proxy": record.recall_proxy,
        "timestamp": record.timestamp,
    }


def _improvement_trend(bundles: list[dict]) -> float:
    """Slope of precision over the last 20 bundles; positive = improving."""
    recent = bundles[-20:]
    if len(recent) < 2:
        return 0.0
    n = len(recent)
    xs = list(range(n))
    ys = [b.get("precision", 0) for b in recent]
    x_mean = sum(xs) / n
    y_mean = sum(ys) / n
    num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    den = sum((x - x_mean) ** 2 for x in xs)
    return round(num / den, 6) if den else 0.0


def get_bundle_stats(storage_path: Path) -> Result[GenealogyStats]:
    """Aggregate stats across all recorded bundles.

    Returns avg_precision, avg_recall, total_bundles, and improvement_trend.
    """
    try:
        data = load_genealogy(storage_path)
        bundles = data.get("bundles", [])
    except PrefetchError as exc:
        return Err(error=str(exc), code=exc.code, details=exc.details)

    if not bundles:
        return Ok(value=GenealogyStats(
            total_bundles=0, avg_precision=0.0, avg_recall=0.0, improvement_trend=0.0,
        ))

    avg_p = sum(b.get("precision", 0) for b in bundles) / len(bundles)
    avg_r = sum(b.get("recall_proxy", 0) for b in bundles) / len(bundles)
    trend = _improvement_trend(bundles)

    return Ok(value=GenealogyStats(
        total_bundles=len(bundles),
        avg_precision=round(avg_p, 4),
        avg_recall=round(avg_r, 4),
        improvement_trend=round(trend, 6),
    ))
