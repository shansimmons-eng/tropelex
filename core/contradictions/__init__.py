"""Contradiction Detection — models and types for finding conflicting decisions."""
from dataclasses import dataclass
from typing import Literal

from core.result import Err, Ok, Result  # noqa: F401 - re-exported for this module's consumers


# --- Domain exceptions (IO boundaries) ---

class ContradictionError(Exception):
    """Base error for contradiction detection failures."""

    def __init__(self, message: str, code: str = "UNKNOWN", details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


class ValidationError(Exception):
    """Invalid input for contradiction operations."""

    def __init__(self, message: str, code: str = "VALIDATION_ERROR", details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


# --- Data models ---

@dataclass(frozen=True)
class Contradiction:
    """A detected conflict between two decisions."""
    id: str
    decision_a_id: str
    decision_a_text: str
    decision_b_id: str
    decision_b_text: str
    contradiction_type: Literal["direct", "implicit", "temporal"]
    severity: Literal["high", "medium", "low"]
    similarity_score: float
    resolution_suggestion: str


@dataclass(frozen=True)
class ContradictionReport:
    """Summary of a contradiction scan across all decisions."""
    contradictions: list[Contradiction]
    total_checked: int
    unresolved_count: int
