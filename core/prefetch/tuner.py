"""
Tropelex Prefetch Tuner — skill-aware budget and compression tuning.

Adjusts prefetch parameters based on agent proficiency per task category.
All functions are pure: no I/O, same input → same output.
"""

from dataclasses import dataclass
from typing import Any, Generic, TypeVar, Union

T = TypeVar("T")


# ── Result types (mirrors core/ghost/preventive.py pattern) ──────────────


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


# ── Data model ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TuningResult:
    """Result of skill-aware tuning for prefetch."""
    adjusted_budget: int
    adjusted_weights: dict[str, float]
    compression_level: int  # 1=light, 2=moderate, 3=aggressive
    reasoning: str


# ── Category keywords for task classification ────────────────────────────

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "backend": ["api", "server", "database", "sql", "route", "endpoint", "auth", "middleware"],
    "frontend": ["ui", "component", "react", "css", "html", "layout", "button", "form"],
    "testing": ["test", "spec", "mock", "assert", "pytest", "coverage", "tdd"],
    "devops": ["deploy", "ci", "cd", "docker", "kubernetes", "pipeline", "infra"],
    "config": ["config", "settings", "env", "yml", "json", "toml", "ini"],
    "data": ["data", "etl", "transform", "ingest", "csv", "parquet", "pipeline"],
}


# ── Public API ───────────────────────────────────────────────────────────


def estimate_task_category(task_text: str) -> Result[str]:
    """Estimate dominant task category from keyword analysis."""
    if not task_text or not task_text.strip():
        return Err(error="Empty task text", code="VALIDATION_ERROR")

    text_lower = task_text.lower()
    scores: dict[str, int] = {cat: 0 for cat in _CATEGORY_KEYWORDS}

    for category, keywords in _CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text_lower:
                scores[category] += 1

    best_cat = max(scores, key=lambda k: scores[k])
    if scores[best_cat] == 0:
        return Err(error="No category keywords found", code="NO_CATEGORY")

    return Ok(value=best_cat)


def get_proficiency_level(skill_graph: dict[str, Any], category: str) -> Result[str]:
    """Get proficiency level for a category from skill graph data.

    Returns one of: 'novice', 'learning', 'competent', 'proficient', 'expert'.
    """
    if not skill_graph or not isinstance(skill_graph, dict):
        return Err(error="Invalid skill graph", code="VALIDATION_ERROR")

    skills = skill_graph.get("skills", {})
    skill_entry = skills.get(category, {})
    score = skill_entry.get("score", 0.0)

    if score >= 0.9:
        return Ok(value="expert")
    elif score >= 0.7:
        return Ok(value="proficient")
    elif score >= 0.5:
        return Ok(value="competent")
    elif score >= 0.3:
        return Ok(value="learning")
    else:
        return Ok(value="novice")


def tune_weights(
    base_weights: dict[str, float],
    skill_graph: dict[str, Any],
    task_categories: list[str],
    max_delta: float = 0.2,
) -> Result[dict[str, float]]:
    """Adjust relevance weights based on proficiency in task categories.

    Novice → widen relevance (boost category weight).
    Expert → tighten relevance (boost confidence weight).
    Returns dict with same keys as base_weights, values adjusted ±max_delta.
    """
    if not base_weights:
        return Err(error="Base weights cannot be empty", code="VALIDATION_ERROR")
    if not task_categories:
        return Err(error="No task categories provided", code="VALIDATION_ERROR")

    adjusted = dict(base_weights)

    # Aggregate proficiency across categories
    for category in task_categories:
        prof_result = get_proficiency_level(skill_graph, category)
        if isinstance(prof_result, Err):
            continue  # Unknown category → skip adjustment
        proficiency = prof_result.value

        if proficiency == "novice":
            adjusted["w_category"] = min(
                1.0, adjusted.get("w_category", 0.25) + max_delta
            )
            adjusted["w_confidence"] = max(
                0.0, adjusted.get("w_confidence", 0.25) - max_delta * 0.5
            )
        elif proficiency == "expert":
            adjusted["w_confidence"] = min(
                1.0, adjusted.get("w_confidence", 0.25) + max_delta
            )
            adjusted["w_category"] = max(
                0.0, adjusted.get("w_category", 0.25) - max_delta * 0.5
            )

    return Ok(value=adjusted)


def pick_compression_level(
    borderline_items: list[str],
    genealogy: dict[str, Any],
) -> Result[int]:
    """Pick compression level based on borderline items and genealogy.

    Uses PromptGenealogy.get_best_strategy() pattern to map historical
    effectiveness to compression level:
      Level 1: light (signatures only)
      Level 2: moderate (summarize long text)
      Level 3: aggressive (dictionary + truncation)
    """
    if not borderline_items:
        return Err(error="No borderline items provided", code="VALIDATION_ERROR")
    if genealogy is None or not isinstance(genealogy, dict):
        return Err(error="Invalid genealogy data", code="VALIDATION_ERROR")

    # Check genealogy for best strategy
    best_strategy = genealogy.get("best_strategy")
    if best_strategy:
        level = _strategy_to_level(best_strategy)
        if level is not None:
            return Ok(value=level)

    # Fallback: heuristic based on content length
    avg_length = sum(len(item) for item in borderline_items) / len(borderline_items)
    if avg_length < 200:
        return Ok(value=1)
    elif avg_length < 1000:
        return Ok(value=2)
    else:
        return Ok(value=3)


def tune_for_task(
    task_text: str,
    agent_skills: dict[str, Any],
    base_budget: int,
    base_weights: dict[str, float],
) -> Result[TuningResult]:
    """Tune prefetch parameters based on agent skill proficiency.

    Novice → widen budget by 20%, lower relevance cutoff.
    Expert → tighten budget by 15% (less context needed).
    Unknown category → use base values.
    """
    if not task_text or not task_text.strip():
        return Err(error="Empty task text", code="VALIDATION_ERROR")
    if base_budget <= 0:
        return Err(error="Budget must be positive", code="VALIDATION_ERROR")
    if not base_weights:
        return Err(error="Base weights cannot be empty", code="VALIDATION_ERROR")

    cat_result = estimate_task_category(task_text)
    if isinstance(cat_result, Err):
        return Ok(value=TuningResult(
            adjusted_budget=base_budget, adjusted_weights=base_weights,
            compression_level=1, reasoning="No category detected, using base values",
        ))

    category = cat_result.value
    prof_result = get_proficiency_level(agent_skills, category)
    if isinstance(prof_result, Err):
        return Ok(value=TuningResult(
            adjusted_budget=base_budget, adjusted_weights=base_weights,
            compression_level=1,
            reasoning=f"No proficiency data for {category}, using base values",
        ))

    return _apply_tuning(base_budget, base_weights, category, prof_result.value)


def _apply_tuning(
    base_budget: int,
    base_weights: dict[str, float],
    category: str,
    proficiency: str,
) -> Result[TuningResult]:
    """Apply tuning adjustments based on proficiency."""
    adjusted_budget, reasoning = _adjust_budget(base_budget, proficiency, category)
    weights_result = tune_weights(base_weights, {}, [category])
    adjusted_weights = weights_result.value if isinstance(weights_result, Ok) else base_weights
    compression_level = _compression_for_proficiency(proficiency)

    return Ok(value=TuningResult(
        adjusted_budget=adjusted_budget,
        adjusted_weights=adjusted_weights,
        compression_level=compression_level,
        reasoning=reasoning,
    ))


# ── Internal helpers ─────────────────────────────────────────────────────


def _adjust_budget(
    base_budget: int, proficiency: str, category: str
) -> tuple[int, str]:
    """Adjust budget based on proficiency. Returns (adjusted_budget, reasoning)."""
    if proficiency == "novice":
        return int(base_budget * 1.2), f"Novice in {category}: widened budget by 20%"
    elif proficiency == "expert":
        return int(base_budget * 0.85), f"Expert in {category}: tightened budget by 15%"
    else:
        return base_budget, f"{proficiency.capitalize()} in {category}: using base budget"


def _compression_for_proficiency(proficiency: str) -> int:
    """Map proficiency to compression level."""
    if proficiency in ("novice", "learning"):
        return 1  # Light compression — more context needed
    elif proficiency == "expert":
        return 3  # Aggressive — expert needs less detail
    else:
        return 2  # Moderate for competent/proficient


def _strategy_to_level(strategy: str) -> int | None:
    """Map a genealogy strategy name to a compression level."""
    strategy_lower = strategy.lower()
    if "signatures" in strategy_lower:
        return 1
    elif "summarize" in strategy_lower:
        return 2
    elif "dictionary" in strategy_lower or "truncat" in strategy_lower:
        return 3
    return None
