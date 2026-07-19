"""
Tropelex Decision Market — domain exceptions, result type, and immutable models.

Team members place confidence bets on decisions; calibration is tracked over time.
This module defines the core data structures used across the market subsystem.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar, Union


# ---------------------------------------------------------------------------
# Result type (project-wide convention)
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

class MarketError(Exception):
    """Base for all decision-market errors."""

    def __init__(
        self,
        message: str,
        code: str = "MARKET_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class ValidationError(Exception):
    """Invalid input passed to a market function."""

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
class ConfidenceBet:
    """An immutable record of a single confidence bet placed on a decision."""

    id: str
    decision_id: str
    agent_name: str
    confidence: float          # 0.0–1.0
    category: str
    placed_at: str             # ISO 8601 timestamp
    resolved: bool = False
    outcome: str | None = None  # "correct" | "incorrect" | None


@dataclass(frozen=True)
class CalibrationScore:
    """Aggregate calibration metrics for a single agent."""

    agent_name: str
    total_bets: int
    correct_bets: int
    accuracy: float
    category_scores: dict[str, float] = field(default_factory=dict)
    overconfidence_index: float = 0.0


@dataclass(frozen=True)
class LeaderboardEntry:
    """A single row in the calibration leaderboard."""

    agent_name: str
    accuracy: float
    total_bets: int
    categories: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BetRequest:
    """Inbound request to place a new confidence bet."""

    decision_id: str
    agent_name: str
    confidence: float
    category: str
