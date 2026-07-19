"""Personas — Digital Twin contributor models from agent proficiency tracking.

Provides frozen dataclass models, domain exceptions, and a Result type
for persona synthesis from the AgentSkillGraph.
"""

from dataclasses import dataclass
from typing import Any, Generic, TypeVar, Union


# ---------------------------------------------------------------------------
# Result type (business logic — never raises, returns Ok/Err)
# ---------------------------------------------------------------------------

T = TypeVar("T")


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


# ---------------------------------------------------------------------------
# Domain exceptions (IO boundary only — business logic returns Result)
# ---------------------------------------------------------------------------

class PersonaError(Exception):
    """Base for all persona-related errors."""

    def __init__(
        self,
        message: str,
        code: str = "PERSONA_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class ValidationError(PersonaError):
    """Invalid input passed to a persona function."""

    def __init__(
        self,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code="VALIDATION_ERROR", details=details)


# ---------------------------------------------------------------------------
# Data models (frozen dataclasses — immutable)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PersonaSummary:
    """Synthesized persona for an agent based on skill graph data."""

    agent_name: str
    strengths: list[str]
    weaknesses: list[str]
    preferred_categories: list[str]
    accuracy_by_category: dict[str, float]
    summary_text: str
    total_sessions: int


@dataclass(frozen=True)
class ReviewSuggestion:
    """Suggested review focus areas for a contributor persona."""

    agent_name: str
    focus_areas: list[str]
    reasoning: str
