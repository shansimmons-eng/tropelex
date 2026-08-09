"""
Canonical Result type — the project-wide "errors as values" convention
used across business-logic modules (market, contradictions, ghost,
friction, goals, and others).

Before this module existed, every one of those modules independently
defined its own byte-identical copy of Ok/Err/Result (17 separate
definitions, found while auditing error handling across the codebase) —
consistent in shape everywhere it was checked, but duplicated rather than
shared. This is the single source of truth; other modules should import
from here rather than redefine it.

Domain-specific exceptions (e.g. MarketError, ContradictionError) stay in
their own modules — those are legitimately domain-specific and not part
of this generic type.
"""

from __future__ import annotations

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
