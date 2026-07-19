"""Corroboration — rationale validation via live web research."""
from dataclasses import dataclass
from enum import Enum
from typing import Any, Generic, TypeVar, Union

T = TypeVar("T")

@dataclass(frozen=True)
class Ok(Generic[T]):
    value: T

@dataclass(frozen=True)
class Err:
    error: str
    code: str = "UNKNOWN"
    details: dict[str, Any] | None = None

Result = Union[Ok[T], Err]

class TropelexError(Exception):
    def __init__(self, message: str, code: str = "UNKNOWN", details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}

class CorroborationError(TropelexError): ...
class ValidationError(TropelexError): ...
class ResearchError(TropelexError): ...

class CorroborationStatus(str, Enum):
    supported = "supported"
    outdated = "outdated"
    contradicted = "contradicted"
    unverifiable = "unverifiable"

@dataclass(frozen=True)
class ResearchFinding:
    title: str
    url: str
    description: str
    source: str
    relevance_score: float  # 0.0–1.0

@dataclass(frozen=True)
class CorroborationReport:
    decision_id: str
    rationale: str
    research_findings: tuple[ResearchFinding, ...]
    status: CorroborationStatus
    confidence_adjustment: float
    evidence_urls: tuple[str, ...]
    checked_at: str  # ISO 8601 timestamp

@dataclass(frozen=True)
class CorroborationRequest:
    decision_id: str
    force_refresh: bool = False
