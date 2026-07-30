"""Benchmarks aggregator — pure functions for computing cross-install benchmarks.

All functions are deterministic, side-effect-free, and return Result types.
"""
from __future__ import annotations

from collections import Counter
from itertools import chain

from . import AnonymizedStats, BenchmarkComparison, Err, Ok, Result


def _safe_mean(values: list[float]) -> float:
    """Mean of a list, 0.0 if empty."""
    return round(sum(values) / len(values), 4) if values else 0.0


def _merge_distributions(dists: list[dict[str, int]]) -> dict[str, int]:
    """Sum category distributions across multiple stats."""
    merged: Counter[str] = Counter()
    for d in dists:
        merged.update(d)
    return dict(merged)


def aggregate_benchmarks(stats_list: list[AnonymizedStats]) -> Result[AnonymizedStats]:
    """Compute aggregate statistics across all participating installs."""
    if not stats_list:
        return Err(error="Empty stats list", code="VALIDATION_ERROR")

    all_tech = set(chain.from_iterable(s.tech_stack for s in stats_list))
    all_dists = [s.category_distribution for s in stats_list]
    all_risk_dists = [s.risk_level_distribution for s in stats_list]

    return Ok(value=AnonymizedStats(
        project_hash="aggregate",
        tech_stack=sorted(all_tech),
        decision_count=sum(s.decision_count for s in stats_list),
        reversal_rate=_safe_mean([s.reversal_rate for s in stats_list]),
        avg_confidence=_safe_mean([s.avg_confidence for s in stats_list]),
        category_distribution=_merge_distributions(all_dists),
        avg_safety_score=_safe_mean([s.avg_safety_score for s in stats_list]),
        risk_level_distribution=_merge_distributions(all_risk_dists),
    ))


def compute_percentiles(
    stats_list: list[AnonymizedStats], project: AnonymizedStats
) -> Result[dict[str, float]]:
    """Rank project against all installs on each metric (0–100 percentile)."""
    if not stats_list:
        return Err(error="Empty stats list", code="VALIDATION_ERROR")

    n = len(stats_list)
    metrics = ("decision_count", "reversal_rate", "avg_confidence", "avg_safety_score")
    percentiles: dict[str, float] = {}

    for metric in metrics:
        values = sorted(getattr(s, metric) for s in stats_list)
        project_val = getattr(project, metric)
        below = sum(1 for v in values if v < project_val)
        percentiles[metric] = round((below / n) * 100, 1)

    return Ok(value=percentiles)


def compare_to_aggregate(
    project_stats: AnonymizedStats, aggregate: AnonymizedStats
) -> Result[BenchmarkComparison]:
    """Compare a single project's stats to the aggregate benchmark."""
    metrics = ("decision_count", "reversal_rate", "avg_confidence", "avg_safety_score")
    deviation: dict[str, float] = {}

    for metric in metrics:
        p_val = getattr(project_stats, metric)
        a_val = getattr(aggregate, metric)
        if a_val != 0:
            deviation[metric] = round((p_val - a_val) / a_val, 4)
        else:
            deviation[metric] = 0.0

    return Ok(value=BenchmarkComparison(
        project_hash=project_stats.project_hash,
        compared_to_aggregate=aggregate,
        deviation=deviation,
        percentile={},  # filled by caller using compute_percentiles
    ))
