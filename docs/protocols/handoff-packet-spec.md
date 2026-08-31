# Agent Handoff Packet Protocol — v1.0

**Status:** Describes what Tropelex implements and ships today (`core/handoff/`). No commitment yet that any other agent framework (AutoGen, CrewAI, LangGraph, or otherwise) implements this — see [Compatibility status](#compatibility-status) below.

## 1. Purpose

An **Agent Handoff Packet** is a role-aware bundle of project context — decisions, their rationale, active goals, recent session history — built for handing work between two agents, or between two sessions of the same agent, without silently losing *why* something is true along the way. It's the concrete artifact behind the "how do decentralized agents stay coordinated without a shared context window" problem.

This document specifies the packet's wire format and the two invariants that make it more than a context dump: **must-survive protection** (a subset of content is exempt from token-budget trimming) and **completeness verification** (a separate check confirms that protection actually held). Both are described here independent of Tropelex's Python implementation, so a compatible packet could in principle be produced or consumed by another framework's own tooling.

## 2. Wire format: `HandoffPacket`

A packet is a JSON object with these fields:

| Field | Type | Description |
|---|---|---|
| `role` | string | The receiving agent's role. See [Role profiles](#4-role-profiles). |
| `project` | string | The project this context was built from. |
| `context_slices` | array of [`ContextSlice`](#3-contextslice) | The actual bundled context, sorted best-first (lowest `priority` number first). |
| `active_decisions` | array of objects | The raw decision records selected for this role, before slicing — implementation detail exposed for callers that want the unsliced form; not required for a compatible consumer. |
| `recent_sessions` | array of objects | The raw session-history records selected for this role, same caveat as `active_decisions`. |
| `token_count` | integer | Total estimated tokens across `context_slices` after trimming. |
| `token_budget` | integer | The effective budget trimming was performed against (`min(role's max_tokens, requested token_budget)`). |
| `skills_summary` | object or `null` | `{category: proficiency_level}`, only populated for roles that request it (see [Role profiles](#4-role-profiles)). |
| `generated_at` | string (ISO 8601, UTC) | When this packet was built. |
| `completeness_findings` | array of [`HandoffCompletenessFinding`](#6-completeness-verification) | Non-empty only if must-survive protection somehow failed — see §6. Expected to be empty in every correct implementation. |
| `packet_hash` | string | SHA-256 hex digest — see [§7 Packet hashing](#7-packet-hashing). Added by the transport layer, not part of the packet's own content for hashing purposes. |

## 3. `ContextSlice`

The atomic unit of bundled context:

| Field | Type | Description |
|---|---|---|
| `category` | string | One of `"decision"`, `"session"`, `"goal"`. |
| `content` | string | Human-readable text — a formatted decision, session summary, or goal reminder. Not further structured; a consuming agent reads this as prose. |
| `priority` | integer | **0 = must-survive** (never trimmed, see §5). 1 = matches the receiving role's priority categories. 2 = decision, doesn't match. 3 = session summary. Lower number = kept first when trimming to budget. |
| `token_estimate` | integer | `len(content) // 4` — a rough, deliberately simple estimate (not a real tokenizer call), consistent across every slice so relative comparisons during trimming stay meaningful even though the absolute number is approximate. |

## 4. Role profiles

A packet is built for a named role, which determines what gets prioritized and how much budget it gets. Tropelex ships five: `CoderAgent`, `TestEngineer`, `Architect`, `FrontendSpecialist`, `DevOpsSpecialist` — each with a `priority_categories` list (which decision categories count as priority-1), `max_decisions`, `max_tokens`, and whether sessions/skills are included at all. An unrecognized role falls back to `CoderAgent`'s profile rather than erroring. `GET /{project}/handoff/roles` lists the available roles and their descriptions. A compatible implementation can define its own role set; the protocol only requires that *some* role resolution happens, not this specific list.

## 5. Must-survive protection

A decision qualifies as **must-survive** if it's explicitly flagged (`must_survive: true`) or its `safety_metadata.risk_level` is `"high"` or `"critical"`. Must-survive decisions get two guarantees a normal decision doesn't:

1. **Exempt from the selection cap.** A role's `max_decisions` limit doesn't apply to must-survive decisions — a critical decision that doesn't even match the role's priority categories still makes it into consideration, rather than never reaching the packet-building step at all.
2. **Exempt from budget trimming.** When `context_slices` collectively exceed `token_budget`, lowest-priority slices are removed first (see `priority` in §3) — but a priority-0 slice is never removed, even if that means the packet's real `token_count` ends up over `token_budget`. Protection wins over the budget as a last resort, rather than silently dropping something marked non-negotiable.

Active project goals get the same priority-0 treatment (capped at 5, highest-priority-first) — the "why are we doing this" framing is meant to survive every handoff intact, not just individual decisions.

## 6. Completeness verification

Must-survive protection (§5) is a mechanism; completeness verification is a separate, independent check that the mechanism actually worked. After trimming, every decision that qualified as must-survive is checked: does its decision text actually appear in the final `context_slices`? If not, a `HandoffCompletenessFinding` is produced:

| Field | Type | Description |
|---|---|---|
| `id` | string | Deterministic ID (`sha256(f"handoff_completeness{decision_id}{text}")[:12]`) — stable across repeated checks of the same violation. |
| `severity` | string | Always `"high"`. |
| `decision_id` | string | The dropped decision's ID. |
| `decision_text` | string | The dropped decision's full text. |
| `category` | string | Always `"handoff_completeness"`. |
| `description` | string | Human-readable summary, decision text truncated to 100 chars. |
| `recommendation` | string | What to do about it. |

In a correct implementation this list should always be empty — §5's protection is unconditional, so nothing should ever fail this check. It exists as a regression safety net: this check reads the *observable outcome* (did the text land in the slices), not the internals of whichever selection/trimming step might have a bug, so it stays meaningful even if those steps change.

## 7. Packet hashing

The transport layer computes a SHA-256 hash over the packet **before** the `packet_hash` field itself is added:

```
packet_hash = sha256(json.dumps(packet_without_packet_hash_field, sort_keys=True, default=str)).hexdigest()
```

`sort_keys=True` makes the hash order-independent — two structurally identical packets serialized in different key order hash the same. This hash is logged to an append-only, hash-chained audit trail at generation time (`handoff_created` event) and is the reference a receiving agent cites when acknowledging the packet (§8) — tamper-evident by construction: a packet edited after the fact won't match its own logged hash.

## 8. Endpoints (Tropelex's own transport)

The wire format above is transport-independent; Tropelex exposes it over HTTP today:

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/{project}/handoff` | Build and return a packet. Body: `{role, token_budget?, agent_name?}`. Logs a `handoff_created` audit event (and a `handoff_completeness_violation` event per finding, if any) as a side effect. |
| `POST` | `/{project}/handoff/acknowledge` | Record that a receiving agent acknowledged a specific packet by hash. Body: `{packet_hash, agent_name?, acknowledged_constraints?}`. 404s if `packet_hash` doesn't match a real `handoff_created` event — rejects acking a packet that was never actually generated. Voluntary: nothing is gated on acknowledgment. |
| `GET` | `/{project}/handoff/unacknowledged` | List generated-but-never-acknowledged packets — a triage queue. |
| `GET` | `/{project}/handoff/completeness-violations` | List any recorded `HandoffCompletenessFinding`s from past packet generations. |
| `GET` | `/{project}/handoff/roles` | List available role names and descriptions. |

An MCP tool (`get_handoff_packet`) wraps the same underlying call for MCP-capable clients — see [`mcp_server/README.md`](../../mcp_server/README.md).

## Compatibility status

This spec describes what's implemented and tested in this repository (`core/handoff/packet_builder.py`, `core/handoff/router.py`) today. It has only ever been exercised against Tropelex's own clients — the dashboard, the MCP server, the OpenCode/Emacs integrations. Nothing about compatibility with AutoGen, CrewAI, LangGraph, or any other multi-agent framework's own runtime has been built or tested. Publishing this document is a prerequisite to that becoming a testable claim, not a claim that it's already true.

## Versioning

v1.0 reflects the schema as of 2026-08-31. Future changes that alter field meaning or remove a field should bump the major version; additive fields (a consumer can safely ignore a field it doesn't recognize) can land under the same major version.
