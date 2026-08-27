"""
Tag-required capture gate — wired into add_decision.

POST /api/memory/{project}/decisions (core/tropebook/web/server.py,
add_decision) requires an explicit, valid `safety_metadata.safety_category`.
_auto_classify_safety() still runs, but its output is only ever a
*suggestion* carried on a 422 (TagRequiredError.to_dict()'s `suggested`
field) -- never a value silently written to disk. Every write path funnels
through the same gate: manual capture, research-promoted decisions
(promote_decision), and the MCP tool (mcp_server/server.py capture_decision,
which requires the caller to pass a real category rather than defaulting to
"general" itself).

This is the reference pattern for core/triggers/goal_gate.py's
require_goal_evidence: don't let a claim (a category, a goal being
"achieved") be recorded without an explicit, checkable basis for it.
"""

from __future__ import annotations

SAFETY_CATEGORIES = {
    "general",
    "adversarial",
    "robustness",
    "monitoring",
    "governance",
    "alignment",
}


class TagRequiredError(Exception):
    """Raised when a capture is attempted without an explicit, valid tag."""

    def __init__(self, suggested: str | None, valid: set[str]):
        self.suggested = suggested
        self.valid = valid
        super().__init__(
            f"a category must be explicitly chosen (suggestion: {suggested!r}); "
            f"valid values: {sorted(valid)}"
        )

    def to_dict(self) -> dict:
        return {
            "error": "tag_required",
            "message": str(self),
            "suggested": self.suggested,
            "valid_categories": sorted(self.valid),
        }


def require_tag(
    category: str | None,
    suggested: str | None = None,
    valid: set[str] = SAFETY_CATEGORIES,
) -> str:
    """Return `category` if it's an explicit, valid choice; raise otherwise.

    `suggested` is carried on the exception so a UI can offer it as a
    one-click accept — the point isn't to make the auto-classifier's guess
    unavailable, it's to make accepting it a decision instead of a default.
    """
    if not category or category not in valid:
        raise TagRequiredError(suggested=suggested, valid=valid)
    return category
