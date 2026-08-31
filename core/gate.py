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

# Condition keys a gate rule (#101) may match on. Deliberately a closed,
# small set of literal-equality checks -- no boolean expressions, no
# operators, nothing that needs an evaluator. A rule that references any
# other key, or whose "if" isn't a dict, is skipped rather than raising:
# same "malformed data degrades to the safe default, never crashes the
# gate" posture policy_for already had before rules existed.
GATE_RULE_CONDITION_KEYS = frozenset({"severity", "agent_name", "category"})

# Bounds enforced at the API boundary (GateRulesRequest), restated here as
# the single source of truth pure-logic side can assert against in tests.
MAX_GATE_RULES = 20


def _rule_matches(rule: Any, severity: str, context: dict[str, Any]) -> bool:
    """True if every condition in rule["if"] holds against this check.

    Conditions are ANDed. An empty (or absent) "if" matches unconditionally
    -- a deliberate way to write a catch-all/new-default rule, not an
    oversight. "category" matches if it appears anywhere in
    context["categories"] (a decision can carry several); the other two
    keys are plain equality against context["agent_name"] / the `severity`
    policy_for was already asked to resolve.
    """
    if not isinstance(rule, dict):
        return False
    condition = rule.get("if")
    if condition is None:
        condition = {}
    if not isinstance(condition, dict):
        return False

    # A key that's absent OR explicitly None both mean "no constraint on
    # this key" -- the API layer's model_dump(by_alias=True) persists
    # every GateRuleCondition field, including ones the caller never set,
    # as an explicit None, so `None` has to be treated the same as
    # "not present" here, not as "must equal None".
    condition_severity = condition.get("severity")
    if condition_severity is not None and condition_severity != severity:
        return False
    condition_agent = condition.get("agent_name")
    if condition_agent is not None and condition_agent != context.get("agent_name"):
        return False
    condition_category = condition.get("category")
    if condition_category is not None and condition_category not in (context.get("categories") or []):
        return False
    return True


def policy_for(
    memory: dict[str, Any],
    severity: str,
    *,
    key: str = "gate_policy",
    context: dict[str, Any] | None = None,
    rules_key: str = "gate_rules",
) -> str:
    """Resolve the enforcement action for a severity tier.

    Resolution order, first match wins:
    1. (#101) If `context` is given, memory[rules_key] -- an ordered list
       of {"if": {...}, "then": action} rules -- is checked top to bottom;
       the first rule whose conditions all match returns its action.
       `context` is opt-in (None by default) precisely so every pre-#101
       caller (Contradiction Detection's own policy_for(..., key=
       "contradiction_gate_policy") call, any test written before rules
       existed) keeps byte-identical behavior -- passing no context skips
       rule evaluation entirely, not "evaluates against an empty context".
    2. memory[key] (the existing flat tier->action override, #64) if the
       tier is set and recognized.
    3. DEFAULT_GATE_POLICY.

    Defensive against malformed stored data at every step -- memory[key]
    or memory[rules_key] not being the right shape, or a value not being a
    recognized action, all fall through to the next step instead of
    propagating garbage into a live block/warn/log_only decision.
    """
    if context is not None:
        rules = memory.get(rules_key)
        if isinstance(rules, list):
            for rule in rules:
                if _rule_matches(rule, severity, context):
                    action = rule.get("then") if isinstance(rule, dict) else None
                    if action in GATE_ACTIONS:
                        return action
                    break  # matched but malformed action -- don't fall through past it silently

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
