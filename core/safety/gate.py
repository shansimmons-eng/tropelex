"""
Required-safety-metadata gate for high/critical-risk decisions.

Today, add_decision (core/tropebook/web/server.py) already requires an
explicit safety_category (core/triggers/tag_gate.py, #35) — omitting it
gets rejected rather than silently auto-classified. Nothing enforces the
same discipline for reversibility, affected_systems, or requires_review:
a decision whose *resolved* risk_level lands on "high" or "critical" —
whether the caller set that explicitly or the auto-classifier guessed it
from keywords — could still have those three fields entirely guessed,
never looked at by anything, and written to disk as if they were real.

This module closes that gap the same way tag_gate closed the category
one: auto-classification still runs and still produces a full suggestion
for every decision. For low/medium risk, that suggestion is accepted as
before — this gate is a no-op there. Once the resolved risk_level is high
or critical, though, reversibility/affected_systems/requires_review can
no longer be silently inherited from the guess — the caller must set them
explicitly. Accepting the auto-classifier's guess stays available; it
just has to be a decision, not a default.
"""

from __future__ import annotations

GATED_RISK_LEVELS = {"high", "critical"}
REQUIRED_FIELDS = ("reversibility", "affected_systems", "requires_review")


class SafetyMetadataRequiredError(Exception):
    """Raised when a high/critical-risk decision omits explicit safety fields."""

    def __init__(self, risk_level: str, missing: list[str], suggested: dict):
        self.risk_level = risk_level
        self.missing = missing
        self.suggested = suggested
        super().__init__(
            f"risk_level={risk_level!r} requires explicit {missing} "
            f"(auto-classifier's guess: {suggested})"
        )

    def to_dict(self) -> dict:
        return {
            "error": "safety_metadata_required",
            "message": str(self),
            "risk_level": self.risk_level,
            "missing_fields": self.missing,
            "suggested": self.suggested,
        }


def require_safety_metadata(
    risk_level: str,
    provided_fields: set[str],
    suggested: dict,
) -> None:
    """No-op unless risk_level is high/critical. In that case, raise
    SafetyMetadataRequiredError if any of reversibility/affected_systems/
    requires_review is missing from provided_fields — the set of field
    names the caller actually set on their request (a pydantic model's
    model_fields_set, not model_dump — the latter can't distinguish "set
    to the default value" from "never set").

    `suggested` is carried on the exception (scoped to just the required
    fields) so a UI can offer a one-click accept, same as tag_gate.
    """
    if risk_level not in GATED_RISK_LEVELS:
        return
    missing = [f for f in REQUIRED_FIELDS if f not in provided_fields]
    if missing:
        raise SafetyMetadataRequiredError(
            risk_level=risk_level,
            missing=missing,
            suggested={f: suggested.get(f) for f in REQUIRED_FIELDS},
        )
