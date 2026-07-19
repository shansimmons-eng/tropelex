"""Narrative mode — prose generation for non-technical audiences."""
from dataclasses import dataclass
from typing import Any, Generic, TypeVar, Union

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

class NarrativeError(Exception):
    def __init__(self, message: str, code: str = "UNKNOWN", details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


class ValidationError(NarrativeError): ...


# --- Data models ---

@dataclass(frozen=True)
class NarrativeSection:
    heading: str
    body: str
    section_type: str  # "origin" | "challenge" | "pivot" | "resolution" | "current"


@dataclass(frozen=True)
class NarrativeReport:
    title: str
    sections: list[NarrativeSection]
    summary: str
    audience: str
    word_count: int
    project_name: str
    generated_at: str


@dataclass(frozen=True)
class NarrativeRequest:
    audience: str = "new_hire"  # "investor" | "new_hire" | "pm"
