"""
Goal-evidence gate — block a goal's transition to "achieved" unless a real
decision is on record for it.

Today PATCH /api/memory/{project}/goals/{goal_id}/status lets a goal move
straight to "achieved" with nothing behind it -- no decision anywhere in
the project has to reference the goal via its goal_id for the transition
to succeed. achieved is also a terminal status (core/goals/__init__.py's
GOAL_STATUS_TRANSITIONS has no legal transition out of it), so a goal
marked achieved by mistake, or aspirationally, stays that way with no
system-visible record of what actually achieved it.

Same shape and intent as core/triggers/tag_gate.py's require_tag: don't
let the claim be made without an explicit, checkable basis for it. The
escape hatch is an explicit override (POST .../goals/{goal_id}/achieve-
override in core/goals/router.py), recorded in the audit trail, not a
silent default -- mirrors core/ghost/preventive_router.py's decision
override for the same reason: legitimate cases exist (a goal achieved by
work outside Tropelex's own decision capture), but they should leave a
trace, not bypass the check invisibly.
"""

from __future__ import annotations


class GoalEvidenceRequiredError(Exception):
    """Raised when a goal is transitioned to 'achieved' with no decision
    recorded against it (no decision.goal_id references the goal)."""

    def __init__(self, goal_id: str):
        self.goal_id = goal_id
        super().__init__(
            f"goal '{goal_id}' has no decision recorded against it -- "
            "link a decision (its goal_id) to this goal first, or call "
            "the achieve-override endpoint with a rationale"
        )

    def to_dict(self) -> dict:
        return {
            "error": "goal_evidence_required",
            "message": str(self),
            "goal_id": self.goal_id,
        }


def require_goal_evidence(goal_id: str, decisions: list[dict]) -> None:
    """Raise GoalEvidenceRequiredError unless some decision's goal_id
    matches `goal_id`. Call before allowing a transition to 'achieved'."""
    if not any(d.get("goal_id") == goal_id for d in decisions):
        raise GoalEvidenceRequiredError(goal_id)
