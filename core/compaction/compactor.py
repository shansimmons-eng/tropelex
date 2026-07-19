"""
Tropelex Memory Compactor — Orchestration layer for memory compaction.

Finds stale supersession chains, merges them into epoch summaries,
and archives originals without deletion.  IO is isolated to
compact_memory; everything else is pure.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any

from core.compaction import Err, Ok, Result
from core.compaction.epoch import (
    CompactionChain,
    EpochRecord,
    generate_epoch_summary,
    identify_compactable_chains,
    merge_chain_to_epoch,
)
from core.knowledge_decay import score_decision
from core.memory.manager import MemoryManager

# Threshold below which a chain is considered stale enough to compact.
_CONFIDENCE_THRESHOLD: float = 0.6
# Rough chars-per-token ratio for savings estimation.
_CHARS_PER_TOKEN: int = 4


# --- Dataclasses ---

@dataclass(frozen=True)
class CompactionResult:
    """Outcome of a compaction pass."""
    epochs_created: int
    decisions_archived: int
    token_savings_estimate: int
    epoch_summaries: list[EpochRecord]


# --- Pure functions (no I/O) ---


def _member_confidence(
    members: list[dict[str, Any]],
    all_decisions: list[dict[str, Any]],
) -> float:
    """Average confidence score across chain members."""
    if not members:
        return 0.0
    scores = [
        score_decision(m, all_decisions).get("score", 0.0) for m in members
    ]
    return sum(scores) / len(scores)


def archive_originals(
    decisions: list[dict[str, Any]],
    compacted_ids: list[str],
    epoch_id: str,
) -> list[dict[str, Any]]:
    """Mark originals as archived; never delete.

    Returns a new list where compacted decisions have archived=True and
    epoch_id set.  Input is not mutated.
    """
    compacted_set = set(compacted_ids)
    result: list[dict[str, Any]] = []
    for d in decisions:
        did = d.get("id", "")
        if did in compacted_set:
            archived = {**d, "archived": True, "epoch_id": epoch_id}
            result.append(archived)
        else:
            result.append(d)
    return result


def build_compaction_report(
    before_count: int,
    after_count: int,
    epoch_count: int,
) -> dict[str, Any]:
    """Summary statistics for a compaction pass."""
    return {
        "decisions_before": before_count,
        "decisions_after": after_count,
        "decisions_archived": before_count - after_count,
        "epochs_created": epoch_count,
    }


def apply_compaction(
    memory: dict[str, Any],
    epochs: list[EpochRecord],
) -> dict[str, Any]:
    """Pure: merge archived decisions and epoch records into memory.

    Returns a new dict — input is never mutated.
    """
    new_mem = copy.deepcopy(memory)
    active = list(new_mem.get("decisions", []))
    archived: list[dict[str, Any]] = list(new_mem.get("archived_decisions", []))

    for epoch in epochs:
        archived_ids = set(epoch.archived_decision_ids)
        still_active: list[dict[str, Any]] = []
        for d in active:
            did = d.get("id", "")
            if did in archived_ids:
                archived.append(
                    {**d, "archived": True, "epoch_id": epoch.epoch_id}
                )
            else:
                still_active.append(d)
        active = still_active

    new_mem["decisions"] = active
    new_mem["archived_decisions"] = archived

    existing_epochs = new_mem.get("epochs", [])
    for epoch in epochs:
        existing_epochs.append({
            "epoch_id": epoch.epoch_id,
            "summary": epoch.summary.text,
            "archived_decision_ids": epoch.archived_decision_ids,
            "date_range": list(epoch.date_range),
            "confidence_range": list(epoch.confidence_range),
        })
    new_mem["epochs"] = existing_epochs
    return new_mem


def estimate_token_savings(
    original_decisions: list[dict[str, Any]],
    epochs: list[EpochRecord],
) -> int:
    """Rough token savings from replacing N decisions with epoch summaries."""
    saved_chars = 0
    archived_ids: set[str] = set()
    for epoch in epochs:
        archived_ids.update(epoch.archived_decision_ids)

    for d in original_decisions:
        if d.get("id", "") in archived_ids:
            blob = json.dumps(d, default=str)
            saved_chars += len(blob)

    epoch_chars = sum(len(ep.summary.text) for ep in epochs)
    saved_chars -= epoch_chars
    return max(saved_chars // _CHARS_PER_TOKEN, 0)


def _filter_stale_chains(
    chains: list[CompactionChain],
    decisions: list[dict[str, Any]],
) -> list[CompactionChain]:
    """Keep only chains whose average confidence is below threshold."""
    return [
        c for c in chains
        if _member_confidence(c.members, decisions) < _CONFIDENCE_THRESHOLD
    ]


# --- IO boundary ---


def compact_memory(
    project: str,
    memory: dict[str, Any],
) -> Result[CompactionResult]:
    """Run a full compaction pass on a project's memory.

    Finds stale supersession chains, generates epoch summaries, archives
    originals, and returns statistics.  IO is isolated here (MemoryManager
    read/write).
    """
    decisions = memory.get("decisions", [])
    if not decisions:
        return Ok(CompactionResult(
            epochs_created=0,
            decisions_archived=0,
            token_savings_estimate=0,
            epoch_summaries=[],
        ))

    chains = identify_compactable_chains(decisions)
    stale = _filter_stale_chains(chains, decisions)

    if not stale:
        return Ok(CompactionResult(
            epochs_created=0,
            decisions_archived=0,
            token_savings_estimate=0,
            epoch_summaries=[],
        ))

    epochs: list[EpochRecord] = []
    for chain in stale:
        result = merge_chain_to_epoch(chain, decisions)
        if isinstance(result, Err):
            return result
        epochs.append(result.value)

    new_memory = apply_compaction(memory, epochs)

    # Persist compacted memory
    mm = MemoryManager()
    try:
        mm.save_project_memory(project, new_memory)
    except Exception as exc:
        return Err(
            error=f"Failed to save compacted memory: {exc}",
            code="IO_ERROR",
        )

    savings = estimate_token_savings(decisions, epochs)
    return Ok(CompactionResult(
        epochs_created=len(epochs),
        decisions_archived=sum(len(e.archived_decision_ids) for e in epochs),
        token_savings_estimate=savings,
        epoch_summaries=epochs,
    ))
