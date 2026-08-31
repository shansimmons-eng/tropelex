"""
Preventive Ghost Checks — FastAPI router.

Pre-write guardrail: checks a proposed diff against active decisions
before code is written, surfacing warnings as a guardrail.

Mount into the main app:
    from core.ghost.preventive_router import preventive_router
    app.include_router(preventive_router)
"""

import logging
import uuid as _uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from core.audit import append_audit_event
from core.gate import (
    DEFAULT_GATE_POLICY,
    GATE_ACTIONS,
    GATE_SEVERITIES,
    MAX_GATE_RULES,
    overridden_ids,
    policy_for,
)
from core.ghost.preventive import check_diff_for_warnings
from core.memory.manager import MemoryManager
from core.prevention_report import build_prevention_report
from core.telemetry import _emit_telemetry

logger = logging.getLogger("tropelex.ghost.preventive")

preventive_router = APIRouter(prefix="/api/memory", tags=["ghost-preventive"])

_mm = MemoryManager()

# "block" means ghost_check raises instead of returning 200 — see #53
# (wishlist.md): the point is that a non-2xx response is what actually
# stops an MCP tool call (mcp_server/server.py's _request raises on any
# status >= 400), where a warning buried in a 200 body is easy for an
# agent to skip past. A project can loosen/tighten this via
# memory["gate_policy"]; unset tiers fall back to core.gate's default.
# The severity→action resolution and override lookup themselves live in
# core/gate.py (#72), generalized out of this router so Contradiction
# Detection (core/tropebook/web/server.py's add_decision) can reuse the
# exact same mechanism instead of inventing its own copy.

# #72: Contradiction Detection gates on its own "contradiction_gate_policy"
# key, not Ghost's "gate_policy" -- two different risk surfaces a project
# should be able to tune independently. GET/PUT /gate-policy (#64) now
# takes a `detector` selector so both are real, validated, discoverable
# endpoints instead of Contradictions' policy only being settable by
# hand-editing the memory JSON directly -- the exact gap #64 closed for
# Ghost, left open here otherwise.
_DETECTOR_POLICY_KEYS = {"ghost": "gate_policy", "contradictions": "contradiction_gate_policy"}


def _load_memory(project: str) -> dict[str, Any]:
    """Load a project's memory, or raise 404."""
    if project not in _mm.list_projects():
        raise HTTPException(status_code=404, detail=f"Project '{project}' not found")
    return _mm.get_project_memory(project)


def _save_memory(project: str, memory: dict[str, Any]) -> None:
    try:
        _mm.save_project_memory(project, memory)
    except Exception as exc:
        logger.error("ghost-preventive save failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


def _severity_counts(warnings: list[dict[str, Any]]) -> dict[str, int]:
    """Tally warnings by severity tier, for a single gate_blocked/gate_warned
    audit event covering a whole ghost-check call (not one event per
    warning — see #61)."""
    counts = {"high": 0, "medium": 0, "low": 0}
    for w in warnings:
        sev = w.get("severity", "low")
        if sev in counts:
            counts[sev] += 1
    return counts


class GhostCheckRequest(BaseModel):
    """Request body for pre-write ghost diff checking."""
    diff: str = Field(..., min_length=1, max_length=100000,
                      description="Unified diff text to check against decisions")
    agent_name: str = Field(
        "unspecified", max_length=100,
        description="Which agent is running this check -- attributes gate_blocked/"
        "gate_warned audit events so #73-4's per-agent safety budget can see them.",
    )


class OverrideRequest(BaseModel):
    """Request body for overriding a blocked ghost warning on a decision."""
    rationale: str = Field(..., min_length=1, max_length=1000,
                           description="Why this warning is being overridden")
    agent_name: str = Field(..., min_length=1, max_length=100)


class GatePolicyRequest(BaseModel):
    """Explicit, validated override for gate_policy (#64).

    Each severity tier is optional -- an unset tier keeps whatever it was
    (module default if never overridden at all), same partial-override
    behavior core.gate.policy_for already had; this doesn't force every
    PUT to restate all three. But any tier that IS given must be a
    recognized action, and extra="forbid" rejects a key that isn't a real
    severity tier (e.g. a typo'd "hihg") with a 422 instead of the old
    behavior -- silently writable, silently never read.
    """
    model_config = ConfigDict(extra="forbid")

    high: str | None = Field(None, pattern="^(block|warn|log_only)$")
    medium: str | None = Field(None, pattern="^(block|warn|log_only)$")
    low: str | None = Field(None, pattern="^(block|warn|log_only)$")


class GateRuleCondition(BaseModel):
    """The "if" half of one gate rule (#101). All three fields are
    optional and ANDed together; an entirely empty condition matches
    unconditionally (a deliberate catch-all, see core.gate._rule_matches).
    Deliberately just three literal-equality fields, not an expression
    language -- see core.gate.GATE_RULE_CONDITION_KEYS's docstring for why.
    """
    model_config = ConfigDict(extra="forbid")

    severity: str | None = Field(None, pattern="^(high|medium|low)$")
    agent_name: str | None = Field(None, min_length=1, max_length=100)
    category: str | None = Field(None, min_length=1, max_length=64)


class GateRule(BaseModel):
    """One ordered rule: if `if_` matches, resolve to `then`. `if_` is
    aliased to the bare word "if" on the wire (Python reserves `if`) --
    populate_by_name lets tests/internal callers construct with either
    spelling, model_dump(by_alias=True) at the write site always persists
    the wire spelling, matching what core.gate._rule_matches reads back.
    """
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    if_: GateRuleCondition = Field(default_factory=GateRuleCondition, alias="if")
    then: str = Field(..., pattern="^(block|warn|log_only)$")


class GateRulesRequest(BaseModel):
    """Full replacement for a project's gate_rules list (#101) -- rules are
    ordered and position is meaningful (first match wins), so this is a
    PUT-the-whole-list endpoint, not per-rule PATCH/append; a client that
    wants to add one rule reads the current list first, same as any other
    ordered-collection API. MAX_GATE_RULES bounds list length so this
    can't grow into something no one can actually audit by reading it.
    """
    model_config = ConfigDict(extra="forbid")

    rules: list[GateRule] = Field(..., max_length=MAX_GATE_RULES)


@preventive_router.get("/{project}/gate-policy")
async def get_gate_policy(
    project: str, detector: str = Query("ghost", pattern="^(ghost|contradictions)$"),
) -> dict[str, Any]:
    """Read a project's gate policy (#64) -- effective per-tier action plus
    an honest default-vs-override breakdown, so it's visible from the
    response whether a project is running the module default or an
    explicit override, rather than the caller having to guess.

    `detector` (#72) selects which detector's policy: "ghost" (default,
    memory["gate_policy"]) or "contradictions"
    (memory["contradiction_gate_policy"]) -- separate keys, separate tuning,
    same validated read/write mechanism.
    """
    key = _DETECTOR_POLICY_KEYS[detector]
    memory = _load_memory(project)
    overrides = memory.get(key)
    if not isinstance(overrides, dict):
        overrides = {}
    return {
        "project": project,
        "detector": detector,
        "effective_policy": {sev: policy_for(memory, sev, key=key) for sev in GATE_SEVERITIES},
        "defaults": dict(DEFAULT_GATE_POLICY),
        "overrides": {sev: overrides[sev] for sev in GATE_SEVERITIES if overrides.get(sev) in GATE_ACTIONS},
    }


@preventive_router.put("/{project}/gate-policy")
async def set_gate_policy(
    project: str, body: GatePolicyRequest,
    detector: str = Query("ghost", pattern="^(ghost|contradictions)$"),
) -> dict[str, Any]:
    """Set a project's gate policy override (#64) -- the only way to change
    enforcement per severity tier used to be hand-editing the memory JSON
    file directly, with no validation at all. Validated at the router
    boundary (GatePolicyRequest), matching this codebase's "validate at
    the boundary, not inside pure logic" convention (#41's Decision.goal_id
    FK check is the precedent) -- core.gate.policy_for's own defensive read
    stays as a second layer for data that predates this endpoint, not the
    primary defense.

    `detector` (#72): see get_gate_policy.
    """
    key = _DETECTOR_POLICY_KEYS[detector]
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=422, detail="At least one of high/medium/low must be set")

    memory = _load_memory(project)
    existing = memory.get(key)
    if not isinstance(existing, dict):
        existing = {}
    memory[key] = {**existing, **updates}
    _save_memory(project, memory)

    return {
        "project": project,
        "detector": detector,
        "updated": True,
        "effective_policy": {sev: policy_for(memory, sev, key=key) for sev in GATE_SEVERITIES},
        "overrides": {sev: memory[key][sev] for sev in GATE_SEVERITIES if memory[key].get(sev) in GATE_ACTIONS},
    }


@preventive_router.get("/{project}/gate-rules")
async def get_gate_rules(project: str) -> dict[str, Any]:
    """Read a project's gate rules (#101) -- an ordered list evaluated
    ahead of gate_policy's flat tier->action mapping, matched against a
    Ghost warning's severity, the checking agent's name, and the
    decision's categories (see core.gate._rule_matches). Ghost only: rules
    are consulted here because ghost_check is the one call site that
    builds and passes the `context` policy_for needs (#72's shared
    tier-mapping stays the only mechanism Contradiction Detection gates
    on -- exposing a gate-rules endpoint for a detector whose call site
    never passes context would be a config knob that's silently never
    read, which this project avoids on purpose).
    """
    memory = _load_memory(project)
    rules = memory.get("gate_rules")
    if not isinstance(rules, list):
        rules = []
    return {"project": project, "rules": rules}


@preventive_router.put("/{project}/gate-rules")
async def set_gate_rules(project: str, body: GateRulesRequest) -> dict[str, Any]:
    """Replace a project's gate rules (#101) in full -- see GateRulesRequest
    for why this is whole-list PUT rather than per-rule PATCH. Validated at
    the router boundary (GateRuleCondition/GateRule/GateRulesRequest),
    same "validate at the boundary" convention set_gate_policy above
    follows; core.gate._rule_matches's own defensive checks are the second
    layer, for data that predates this endpoint or was written by hand.
    """
    memory = _load_memory(project)
    memory["gate_rules"] = [r.model_dump(by_alias=True) for r in body.rules]
    _save_memory(project, memory)
    return {"project": project, "updated": True, "rules": memory["gate_rules"]}


@preventive_router.post("/{project}/ghost-check")
async def ghost_check(project: str, body: GhostCheckRequest) -> dict[str, Any]:
    """Check a proposed diff against active decisions before writing.

    Returns warnings for any decisions that may be contradicted by the diff.
    This is a pre-write hook — call before finalizing a diff.

    Enforcement (#53): each warning's severity maps to a policy action
    (block/warn/log_only — see core.gate.policy_for). If any warning resolves to
    "block" and its decision has no recorded override, this raises 409
    instead of returning 200 — a real gate, not just data an agent can
    skip past. mcp_server/server.py's MCP wrapper raises on any non-2xx
    status, so a blocked ghost-check surfaces as a tool failure the
    calling agent has to actually handle: fix the diff, or call
    POST /{project}/decisions/{decision_id}/override with a rationale.

    #67 built a semantic-rescue mechanism into check_diff_for_warnings
    (optional embeddings/diff_embedding params, capped at "medium" severity)
    but it is deliberately NOT wired in here: a real dry-run against this
    project's own decisions found raw-diff-text-vs-decision-text cosine
    similarity for the actual target case (a keyword-evasive backdoor) at
    0.29, while a genuinely unrelated one-line typo fix scored up to 0.65
    against real decisions purely from shared surface vocabulary -- no
    threshold separates the two. Wiring this live would have repeated #57's
    own incident (an untuned semantic signal flooding a live project with
    warnings). See wishlist.md #67 for the full negative result.
    """
    try:
        memory = _load_memory(project)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("ghost-check load failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    result = check_diff_for_warnings(memory, body.diff)

    # Result type → HTTP translation
    if hasattr(result, "error"):
        # It's an Err
        code = getattr(result, "code", "UNKNOWN")
        if code == "NOT_FOUND":
            raise HTTPException(status_code=404, detail=result.error)
        raise HTTPException(status_code=500, detail=result.error)

    warnings = result.value
    severity_dist = {"high": 0, "medium": 0, "low": 0}
    for w in warnings:
        sev = w.get("severity", "low")
        if sev in severity_dist:
            severity_dist[sev] += 1

    recommendations = list({w["recommendation"] for w in warnings if w.get("recommendation")})

    overridden = overridden_ids(memory)
    # #101: categories per decision, looked up once rather than per-warning
    # -- the "category" condition a gate rule can match on comes from the
    # violated decision itself, which GhostWarning doesn't carry directly.
    decision_categories = {
        d.get("id", ""): d.get("categories") or []
        for d in memory.get("decisions", [])
        if isinstance(d, dict)
    }
    blocking: list[dict[str, Any]] = []
    warn_tier: list[dict[str, Any]] = []
    for w in warnings:
        context = {
            "agent_name": body.agent_name,
            "categories": decision_categories.get(w.get("decision_id", ""), []),
        }
        policy = policy_for(memory, w.get("severity", "low"), context=context)
        w["policy"] = policy
        w["overridden"] = w.get("decision_id") in overridden
        if w["overridden"]:
            continue
        if policy == "block":
            blocking.append(w)
        elif policy == "warn":
            warn_tier.append(w)

    _emit_telemetry("GHOST", f"Drift check run for {project} ({len(warnings)} warning(s))")

    # #61 (wishlist.md): log_only-tier warnings never got an audit trace
    # before this, and block/warn tiers only ever wrote an "override" event
    # if an agent later bypassed them — a warning that was correctly
    # obeyed left zero trace. This is what the Prevention Report reads.
    mutated = False
    if blocking:
        append_audit_event(
            memory,
            "gate_blocked",
            decision_ids=list({w["decision_id"] for w in blocking if w.get("decision_id")}),
            severity_counts=_severity_counts(blocking),
            agent_name=body.agent_name,
        )
        mutated = True
    if warn_tier:
        append_audit_event(
            memory,
            "gate_warned",
            decision_ids=list({w["decision_id"] for w in warn_tier if w.get("decision_id")}),
            severity_counts=_severity_counts(warn_tier),
            agent_name=body.agent_name,
        )
        mutated = True
    if mutated:
        _save_memory(project, memory)

    if blocking:
        raise HTTPException(status_code=409, detail={
            "message": (
                f"{len(blocking)} warning(s) blocked by gate policy — fix the diff or call "
                f"POST /api/memory/{project}/decisions/{{decision_id}}/override with a rationale to proceed."
            ),
            "project": project,
            "blocking_warnings": blocking,
            "total_warnings": len(warnings),
            "severity_distribution": severity_dist,
        })

    return {
        "project": project,
        "warnings": warnings,
        "total_warnings": len(warnings),
        "severity_distribution": severity_dist,
        "recommendations": recommendations,
    }


@preventive_router.post("/{project}/decisions/{decision_id}/override")
async def override_ghost_warning(project: str, decision_id: str, body: OverrideRequest) -> dict[str, Any]:
    """Record an explicit override for ghost/contradiction warnings against
    one decision, so future ghost-check calls stop blocking on it.

    The override itself is written into the append-only audit trail
    (core/audit.py, #52) as an "override" event — it becomes part of the
    same tamper-evident record as decision creation and review, not a
    parallel, unaudited mechanism. Warnings against the decision keep
    showing up (marked "overridden": true) — this suppresses the block,
    it doesn't hide the underlying signal.
    """
    try:
        memory = _load_memory(project)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("override load failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    if not any(d.get("id") == decision_id for d in memory.get("decisions", [])):
        raise HTTPException(status_code=404, detail=f"Decision '{decision_id}' not found in project '{project}'")

    override_id = _uuid.uuid4().hex[:12]
    override_entry = {
        "id": override_id,
        "decision_id": decision_id,
        "rationale": body.rationale,
        "agent_name": body.agent_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    memory.setdefault("overrides", []).append(override_entry)
    append_audit_event(
        memory,
        "override",
        override_id=override_id,
        decision_id=decision_id,
        rationale=body.rationale,
        agent_name=body.agent_name,
    )
    _save_memory(project, memory)
    _emit_telemetry("GHOST", f"Warning override recorded for decision {decision_id} in {project}")

    return {"created": True, "override": override_entry}


@preventive_router.get("/{project}/prevention-report")
async def prevention_report(project: str) -> dict[str, Any]:
    """"What have we prevented so far?" (#61) — aggregates the append-only
    audit trail (core/audit.py, #52) into historical counts of gate blocks,
    gate warnings, contradiction escalations, and overrides.

    Pure read over audit_log; see core/prevention_report.py for the
    aggregation itself. Historical only: events from before this feature
    shipped were never logged (gate_blocked/gate_warned/
    contradiction_escalated didn't exist as event types yet), so a project
    with a long history but no report activity isn't evidence nothing was
    ever prevented — the same honestly-disclosed backfill limitation #52
    already carries for its own audit log.
    """
    memory = _load_memory(project)
    report = build_prevention_report(memory.get("audit_log", []))
    return {"project": project, **report}
