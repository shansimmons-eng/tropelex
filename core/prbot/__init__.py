"""PR Bot — delivers decision insights as PR comments."""
from dataclasses import dataclass
from typing import Any, Generic, TypeVar, Union

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


class PRBotError(Exception):
    """Base for PR bot errors."""
    def __init__(self, message: str, code: str = "UNKNOWN", details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


class ValidationError(Exception):
    """Invalid input at a boundary."""
    def __init__(self, message: str, code: str = "VALIDATION_ERROR", details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class PRDecision:
    decision_id: str
    decision_text: str
    confidence: float
    relevance_score: float
    impact_score: float
    relationship: str  # "direct" | "ancestor" | "descendant"
    risk_level: str = "low"
    requires_review: bool = False


@dataclass(frozen=True)
class PRGhostWarning:
    decision_id: str
    severity: str
    matched_keywords: list[str]
    recommendation: str


@dataclass(frozen=True)
class PRComment:
    body: str
    decisions_mentioned: list[PRDecision]
    ghost_warnings: list[PRGhostWarning]
    relevance_score: float
    decision_count: int
    warning_count: int


@dataclass(frozen=True)
class PRCommentRequest:
    diff: str
    pr_title: str = ""
    pr_body: str = ""
