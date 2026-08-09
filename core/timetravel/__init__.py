"""Time-Travel Debugger — snapshot models and types for reconstructing past memory state."""
from dataclasses import dataclass
from typing import Any

from core.result import Err, Ok, Result  # noqa: F401 - re-exported for this module's consumers


# --- Domain exceptions (IO boundaries) ---

class TimeTravelError(Exception):
    """Base error for time-travel operations."""

    def __init__(self, message: str, code: str = "UNKNOWN", details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


class MemoryError(TimeTravelError):
    """Raised when a memory snapshot cannot be found or loaded."""

    def __init__(self, message: str, code: str = "NOT_FOUND", details: dict | None = None):
        super().__init__(message, code=code, details=details)


class ValidationError(TimeTravelError):
    """Invalid input for time-travel operations."""

    def __init__(self, message: str, code: str = "VALIDATION_ERROR", details: dict | None = None):
        super().__init__(message, code=code, details=details)


# --- Data models ---

@dataclass(frozen=True)
class MemorySnapshot:
    """A point-in-time snapshot of project memory."""
    project_name: str
    snapshot_date: str       # ISO 8601 datetime
    memory: dict[str, Any]
    decision_count: int
    session_count: int


@dataclass(frozen=True)
class SnapshotDiff:
    """Delta between two memory snapshots."""
    date_from: str
    date_to: str
    decisions_added: list[str]
    decisions_removed: list[str]
    sessions_added: int
    changes_summary: str


@dataclass(frozen=True)
class TimeTravelRequest:
    """Request to retrieve memory as of a specific date."""
    date: str  # ISO date or "YYYY-MM-DD"


@dataclass(frozen=True)
class DiffRequest:
    """Request to diff memory between two dates."""
    date_from: str
    date_to: str
