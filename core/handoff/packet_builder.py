"""
Tropelex Handoff Packet Builder
Role-aware context bundling for agent handoff.

Pure functions only -- no I/O, no network, no file access.
Builds token-budgeted context packets tailored to each agent role.
"""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from core.knowledge_decay import score_decisions


# Role profiles define what each agent type needs from memory
ROLE_PROFILES: dict[str, dict[str, Any]] = {
    "CoderAgent": {
        "description": "General-purpose coding agent",
        "priority_categories": ["backend", "config", "testing"],
        "include_sessions": True,
        "include_skills": True,
        "max_decisions": 15,
        "max_tokens": 4000,
    },
    "TestEngineer": {
        "description": "Testing and quality assurance specialist",
        "priority_categories": ["testing", "backend"],
        "include_sessions": True,
        "include_skills": True,
        "max_decisions": 10,
        "max_tokens": 3000,
    },
    "Architect": {
        "description": "System architecture and design decisions",
        "priority_categories": ["backend", "config", "devops", "database"],
        "include_sessions": True,
        "include_skills": True,
        "max_decisions": 20,
        "max_tokens": 5000,
    },
    "FrontendSpecialist": {
        "description": "UI/UX implementation specialist",
        "priority_categories": ["ui", "config"],
        "include_sessions": True,
        "include_skills": False,
        "max_decisions": 10,
        "max_tokens": 3000,
    },
    "DevOpsSpecialist": {
        "description": "CI/CD, infrastructure, deployment",
        "priority_categories": ["devops", "config", "testing"],
        "include_sessions": True,
        "include_skills": True,
        "max_decisions": 10,
        "max_tokens": 3000,
    },
}


@dataclass(frozen=True)
class ContextSlice:
    """A single piece of context in the handoff packet."""
    category: str
    content: str
    priority: int  # 0=must-survive (#69), 1=role match, higher=lower priority
    token_estimate: int


@dataclass(frozen=True)
class HandoffPacket:
    """Role-aware context bundle for agent handoff."""
    role: str
    project: str
    context_slices: list[ContextSlice]
    active_decisions: list[dict[str, Any]]
    recent_sessions: list[dict[str, Any]]
    token_count: int
    token_budget: int
    skills_summary: dict[str, Any] | None
    generated_at: str
    completeness_findings: list["HandoffCompletenessFinding"] = field(default_factory=list)


@dataclass(frozen=True)
class HandoffCompletenessFinding:
    """A must-survive decision (#69) that didn't make it into the final
    context_slices -- same field shape as GhostWarning/Contradiction.
    Should never actually occur through the real pipeline once
    _select_decisions/_trim_to_budget both protect priority-0 content;
    this exists as a regression safety net verifying the observable
    outcome, not the mechanism."""
    id: str
    severity: str
    decision_id: str
    decision_text: str
    category: str
    description: str
    recommendation: str


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English text.
    Returns len(text) // 4.
    """
    return len(text) // 4


def _decision_matches_category(decision: dict[str, Any], categories: list[str]) -> bool:
    """Check if a decision relates to any of the given categories.
    Checks explicit categories field first, then falls back to keyword matching.
    """
    explicit = decision.get("categories", [])
    if any(cat in categories for cat in explicit):
        return True
    text = f"{decision.get('decision', '')} {decision.get('context', '')}".lower()
    return any(cat.lower() in text for cat in categories)


def _is_must_survive(decision: dict[str, Any]) -> bool:
    """A decision that must not be trimmed out of a handoff packet (#69):
    explicitly flagged, or derived from its existing risk_level -- no
    schema migration needed, works on every decision that already carries
    safety metadata (#35/#54)."""
    if decision.get("must_survive") is True:
        return True
    safety = decision.get("safety_metadata")
    if not isinstance(safety, dict):
        return False
    return safety.get("risk_level") in ("high", "critical")


def _select_decisions(
    decisions: list[dict],
    profile: dict[str, Any],
    scored: list[dict],
) -> list[dict]:
    """Select and prioritize decisions for this role.
    Filter by priority_categories, sort by confidence score,
    cap at max_decisions.
    """
    if not decisions:
        return []

    # Build score lookup: truncated decision text -> scored data
    score_lookup: dict[str, dict] = {s.get("decision", ""): s for s in scored}

    def _get_score(d: dict) -> float:
        key = d.get("decision", "")[:100]
        return score_lookup.get(key, {}).get("score", 0.0)

    def _enrich(d: dict) -> dict:
        key = d.get("decision", "")[:100]
        return {**d, "confidence": score_lookup.get(key, {})}

    # Split into priority-matching and other decisions
    priority_cats = profile.get("priority_categories", [])
    priority = [d for d in decisions if _decision_matches_category(d, priority_cats)]
    others = [d for d in decisions if not _decision_matches_category(d, priority_cats)]

    # Sort each group by confidence score (descending)
    priority.sort(key=_get_score, reverse=True)
    others.sort(key=_get_score, reverse=True)

    # Combine: priority-matching first, then others
    combined = priority + others

    # Cap at max_decisions
    max_d = profile.get("max_decisions", 15)
    selected = combined[:max_d]

    # #69: must-survive decisions are exempt from the cap -- a critical
    # decision that doesn't match this role's priority_categories would
    # otherwise never even reach _build_context_slices/_trim_to_budget.
    # Protection over budget is an explicit, intentional tradeoff here,
    # not a bug -- the returned list can exceed max_decisions.
    selected_ids = {id(d) for d in selected}
    must_survive_cut = [
        d for d in combined[max_d:]
        if _is_must_survive(d) and id(d) not in selected_ids
    ]
    selected = selected + must_survive_cut

    return [_enrich(d) for d in selected]


def _select_sessions(
    sessions: list[dict],
    profile: dict[str, Any],
) -> list[dict]:
    """Select recent sessions relevant to this role.
    Return last N sessions (based on profile), sorted by date.
    """
    if not sessions or not profile.get("include_sessions", True):
        return []

    # Sort by timestamp descending (most recent first)
    sorted_sessions = sorted(
        sessions,
        key=lambda s: s.get("timestamp", ""),
        reverse=True,
    )

    # Cap at a reasonable number
    max_sessions = min(5, len(sorted_sessions))
    return sorted_sessions[:max_sessions]


def _build_context_slices(
    decisions: list[dict],
    sessions: list[dict],
    profile: dict[str, Any],
) -> list[ContextSlice]:
    """Build prioritized context slices from decisions and sessions.
    Each slice has category, content, priority, and token estimate.
    """
    slices: list[ContextSlice] = []
    priority_cats = profile.get("priority_categories", [])

    # Decision slices: priority 0 if must-survive (#69), else 1 if matches
    # role categories, else 2
    for d in decisions:
        text = d.get("decision", "")
        context = d.get("context", "")
        confidence = d.get("confidence", {})
        tier = confidence.get("tier", "unknown") if isinstance(confidence, dict) else "unknown"
        score = confidence.get("score", 0.0) if isinstance(confidence, dict) else 0.0

        content = f"[{tier} conf={score:.2f}] {text}"
        if context:
            content += f"\nContext: {context}"

        if _is_must_survive(d):
            priority = 0
        elif _decision_matches_category(d, priority_cats):
            priority = 1
        else:
            priority = 2
        slices.append(ContextSlice(
            category="decision",
            content=content,
            priority=priority,
            token_estimate=_estimate_tokens(content),
        ))

    # Session slices: priority 3
    for s in sessions:
        summary = s.get("summary", "")
        timestamp = s.get("timestamp", "")
        date_str = timestamp[:10] if timestamp else "unknown"
        insights = s.get("insights", [])

        content = f"Session {date_str}: {summary}"
        if insights:
            content += f"\nInsights: {'; '.join(insights[:3])}"

        slices.append(ContextSlice(
            category="session",
            content=content,
            priority=3,
            token_estimate=_estimate_tokens(content),
        ))

    return slices


def _find_worst_slice(slices: list[ContextSlice]) -> int:
    """Find index of the lowest-priority slice (highest priority number)."""
    worst_idx = 0
    for i in range(1, len(slices)):
        if slices[i].priority > slices[worst_idx].priority:
            worst_idx = i
        elif (slices[i].priority == slices[worst_idx].priority
              and slices[i].token_estimate < slices[worst_idx].token_estimate):
            worst_idx = i
    return worst_idx


def _trim_to_budget(
    slices: list[ContextSlice],
    token_budget: int,
) -> tuple[list[ContextSlice], int]:
    """Trim context slices to fit within token budget.
    Remove lowest-priority slices first. Priority-0 (must-survive, #69)
    slices are never removed, even if that means the returned total
    exceeds token_budget -- protection wins over the budget as a last
    resort, rather than silently dropping something that was marked
    non-negotiable. Returns (trimmed_slices, total_tokens).
    """
    if not slices:
        return ([], 0)

    total = sum(s.token_estimate for s in slices)
    if total <= token_budget:
        result = sorted(slices, key=lambda s: (s.priority, -s.token_estimate))
        return (result, total)

    # Iteratively remove lowest-priority slices until under budget
    remaining = list(slices)
    running_total = total

    while running_total > token_budget and remaining:
        worst_idx = _find_worst_slice(remaining)
        if remaining[worst_idx].priority == 0:
            # Nothing left to remove but must-survive content -- stop,
            # even though running_total is still over token_budget.
            break
        running_total -= remaining[worst_idx].token_estimate
        remaining.pop(worst_idx)

    # Return sorted by priority (best first)
    remaining.sort(key=lambda s: (s.priority, -s.token_estimate))
    return (remaining, running_total)


def _check_completeness(
    must_survive_decisions: list[dict[str, Any]],
    context_slices: list[ContextSlice],
) -> list[HandoffCompletenessFinding]:
    """Verify every must-survive decision's text actually landed in the
    final context_slices -- checks the observable OUTCOME, independent of
    which upstream mechanism (selection cap, token trim) might have
    dropped it. Pure function, no dependency on _select_decisions/
    _trim_to_budget's internals, so it stays a real regression check even
    if those functions change later.
    """
    findings: list[HandoffCompletenessFinding] = []
    for d in must_survive_decisions:
        if not isinstance(d, dict):
            continue
        text = d.get("decision", "")
        if not text:
            continue
        survived = any(
            isinstance(s.content, str) and text in s.content
            for s in context_slices
            if s is not None
        )
        if survived:
            continue
        decision_id = d.get("id", "")
        raw = f"handoff_completeness{decision_id}{text}"
        fid = hashlib.sha256(raw.encode()).hexdigest()[:12]
        findings.append(HandoffCompletenessFinding(
            id=fid,
            severity="high",
            decision_id=decision_id,
            decision_text=text,
            category="handoff_completeness",
            description=f"Must-survive decision was dropped from the handoff packet: {text[:100]}",
            recommendation="Increase the token budget, or review why this decision wasn't protected (#69).",
        ))
    return findings


def _format_skills_summary(
    memory: dict,
    profile: dict[str, Any],
) -> dict[str, Any] | None:
    """Extract agent skills summary if relevant to this role.
    Returns {category: proficiency_level} or None if not relevant.
    """
    if not profile.get("include_skills", False):
        return None

    patterns = memory.get("patterns", [])
    if not patterns:
        return None

    skills: dict[str, str] = {}
    for p in patterns:
        name = p.get("name", "")
        if ":" in name:
            category = name.split(":")[0]
            count = p.get("count", 0)
            if count >= 5:
                skills[category] = "proficient"
            elif count >= 2:
                skills[category] = "learning"
            else:
                skills[category] = "novice"

    return skills if skills else None


def build_handoff_packet(
    project: str,
    role: str,
    memory: dict,
    token_budget: int = 4000,
) -> HandoffPacket:
    """Main entry point. Build a role-aware context packet.

    Steps:
    1. Look up role profile (default to CoderAgent if unknown)
    2. Score decisions with knowledge_decay
    3. Select decisions for this role
    4. Select sessions for this role
    5. Build context slices
    6. Trim to token budget
    7. Format skills summary
    8. Return HandoffPacket
    """
    # 1. Look up role profile (default to CoderAgent if unknown)
    profile = ROLE_PROFILES.get(role, ROLE_PROFILES["CoderAgent"])

    # 2. Score decisions with knowledge_decay
    decisions = memory.get("decisions", [])
    scored = score_decisions(decisions) if decisions else []

    # 3. Select decisions for this role
    selected_decisions = _select_decisions(decisions, profile, scored)

    # 4. Select sessions for this role
    sessions = memory.get("session_history", [])
    selected_sessions = _select_sessions(sessions, profile)

    # 5. Build context slices
    slices = _build_context_slices(selected_decisions, selected_sessions, profile)

    # 6. Trim to token budget
    effective_budget = min(profile.get("max_tokens", token_budget), token_budget)
    trimmed, token_count = _trim_to_budget(slices, effective_budget)

    # 7. Format skills summary
    skills = _format_skills_summary(memory, profile)

    # 7.5. Verify must-survive decisions actually made it into the final
    # slices (#69) -- regression safety net, see _check_completeness.
    must_survive_decisions = [d for d in selected_decisions if _is_must_survive(d)]
    completeness_findings = _check_completeness(must_survive_decisions, trimmed)

    # 8. Return HandoffPacket
    now = datetime.now(timezone.utc).isoformat()
    return HandoffPacket(
        role=role,
        project=project,
        context_slices=trimmed,
        active_decisions=selected_decisions,
        recent_sessions=selected_sessions,
        token_count=token_count,
        token_budget=effective_budget,
        skills_summary=skills,
        generated_at=now,
        completeness_findings=completeness_findings,
    )
