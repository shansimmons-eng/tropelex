# Safety & Alignment Properties

Tropelex is built as a persistent decision-memory system for AI coding agents. That framing ("developer productivity tool") is accurate, but incomplete. The same mechanisms that make an agent's memory useful also constrain and audit its behavior: an immutable decision history an agent is forced to cross-reference before acting, drift detection that catches code silently diverging from stated intent, and multi-agent handoff protocols that carry rationale across agent boundaries instead of losing it.

This document asserts those properties explicitly, for anyone evaluating Tropelex as safety-relevant infrastructure rather than just a productivity tool. Every mechanism described below is implemented and tested in this repository today: nothing here is a roadmap item. See [`wishlist.md`](wishlist.md) for what's still planned.

**Scope note:** none of this is a formal alignment guarantee. It's infrastructure that makes certain failure modes (silent objective drift, unresolved conflicting decisions, context loss across agent handoffs) visible and checkable rather than invisible by default. Treat it as a foundation to build evaluations and guardrails on.

---

## Prompt-Injection & Payload Defense

**Mechanism:** Context Compressor (`core/context-compressor/`, `core/compression/`)

Strips filler and normalizes prompt content before it reaches the model: using an LLM pass when a key is configured, or deterministic dictionary rules otherwise. A side effect of normalization is a reduction in the surface area available for injected instructions riding along inside otherwise-legitimate context (pasted logs, scraped pages, tool output). This is not a dedicated injection filter: it's a general compression pass that happens to shrink that attack surface as a byproduct of its primary job.

## Guardrail Ossification Prevention

**Mechanism:** Knowledge Decay (`core/knowledge_decay.py`)

Every decision's confidence score decays over time by default (`half_life_days`-based, currently 90 days). A decision made months ago doesn't retain full authority forever just because nobody revisited it; stale guardrails and policies lose confidence automatically rather than silently continuing to govern behavior as the system and its environment change around them.

## Silent Objective-Drift Detection

**Mechanism:** Ghost Decisions (`core/ghost/detector.py`, `core/ghost/pattern_matcher.py`)

Scans code changes for keyword/topic overlap against recorded decisions and flags cases where a change appears to contradict a decision with no one having explicitly revisited or superseded it: the "nobody said anything, but the code stopped matching the stated intent" failure mode.

## Pre-Action Policy Compliance Gate

**Mechanism:** Preventive Ghost Checks (`core/ghost/preventive.py`, `core/ghost/preventive_router.py`)

Runs the same drift-detection logic *before* a diff is committed, not after: `POST /api/memory/{project}/ghost-check` takes a proposed unified diff and returns severity-scored warnings against every active decision it touches. Designed as a literal pre-write hook: call it before finalizing a change.

## Configurable Gate-Severity Policy

**Mechanism:** Gate Policy Schema (`core/ghost/preventive_router.py`)

Each of the three severity tiers the pre-action gate above can raise (`high`/`medium`/`low`) is independently configurable to one of three actions (`block`/`warn`/`log_only`) via a validated schema (`GatePolicyRequest`, extra fields rejected) — `PUT /{project}/gate-policy` sets it, `GET /{project}/gate-policy` shows the effective policy alongside defaults and any overrides. Worth being precise about scope here: this is a bounded tier-to-action mapping, not a general policy language — enforcement is configurable, not arbitrarily programmable.

## Safety-Budget Escalation

**Mechanism:** Safety Budget (`core/safety_budget.py`)

Distinct from any single decision's own risk score: sums a weighted per-agent signal across overrides (weighted highest), gate-blocked/gate-warned severity events, and high/medium-risk decisions captured, and flags when an agent crosses a configurable threshold. This is a cumulative-pattern check — an agent whose individual actions each look acceptable in isolation but who's accumulating overrides and high-severity gate events over a session gets flagged even though no single action triggered it.

## Conflicting-Objective Surfacing

**Mechanism:** Contradiction Detection (`core/contradictions/detector.py`)

Scans all decision pairs for direct contradictions (opposing-keyword pairs: "use" vs. "don't use," "always" vs. "never"), mutually-exclusive technology choices (REST vs. GraphQL, SQL vs. NoSQL), and implicit/temporal conflicts, scored by severity and returned with a resolution suggestion. Unresolved conflicting objectives sitting in a decision graph are exactly the kind of thing that's easy to lose track of across a long agent session: this makes them queryable.

## Human-in-the-Loop Alignment Elicitation

**Mechanism:** Friction Mining (`core/friction/miner.py`)

Scans conversation transcripts for rephrasing ("no, actually...", "that's wrong"), escalation ("as I said," "how many times do I have to explain this"), retry, and rapid-edit patterns, and scores a friction level with zone-level detail. These are moments of implicit human correction: a lightweight, always-on channel for capturing preference signal that would otherwise be discarded once the conversation scrolled past it.

## Inter-Agent Coordination Protocol

**Mechanism:** Agent Handoff Packets (`core/handoff/packet_builder.py`, `core/handoff/router.py`)

Builds role-aware context bundles (not raw state, but state plus the rationale behind it) for handing work between distinct agents (or distinct sessions of the same agent). This is the concrete mechanism for the "how do decentralized agents stay coordinated without a shared context window" problem: the packet is the coordination artifact.

## Must-Survive Decision Protection

**Mechanism:** Priority-Tiered Packet Selection (`core/handoff/packet_builder.py`)

A decision qualifies as must-survive either explicitly (`must_survive: true`) or automatically (`safety_metadata.risk_level` of `high`/`critical`). Must-survive decisions are exempt from the packet's `max_decisions` cap and protected from removal even when the packet has to be trimmed to fit a token budget — a context-starved handoff can silently drop a routine decision to make room, but not a high-risk one.

## Handoff Completeness Verification

**Mechanism:** Completeness Check (`core/handoff/packet_builder.py`, `core/handoff/router.py`)

A separate check from the protection above: after a packet is built, `_check_completeness()` verifies the must-survive decisions that were *supposed* to make it in actually did, and raises a `HandoffCompletenessFinding` (surfaced via `GET /needs-attention` and a dedicated endpoint) if any didn't. This asks "did the protection actually work" as its own checkable question, distinct from "did we attempt to protect it."

## Goal Re-Anchoring

**Mechanism:** Priority-0 Goal Slices (`core/handoff/packet_builder.py`, `core/prefetch/router.py`)

Active project goals ride in every context bundle and handoff packet at the same priority-0 tier as must-survive decisions — not subject to the relevance-scored knapsack that ranks everything else by impact. The "why are we doing this" framing survives every context handoff intact, not just individual decisions.

## Calibration & Honest-Signaling Mechanism

**Mechanism:** Decision Market (`core/market/calibration.py`, `core/market/router.py`)

Agents (or reviewers) place confidence bets on decisions; a leaderboard tracks calibration over time: who's overconfident, who's well-calibrated, on which categories. It's a small mechanism-design surface for eliciting and scoring honest confidence reporting rather than just accepting stated confidence at face value.

## Coordination Drift Detection

**Mechanism:** Cross-Agent Agreement Tracking (`core/market/coordination.py`)

Distinct from the per-agent calibration above: detects declining agreement between *multiple* agents' calibration profiles over time. Two agents can each look individually well-calibrated while steadily diverging from each other — this surfaces that pattern directly instead of relying on any single agent's own accuracy trend to reveal it.

## Forensic State Auditing

**Mechanism:** Time-Travel Debugger (`core/timetravel/`)

Reconstructs project memory as it existed as of any past date, replaying recorded sessions up to that point. Built for the postmortem question: "what would an agent operating at that point in time have actually known when it made this call?" This functions as an audit trail that survives long after the original session context is gone.

## Instance Access Control

**Mechanism:** Shared-Secret Authentication + Host Validation (`core/auth/shared_secret.py`)

Every mutating API call requires an instance-scoped secret (auto-generated on first run, read from `.env` by every client: dashboard, MCP server, OpenCode plugin, VSCode extension, Emacs package), unless the request itself is a genuinely same-origin browser call the browser's own `Sec-Fetch-Site` header proves (a header page JavaScript cannot forge). A separate Host-header check rejects any request not addressed to the instance's own hostname, closing the DNS-rebinding path that CORS alone doesn't cover. This exists because "an agent's memory system" is also a live write surface: without it, any local process (not just the intended clients) could mutate decision history, escalate reviews, or read project memory.

## Tamper-Evident Decision History

**Mechanism:** Decision Content Hashing (`core/audit.py`)

Every decision carries a content hash computed from its decision text, context, and safety metadata at write time, resynced on every legitimate mutation (review, rollback, tag change, auto-escalation) via `resync_decision_hash`, and logged as its own hash-chained audit event. `verify_integrity` recomputes each decision's hash from its current content and separately cross-checks it against the audit trail's own record of the last legitimate write. So, an edit made directly to the underlying JSON file (bypassing the API entirely) is caught even if the attacker also recomputes and overwrites the stored hash to match. This is due to the fact that the audit trail's copy is independent and itself hash-chained which constitutes an "immutable decision history" (see this document's opening paragraph) a checkable claim rather than an assumption: a decision predating this mechanism is honestly reported as `unverified_hash`, never silently assumed clean.

---

## What this is not

- **Not a safety evaluation suite.** Tropelex doesn't red-team a model or measure capability elicitation. It's memory and coordination infrastructure that other evaluation work can build on top of.
- **Not a guarantee of correct behavior.** Every mechanism above surfaces information (a contradiction, a drift warning, a calibration score); none of them can force an agent to act on it. The value is in making failure modes checkable, not in preventing them outright.
- **A general-purpose MCP server exists** ([`mcp_server/`](mcp_server/)) exposing decision capture, contradiction checks, context bundling, agent handoff packets, and calibration data as MCP tools, so any MCP-capable agent (not just Tropelex's own editor integrations) can read and write this infrastructure directly. Currently a curated subset of the full REST API; see `mcp_server/README.md` for the tool list.

If you're evaluating Tropelex for a grant, fellowship, or collaboration and want more detail on any of the above, the relevant source files are linked next to each mechanism: everything described here is real, shipped, and tested.
