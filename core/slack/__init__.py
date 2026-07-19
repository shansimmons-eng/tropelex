"""
Tropelex Slack Decision Capture — domain types, exceptions, and Result type.

Provides frozen dataclasses for Slack decision capture and extraction,
domain exceptions for IO boundaries, and the standard Result type for
business logic error handling.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar, Union


# ---------------------------------------------------------------------------
# Result type (project-wide convention — matches core/cost/__init__.py)
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

class SlackCaptureError(Exception):
    """Raised when a Slack decision capture operation fails."""

    def __init__(
        self,
        message: str,
        code: str = "SLACK_CAPTURE_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class ValidationError(Exception):
    """Raised when input validation fails for Slack capture/extract."""

    def __init__(
        self,
        message: str,
        code: str = "VALIDATION_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


# ---------------------------------------------------------------------------
# Data models (frozen dataclasses — immutable)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CapturedDecision:
    """A single decision captured from a Slack-style chat message."""

    decision_text: str
    context: str
    source: str  # "manual" | "extracted"
    channel: str
    timestamp: str  # ISO 8601
    agent_name: str


@dataclass(frozen=True)
class ExtractionResult:
    """Result of extracting decisions from a thread of chat messages."""

    decisions: list[CapturedDecision]
    thread_summary: str
    extraction_count: int


@dataclass(frozen=True)
class CaptureRequest:
    """Request to capture a single decision from chat input."""

    decision_text: str
    context: str = ""
    channel: str = ""
    agent_name: str = ""


@dataclass(frozen=True)
class ExtractRequest:
    """Request to extract decisions from a list of chat messages."""

    messages: list[str]
    channel: str = ""
