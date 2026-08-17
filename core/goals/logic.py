"""
Goals — pure functions for creating, updating, and transitioning goals.

Pure, side-effect-free functions operating on plain dicts. All functions
return Result[Ok, Err] and produce new dicts/lists rather than mutating
input, matching core/market/calibration.py's convention exactly.
Same input -> same output, always. No I/O.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from core.goals import (
    GOAL_PRIORITIES,
    GOAL_STATUS_TRANSITIONS,
    GOAL_STATUSES,
    Err,
    Ok,
    Result,
)
from core.injection_sentinel import scan_content
from core.triggers.tag_gate import SAFETY_CATEGORIES

_NONSAFETY_PREFIX = "nonsafety:"
_MAX_CATEGORY_LEN = 64


def _validate_category(category: str | None) -> str | None:
    """Return an error string if `category` is invalid, else None.

    A category is valid if it's None (unclassified — allowed, unlike
    safety_category on Decision, which is gated: see core/triggers/tag_gate.py
    for why that field specifically must never silently default), a bare
    SAFETY_CATEGORIES value, or a "nonsafety:<label>" namespaced string.
    The nonsafety: prefix isn't improvised — it mirrors the "category:ui" /
    "day:monday" namespacing core/learner/learner.py already uses for
    pattern names.
    """
    if category is None:
        return None
    if category in SAFETY_CATEGORIES:
        return None
    if category.startswith(_NONSAFETY_PREFIX):
        label = category[len(_NONSAFETY_PREFIX):]
        if not label:
            return "category 'nonsafety:' must have a non-empty label after the colon"
        if len(category) > _MAX_CATEGORY_LEN:
            return f"category must be at most {_MAX_CATEGORY_LEN} characters"
        return None
    return (
        f"category must be one of {sorted(SAFETY_CATEGORIES)}, "
        f"a 'nonsafety:<label>' string, or omitted — got {category!r}"
    )


def create_goal(goals: list[dict], goal: dict) -> Result[list[dict]]:
    """Validate and append a goal, returning a new list (immutable)."""
    text = goal.get("text", "")
    if not isinstance(text, str) or not text.strip():
        return Err(error="Goal text must be a non-empty string", code="VALIDATION_ERROR")

    status = goal.get("status", "proposed")
    if status not in GOAL_STATUSES:
        return Err(error=f"status must be one of {sorted(GOAL_STATUSES)}, got {status!r}", code="VALIDATION_ERROR")

    priority = goal.get("priority", "medium")
    if priority not in GOAL_PRIORITIES:
        return Err(error=f"priority must be one of {sorted(GOAL_PRIORITIES)}, got {priority!r}", code="VALIDATION_ERROR")

    category = goal.get("category")
    category_error = _validate_category(category)
    if category_error:
        return Err(error=category_error, code="VALIDATION_ERROR")

    now = datetime.now(timezone.utc).isoformat()
    enriched = {
        "id": goal.get("id") or uuid.uuid4().hex[:12],
        "text": text.strip(),
        "status": status,
        "priority": priority,
        "category": category,
        "tags": goal.get("tags") or [],
        "created_at": now,
        "updated_at": now,
    }
    # P7 (gap E): flag, don't block -- same pattern as add_decision. Goal
    # text is agent-writable and later read back as trusted context
    # (get_context_bundle), so it's exactly the kind of field the
    # sentinel exists for but never covered.
    flags = scan_content(enriched["text"])
    if flags:
        enriched["content_flags"] = flags
    return Ok(value=[*goals, enriched])


def update_goal(goal: dict, updates: dict) -> Result[dict]:
    """Merge whitelisted fields into a goal. Never touches status — see
    transition_status(), which is the only path that changes it, so a
    status change is always a deliberate, auditable action rather than a
    field-patch side effect.
    """
    if "status" in updates:
        return Err(
            error="status cannot be changed via update_goal — use transition_status",
            code="VALIDATION_ERROR",
        )

    result = dict(goal)
    if "text" in updates:
        text = updates["text"]
        if not isinstance(text, str) or not text.strip():
            return Err(error="Goal text must be a non-empty string", code="VALIDATION_ERROR")
        result["text"] = text.strip()
        # Recompute rather than accumulate -- content_flags should reflect
        # the *current* text, same reasoning as P2's hash resync.
        flags = scan_content(result["text"])
        if flags:
            result["content_flags"] = flags
        else:
            result.pop("content_flags", None)
    if "priority" in updates:
        priority = updates["priority"]
        if priority not in GOAL_PRIORITIES:
            return Err(error=f"priority must be one of {sorted(GOAL_PRIORITIES)}, got {priority!r}", code="VALIDATION_ERROR")
        result["priority"] = priority
    if "category" in updates:
        category_error = _validate_category(updates["category"])
        if category_error:
            return Err(error=category_error, code="VALIDATION_ERROR")
        result["category"] = updates["category"]
    if "tags" in updates:
        result["tags"] = updates["tags"] or []

    result["updated_at"] = datetime.now(timezone.utc).isoformat()
    return Ok(value=result)


def transition_status(goal: dict, new_status: str) -> Result[dict]:
    """Move a goal to a new status, rejecting illegal transitions
    (e.g. achieved -> proposed). achieved/abandoned are terminal."""
    if new_status not in GOAL_STATUSES:
        return Err(error=f"status must be one of {sorted(GOAL_STATUSES)}, got {new_status!r}", code="VALIDATION_ERROR")

    current = goal.get("status")
    legal = GOAL_STATUS_TRANSITIONS.get(current, set())
    if new_status not in legal:
        return Err(
            error=f"cannot transition goal from '{current}' to '{new_status}'",
            code="VALIDATION_ERROR",
            details={"current_status": current, "requested_status": new_status, "legal_transitions": sorted(legal)},
        )

    return Ok(value={
        **goal,
        "status": new_status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })


def list_goals(
    goals: list[dict], status: str | None = None, category: str | None = None
) -> list[dict]:
    """Filter and sort goals, newest first. Never fails on valid input —
    no goals matching a filter is a valid, non-error result (matches
    compute_leaderboard()'s convention of returning Ok([]) for the empty
    case rather than modeling "nothing found" as an error)."""
    result = goals
    if status is not None:
        result = [g for g in result if g.get("status") == status]
    if category is not None:
        result = [g for g in result if g.get("category") == category]
    return sorted(result, key=lambda g: g.get("created_at", ""), reverse=True)
