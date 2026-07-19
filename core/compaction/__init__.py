"""
Tropelex Compaction — Memory compaction and epoch summarization.

Provides Result type and domain dataclasses shared across compaction modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class Ok:
    """Successful result wrapper."""
    value: Any


@dataclass(frozen=True)
class Err:
    """Error result wrapper."""
    error: str
    code: str = "UNKNOWN"
    details: dict[str, Any] | None = None


Result = Ok | Err
