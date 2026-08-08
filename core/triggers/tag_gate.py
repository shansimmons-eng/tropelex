"""
Tag-required capture gate — sketch, not wired into server.py.

Today, POST /api/memory/{project}/decisions (core/tropebook/web/server.py,
add_decision) accepts an optional `safety_metadata.safety_category`. If it's
omitted, _auto_classify_safety() silently invents one from keyword matching
and the decision is saved with a category nobody chose. The MCP tool wrapper
(mcp_server/server.py capture_decision) makes this worse by defaulting the
parameter to "general" itself, so even an agent that never thinks about
category gets a clean-looking, wrong-by-default save.

This module is the primitive for closing that gap: don't let a category be
silently assigned. Auto-classification still runs, but its output becomes a
*suggestion* attached to an error, not a value written to disk.

Deliberately not wired into add_decision in this pass: doing so changes the
API's existing contract (any caller currently omitting safety_category,
including the live dashboard and the MCP tool's own default, would start
getting rejected instead of auto-classified) and that's a call worth making
on purpose, not as a side effect of a sketch.

If/when wiring it in, the shape at the call site would be:

    from core.triggers.tag_gate import require_tag, TagRequiredError

    @app.post("/api/memory/{project}/decisions")
    async def add_decision(project: str, data: DecisionCreate):
        ...
        suggestion = _auto_classify_safety(data.decision, data.context)
        try:
            category = require_tag(
                data.safety_metadata.safety_category if data.safety_metadata else None,
                suggested=suggestion["safety_category"],
            )
        except TagRequiredError as exc:
            raise HTTPException(status_code=422, detail=exc.to_dict())
        ...

    # and mcp_server/server.py's capture_decision would need to drop its
    # `safety_category: str = "general"` default so the MCP-level caller is
    # forced to either pass a real category or surface the 422's suggestion
    # back to whoever/whatever is driving it.
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
