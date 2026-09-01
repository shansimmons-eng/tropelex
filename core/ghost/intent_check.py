"""
LLM-as-intent-check (wishlist #106) -- a narrow, budgeted advisory signal
for the specific case Ghost's keyword matching structurally can't cover:
a diff that genuinely conflicts with a high/critical-risk decision but
shares no vocabulary with it.

Distinct from #67's embedding-similarity rescue, which was evaluated and
deliberately not shipped (0.29 vs. 0.65 cosine similarity on real
decisions, no clean separation -- see docs/cais-summary.md's Evaluation &
Limitations section): this asks a single structured question via a real
LLM call instead of a similarity score, and only for the narrow slice of
cases where it's worth the cost, not every diff.

Advisory only: a conflict escalates an existing warning's severity, it
never creates a new hard-block path of its own -- reuses the existing
severity->policy resolution (core/gate.py) exactly as it already exists.

Uses core.llm.chat -- the same Ollama-first/OpenAI-fallback/cost-tracked
wrapper every other LLM feature in this codebase goes through, not a new
LLM-calling path. Returns None (not a guess) whenever the check couldn't
actually run: no backend available, or the per-project daily budget is
already spent -- callers must treat None as "no additional signal,"
never as an implicit yes or no.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from core.audit import append_audit_event
from core.llm import chat as llm_chat

DEFAULT_MAX_CALLS_PER_DAY = 50

_SYSTEM_PROMPT = (
    "You are checking whether a code diff conflicts with a recorded "
    "architectural or safety decision. Answer with YES or NO on the "
    "first line (YES means the diff makes the decision false or "
    "meaningfully weaker), then exactly one sentence of rationale on "
    "the second line. Nothing else."
)


def _cache_key(decision_id: str, diff_text: str) -> str:
    return hashlib.sha256(f"{decision_id}:{diff_text}".encode()).hexdigest()


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _rate_limit_state(memory: dict[str, Any]) -> dict[str, Any]:
    """A plain per-project daily counter, persisted in project memory
    (not in-process) -- same "durable, not ephemeral" posture as
    everything else safety-adjacent in this codebase; a counter that
    resets on server restart isn't really a budget. Reset by UTC date,
    defensive against a malformed or missing prior value."""
    state = memory.get("intent_check_rate_limit")
    if not isinstance(state, dict) or state.get("date") != _today():
        state = {"date": _today(), "count": 0}
        memory["intent_check_rate_limit"] = state
    return state


def _parse_response(text: str) -> tuple[bool, str]:
    """Fail closed: anything not starting with YES (case-insensitive) on
    the first line -- including an empty or malformed response -- is
    treated as NO. A parse failure must never be silently treated as a
    conflict; the worst case of failing closed here is a missed
    escalation, not a false one."""
    lines = text.strip().splitlines()
    if not lines:
        return False, ""
    conflict = lines[0].strip().upper().startswith("YES")
    rationale = lines[1].strip() if len(lines) > 1 else ""
    return conflict, rationale


async def check_intent_conflict(
    decision_id: str,
    decision_text: str,
    diff_text: str,
    memory: dict[str, Any],
    *,
    project: str | None = None,
    max_calls_per_day: int = DEFAULT_MAX_CALLS_PER_DAY,
) -> dict[str, Any] | None:
    """Ask the single structured question: does this diff conflict with
    this decision? Returns {"conflict": bool, "rationale": str}, or None
    if the check didn't run at all (no LLM backend, or today's per-project
    budget is spent).

    Mutates `memory` in place (cache entries, the rate-limit counter, an
    audit event for every call that actually reaches this function) --
    same "caller owns persistence" contract as append_audit_event itself;
    the router must still save memory afterward.
    """
    cache = memory.setdefault("intent_check_cache", {})
    key = _cache_key(decision_id, diff_text)

    cached = cache.get(key)
    if isinstance(cached, dict) and "conflict" in cached:
        append_audit_event(
            memory, "ghost_intent_check",
            decision_id=decision_id, diff_hash=key[:12], result=cached["conflict"], cached=True,
        )
        return {"conflict": cached["conflict"], "rationale": cached.get("rationale", "")}

    rate_state = _rate_limit_state(memory)
    if rate_state["count"] >= max_calls_per_day:
        return None  # over budget for today -- skip, don't block, don't error

    response = await llm_chat(
        system=_SYSTEM_PROMPT,
        user=f"Decision: {decision_text}\n\nDiff:\n{diff_text}",
        max_tokens=120,
        project=project,
        description="ghost intent check",
    )
    rate_state["count"] += 1

    if response is None:
        append_audit_event(
            memory, "ghost_intent_check",
            decision_id=decision_id, diff_hash=key[:12], result=None, cached=False,
        )
        return None  # no LLM backend available

    conflict, rationale = _parse_response(response)
    cache[key] = {
        "conflict": conflict, "rationale": rationale,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    append_audit_event(
        memory, "ghost_intent_check",
        decision_id=decision_id, diff_hash=key[:12], result=conflict, cached=False,
    )
    return {"conflict": conflict, "rationale": rationale}
