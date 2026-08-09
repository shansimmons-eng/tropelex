"""
Tropelex Goals — domain exceptions, result type, and immutable models.

A Goal is the prospective counterpart to a Decision: what a project is
aiming at, before decisions accumulate under it. Where Decision captures
risk/reversibility (properties of something that already happened), Goal
has a status lifecycle (proposed -> active -> achieved|abandoned) and no
risk metadata, because nothing has happened yet.

Result/Ok/Err are intentionally NOT redefined here — imported from
core.result, the single canonical definition every business-logic module
should use. Prior to core.result existing, this imported from
core.market instead (which itself just held its own copy, one of 17
independent copies of the same type found across the codebase during an
error-handling audit) — updated to import from the real shared source.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.result import Err, Ok, Result  # noqa: F401 - re-exported for core.goals.* consumers

GOAL_STATUSES = {"proposed", "active", "achieved", "abandoned"}
GOAL_PRIORITIES = {"low", "medium", "high", "critical"}  # mirrors SafetyMetadata.risk_level's vocabulary

# Legal status transitions — anything not listed here (e.g. achieved -> proposed)
# is rejected by transition_status(). A goal can be abandoned from proposed or
# active, but not un-abandoned or un-achieved; those are terminal states.
GOAL_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "proposed": {"active", "abandoned"},
    "active": {"achieved", "abandoned"},
    "achieved": set(),
    "abandoned": set(),
}


class GoalError(Exception):
    """Base for all goal-subsystem errors."""

    def __init__(
        self,
        message: str,
        code: str = "GOAL_ERROR",
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class GoalValidationError(Exception):
    """Invalid input passed to a goal function."""

    def __init__(
        self,
        message: str,
        code: str = "VALIDATION_ERROR",
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class Goal:
    """An immutable shape contract for a goal record.

    Business logic (core/goals/logic.py) operates on plain dicts, matching
    core/market/calibration.py's convention — this dataclass documents the
    shape rather than being threaded through function signatures.
    """

    id: str
    text: str
    status: str
    priority: str
    category: str | None = None
    tags: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class GoalCreate:
    """Inbound request to propose a new goal."""

    text: str
    status: str = "proposed"
    priority: str = "medium"
    category: str | None = None
    tags: list[str] = field(default_factory=list)
