"""Federation — opt-in, privacy-preserving anonymized benchmarking across installs."""
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


class FederationError(Exception):
    """Base for federation errors."""
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
class AnonymizedStats:
    """Structural statistics stripped of any decision text — safe to share."""
    project_hash: str
    tech_stack: list[str]
    decision_count: int
    reversal_rate: float
    avg_confidence: float
    category_distribution: dict[str, int]


@dataclass(frozen=True)
class BenchmarkComparison:
    """How a project compares to the federated aggregate."""
    project_hash: str
    compared_to_aggregate: AnonymizedStats
    deviation: dict[str, float]
    percentile: dict[str, float]


@dataclass(frozen=True)
class FederationRequest:
    """Request payload for federation sharing."""
    opt_in: bool = True
