"""PR Bot — delivers decision insights as PR comments."""
from dataclasses import dataclass

from core.result import Err, Ok, Result  # noqa: F401 - re-exported for this module's consumers


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
