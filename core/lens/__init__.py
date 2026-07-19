"""
Memory Lens — data models, domain exceptions, and Result type.

Provides inline decision annotations for code editors.
Maps code patterns to decisions, detects drift, returns annotation data
consumable by VS Code extensions and other IDE integrations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, Literal, TypeVar, Union


# ---------------------------------------------------------------------------
# Result type (matches project convention)
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

class LensError(Exception):
    """Base for all Memory Lens errors."""

    def __init__(
        self,
        message: str,
        code: str = "LENS_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class ValidationError(LensError):
    """Invalid input passed to a lens function."""

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
class Annotation:
    """A single decision annotation attached to a line of code."""

    decision_id: str
    decision_text: str
    confidence: float
    line_number: int
    file_path: str
    relationship: Literal["defined", "referenced", "drifted"]
    reference_count: int


@dataclass(frozen=True)
class LensRequest:
    """Request to annotate a specific file (and optionally a line)."""

    file_path: str
    line_number: int | None = None


@dataclass(frozen=True)
class ScanResult:
    """All annotations found in a single file scan."""

    file_path: str
    annotations: list[Annotation]
    total_annotations: int
