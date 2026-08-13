"""
Generalized soft-enforcement gate (#72).

The `block`/`warn`/`log_only` severity policy #53 built specifically for
Ghost Preventive Checks (core/ghost/preventive_router.py's `_policy_for`),
extracted so any detector can reuse the same resolution + override
mechanism instead of inventing its own copy — same "shared module beats
two copies" reasoning already applied to core/audit.py (#52) and
core/result.py (#50).

Two independent detectors can gate on different severities of different
things (a Ghost warning against one decision vs. a Contradiction between
two), so `policy_for`/`overridden_ids` both take an explicit storage
`key` rather than hardcoding "gate_policy"/"overrides" — each detector's
own project-level override state stays separate, not silently shared
with a mechanism it wasn't consulted on. A `decision_id` override is
still reusable *across* detectors, though: "I've accepted the risk on
this decision" is a property of the decision, not of which detector
happened to raise the warning, so both Ghost and Contradictions call
`overridden_ids(memory, key="overrides")` against the same list by
default — the whole point of Override-as-Decision being a single audited
mechanism rather than one per detector.
"""

from __future__ import annotations

from typing import Any

DEFAULT_GATE_POLICY: dict[str, str] = {"high": "block", "medium": "warn", "low": "log_only"}
GATE_ACTIONS = {"block", "warn", "log_only"}
GATE_SEVERITIES = ("high", "medium", "low")


def policy_for(memory: dict[str, Any], severity: str, *, key: str = "gate_policy") -> str:
    """Resolve the enforcement action for a severity tier: project override
    (memory[key]) if set and recognized, else the module default.

    Defensive against malformed stored data (#64's own hardening,
    generalized here) -- memory[key] not being a dict, or a tier's value
    not being a recognized action, both fall back to the default instead
    of propagating garbage into a live block/warn/log_only decision.
    """
    overrides = memory.get(key)
    if not isinstance(overrides, dict):
        overrides = {}
    value = overrides.get(severity)
    if value not in GATE_ACTIONS:
        return DEFAULT_GATE_POLICY.get(severity, "log_only")
    return value


def overridden_ids(memory: dict[str, Any], *, key: str = "overrides") -> set[str]:
    """Decision IDs with at least one recorded override under `key` —
    suppresses blocking for that decision going forward, same as #53's
    original _overridden_decision_ids. The override stays visible in
    whatever response surfaces it (severity/warning untouched); it just
    stops forcing a non-2xx result once a human/agent has explicitly
    accepted the risk."""
    overrides = memory.get(key)
    if not isinstance(overrides, list):
        return set()
    return {
        o["decision_id"] for o in overrides
        if isinstance(o, dict) and o.get("decision_id")
    }
