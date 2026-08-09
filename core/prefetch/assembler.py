"""
Tropelex Prefetch Assembler — budget-aware knapsack bundling.

Pure functions only — no I/O, no network, no file access.
Uses value-density greedy + exact0/1 DP for boundary optimization.
Records near-miss items for transparency.

Result type from code-quality.md: every fallible function returns Result.
"""

from dataclasses import dataclass, field
from typing import Any

from core.result import Err, Ok, Result  # noqa: F401 - re-exported for this module's consumers


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ScoredItem:
    """A candidate item with relevance score and token cost."""
    text: str
    token_estimate: int
    relevance_score: float
    source_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AssembledBundle:
    """Result of budget-aware assembly: included items + near-misses."""
    included: list[ScoredItem]
    near_misses: list[ScoredItem]
    total_tokens: int
    utilization: float
    item_count: int
    near_miss_count: int


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_NEAR_MISS_SCORE_THRESHOLD = 0.05   # items within 5% of boundary score
_MIN_RELEVANCE_NEAR_MISS = 0.3      # near-misses must score above this
_MAX_DP_ITEMS = 50                  # DP pass runs only for small N


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    """Rough token estimate accounting for subword tokenization.

    Uses word-count × 1.3 multiplier to approximate BPE/SentencePiece
    behavior where common subwords compress below 1 token/word on average
    but rare compounds inflate beyond it.
    """
    word_count = len(text.split())
    return max(1, int(word_count * 1.3))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _item_fits(item: ScoredItem, remaining_budget: int) -> bool:
    """True if item's token estimate fits within remaining budget."""
    return item.token_estimate <= remaining_budget


def _value_density(item: ScoredItem) -> float:
    """Relevance per token — higher is better for greedy fill."""
    if item.token_estimate <= 0:
        return 0.0
    return item.relevance_score / item.token_estimate


# ---------------------------------------------------------------------------
# Greedy fill (fast, ~optimal for well-sorted inputs)
# ---------------------------------------------------------------------------

def _greedy_fill(
    items: list[ScoredItem],
    budget: int,
) -> tuple[list[ScoredItem], int]:
    """Greedy value-density fill. Returns (included, total_tokens).

    Sorts by value-density descending, adds items while they fit.
    Pure: returns new list, never mutates input.
    """
    ranked = sorted(items, key=_value_density, reverse=True)
    included: list[ScoredItem] = []
    remaining = budget

    for item in ranked:
        if _item_fits(item, remaining):
            included.append(item)
            remaining -= item.token_estimate

    total_tokens = budget - remaining
    return included, total_tokens


# ---------------------------------------------------------------------------
# Exact0/1 knapsack DP (optimal for N ≤ _MAX_DP_ITEMS)
# ---------------------------------------------------------------------------

def _dp_reconstruct(
    prev: list[list[int]],
    items: list[ScoredItem],
    costs: list[int],
    budget: int,
) -> list[ScoredItem]:
    """Backtrack through DP table to recover optimal item set."""
    selected: list[ScoredItem] = []
    j = budget
    for i in range(len(items), 0, -1):
        if prev[i][j] != prev[i - 1][j]:
            selected.append(items[i - 1])
            j -= costs[i - 1]
    return selected


def _dp_knapsack(
    items: list[ScoredItem],
    budget: int,
) -> list[ScoredItem]:
    """Exact0/1 knapsack via dynamic programming.

    Uses token costs as weights and relevance × 1000 as integer values.
    O(N × budget) — feasible for N ≤ 50 and typical token budgets.
    Returns the optimal subset of items.
    """
    n = len(items)
    if n == 0 or budget <= 0:
        return []

    costs = [max(1, it.token_estimate) for it in items]
    values = [int(it.relevance_score * 1000) for it in items]

    prev = [[0] * (budget + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(budget + 1):
            prev[i][j] = prev[i - 1][j]
            if costs[i - 1] <= j:
                val = prev[i - 1][j - costs[i - 1]] + values[i - 1]
                if val > prev[i][j]:
                    prev[i][j] = val

    return _dp_reconstruct(prev, items, costs, budget)


# ---------------------------------------------------------------------------
# Boundary detection + near-miss identification
# ---------------------------------------------------------------------------

def find_boundary_items(
    scored: list[ScoredItem],
    budget: int,
) -> tuple[list[ScoredItem], list[ScoredItem]]:
    """Split scored items into included/excluded at the budget boundary.

    Items excluded but with relevance within 5% of the lowest included
    item's score are flagged as near-misses.  Excluded items must also
    score above _MIN_RELEVANCE_NEAR_MISS to qualify.
    """
    if not scored or budget <= 0:
        return ([], list(scored))

    ranked = sorted(scored, key=_value_density, reverse=True)
    included: list[ScoredItem] = []
    remaining = budget

    for item in ranked:
        if _item_fits(item, remaining):
            included.append(item)
            remaining -= item.token_estimate

    if not included:
        return ([], list(scored))

    boundary_score = min(it.relevance_score for it in included)
    threshold = boundary_score * (1.0 - _NEAR_MISS_SCORE_THRESHOLD)

    excluded = [it for it in ranked if it not in included]
    near_misses = [
        it for it in excluded
        if it.relevance_score >= threshold
        and it.relevance_score >= _MIN_RELEVANCE_NEAR_MISS
    ]

    return included, near_misses


# ---------------------------------------------------------------------------
# Main assembly: greedy + DP optimization
# ---------------------------------------------------------------------------

def _pick_best_subset(
    candidates: list[ScoredItem],
    budget: int,
) -> tuple[list[ScoredItem], int]:
    """Run greedy + DP, return whichever yields higher total relevance.

    DP runs only when N ≤ _MAX_DP_ITEMS.  Returns (included, total_tokens).
    """
    greedy_inc, greedy_tokens = _greedy_fill(candidates, budget)
    greedy_value = sum(it.relevance_score for it in greedy_inc)

    if len(candidates) > _MAX_DP_ITEMS:
        return greedy_inc, greedy_tokens

    dp_items = _dp_knapsack(candidates, budget)
    dp_value = sum(it.relevance_score for it in dp_items)
    dp_tokens = sum(it.token_estimate for it in dp_items)

    if dp_value >= greedy_value:
        return dp_items, dp_tokens
    return greedy_inc, greedy_tokens


def _identify_near_misses(
    candidates: list[ScoredItem],
    included: list[ScoredItem],
) -> list[ScoredItem]:
    """Find excluded items close enough to the boundary to be near-misses.

    An excluded item qualifies if its relevance is within 5% of the
    lowest included score AND above _MIN_RELEVANCE_NEAR_MISS.
    """
    included_set = {it.text for it in included}
    excluded = [it for it in candidates if it.text not in included_set]

    if not included:
        return []

    boundary_score = min(it.relevance_score for it in included)
    threshold = boundary_score * (1.0 - _NEAR_MISS_SCORE_THRESHOLD)

    return [
        it for it in excluded
        if it.relevance_score >= threshold
        and it.relevance_score >= _MIN_RELEVANCE_NEAR_MISS
    ]


def assemble_budget_bundle(
    candidates: list[ScoredItem],
    token_budget: int,
) -> Result[AssembledBundle]:
    """Budget-aware knapsack assembly with near-miss transparency.

    Strategy:
      1. Greedy value-density fill (fast baseline).
      2. If N ≤ _MAX_DP_ITEMS, run exact0/1 DP and use whichever
         yields higher total relevance.
      3. Identify near-miss items (excluded but close to boundary).
      4. Return AssembledBundle with utilization metrics.

    Pure — same input always produces same output.
    """
    if not candidates:
        return Ok(AssembledBundle(
            included=[], near_misses=[], total_tokens=0,
            utilization=0.0, item_count=0, near_miss_count=0,
        ))
    if token_budget <= 0:
        return Err(
            error="Token budget must be positive",
            code="VALIDATION_ERROR",
            details={"token_budget": token_budget},
        )

    included, total_tokens = _pick_best_subset(candidates, token_budget)
    near_misses = _identify_near_misses(candidates, included)
    utilization = total_tokens / token_budget if token_budget > 0 else 0.0

    return Ok(AssembledBundle(
        included=included,
        near_misses=near_misses,
        total_tokens=total_tokens,
        utilization=round(utilization, 4),
        item_count=len(included),
        near_miss_count=len(near_misses),
    ))


# ---------------------------------------------------------------------------
# Compatibility wrapper (matches subtask JSON acceptance criteria)
# ---------------------------------------------------------------------------

def assemble_bundle(
    scored_items: list[ScoredItem],
    token_budget: int,
) -> Result[tuple[list[ScoredItem], list[ScoredItem]]]:
    """Greedy knapsack assembly — returns (bundle, near_misses).

    Simplified interface per subtask contract.  Delegates to
    assemble_budget_bundle for the full greedy+DP pipeline.
    Items with relevance < 0.3 are excluded from near-misses.
    """
    if not scored_items:
        return Ok(([], []))
    if token_budget <= 0:
        return Ok(([], []))

    result = assemble_budget_bundle(scored_items, token_budget)
    if isinstance(result, Err):
        return result

    bundle = result.value
    return Ok((bundle.included, bundle.near_misses))


# ---------------------------------------------------------------------------
# Response formatter
# ---------------------------------------------------------------------------

def build_prefetch_response(
    bundle: list[ScoredItem],
    near_misses: list[ScoredItem],
    bundle_id: str,
) -> dict[str, Any]:
    """Format assembled items into an API response dict.

    Pure — returns a plain dict suitable for JSON serialization.
    """
    total_tokens = sum(it.token_estimate for it in bundle)
    items_out = [
        {
            "text": it.text,
            "token_estimate": it.token_estimate,
            "relevance_score": it.relevance_score,
            "source_id": it.source_id,
            "metadata": it.metadata,
        }
        for it in bundle
    ]
    misses_out = [
        {
            "text": it.text,
            "token_estimate": it.token_estimate,
            "relevance_score": it.relevance_score,
            "source_id": it.source_id,
        }
        for it in near_misses
    ]
    return {
        "bundle_id": bundle_id,
        "items": items_out,
        "near_misses": misses_out,
        "total_tokens": total_tokens,
        "item_count": len(bundle),
        "near_miss_count": len(near_misses),
    }
