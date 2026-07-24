"""Doc Mining — models and types for mining markdown files for drift,
contradictions, and undocumented decisions against a project's decision graph.
"""
from dataclasses import dataclass
from typing import Any, Generic, Literal, TypeVar, Union

T = TypeVar("T")


# --- Result type (business logic) ---

@dataclass(frozen=True)
class Ok(Generic[T]):
    value: T


@dataclass(frozen=True)
class Err:
    error: str
    code: str = "UNKNOWN"
    details: dict[str, Any] | None = None


Result = Union[Ok[T], Err]


# --- Domain exceptions (IO boundaries) ---

class DocMineError(Exception):
    """Base error for doc mining failures."""

    def __init__(self, message: str, code: str = "UNKNOWN", details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


# --- Data models ---

@dataclass(frozen=True)
class DocClaim:
    """A single extracted claim (sentence or list item) from a markdown file."""
    id: str
    text: str
    source_file: str
    line_number: int


@dataclass(frozen=True)
class DocFinding:
    """A detected conflict involving at least one doc claim."""
    id: str
    kind: Literal["doc_vs_decision", "doc_vs_doc"]
    claim_a_text: str
    claim_a_source: str
    claim_b_text: str
    claim_b_source: str
    contradiction_type: Literal["direct", "implicit", "temporal"]
    severity: Literal["high", "medium", "low"]
    similarity_score: float
    resolution_suggestion: str


@dataclass(frozen=True)
class UncapturedClaim:
    """A decision-shaped claim in a doc with no matching entry in the decision graph."""
    text: str
    source_file: str
    line_number: int


@dataclass(frozen=True)
class DocMineReport:
    """Summary of a doc mining scan."""
    files_scanned: list[str]
    claims_extracted: int
    findings: list[DocFinding]
    uncaptured_claims: list[UncapturedClaim]
