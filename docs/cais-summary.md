# CAIS Research Grant Proposal: Tropelex

## Project Title
Tropelex: Immutable Decision Memory as Infrastructure Against Agentic Objective Drift and Reward Hacking

## Abstract
As LLM-based autonomous agents perform multi-step software engineering and operational tasks, they frequently suffer from objective drift — silently altering program semantics or bypassing constraints to achieve local task completion. Tropelex provides open-source, deterministic safety infrastructure that lets autonomous agents cross-reference an immutable decision graph before committing code or system state changes. By pairing a pre-write policy check with automated ghost-decision (silent drift) detection, Tropelex works toward reducing agentic reward hacking at the execution boundary.

## Technical Safety Problems Addressed
- **Agentic Reward Hacking & Intent Drift:** Autonomous agents optimized for short-term goal fulfillment (e.g., passing a unit test) can refactor or delete constraints without explicit human approval.
- **Context Degradation & Prompt Injection:** Long-horizon agent runs suffer from context truncation and payload optimization attacks, causing agents to lose track of operational guardrails.

## Architecture & Core Safety Primitives
- **Pre-Action Guard Gate (`Preventive Ghost Checks`):** A pre-write hook that evaluates a proposed diff against active recorded decisions before the change persists.
- **Silent Objective-Drift Detection (`Ghost Decisions`):** An analyzer that flags code diffs or structural mutations contradicting recorded system rationale without anyone raising an explicit contradiction flag.
- **Contradiction Surface Detection (`Contradiction Detection`):** Scans for unresolved conflicting decisions recorded in the project's memory.
- **Forensic State Reconstruction (`Time-Travel Debugger`):** Deterministic playback of the decision graph as of any historical date, for postmortem review.
- **Tamper-Evident Decision History (`Provenance Chain`):** Every decision carries a content hash resynced on each legitimate mutation and logged as its own hash-chained audit event; `verify_integrity` independently cross-checks a decision's current hash against the audit trail's own record, catching direct edits to the underlying store that bypass the API entirely — what makes forensic postmortem review (above) a checkable claim rather than an assumption.

See [SAFETY.md](../SAFETY.md) for the full mapping of these features to safety terminology, and the project [README](../README.md) for the complete feature set.

## Deliverables & Milestones
1. **Empirical Drift-Bench Suite:** An open-source benchmark measuring agent compliance against pre-write checks under simulated objective-drift and prompt-injection scenarios.
2. **Standardized MCP Safety Adapter:** A Model Context Protocol interface enabling decision auditing for Claude Desktop and other MCP-compatible agent runtimes (current implementation targets Claude Code / MCP clients; broader runtime support is proposed future work).
3. **Verification Metric Report:** Quantitative analysis of guardrail-drift detection rates across real multi-step development sessions, building on the project's existing test suite (2,674+ passing unit tests as of this writing).

## Evaluation & Limitations
Drift-Bench (14 scenarios, 6 categories) currently measures 0.7143 overall detection with 0.0 false positives anywhere in the corpus:

| Category | Detection rate | False-positive rate |
|---|---|---|
| Silent objective drift | 1.0 | 0.0 |
| Unresolved conflicting decisions | 1.0 | 0.0 |
| Tool-output injection | 1.0 | 0.0 |
| Handoff constraint-dropping | 1.0 | 0.0 |
| Test-passing reward hacking | **0.5** | 0.0 |
| Multi-step drift | **0.0** | 0.0 |

**Test-passing reward hacking moved from 0.0 to 0.5 on 2026-09-01**, and the reason it's exactly 0.5 rather than higher is itself the honest finding: this category holds two independent evasion shapes, and only one is caught. The keyword-evasion backdoor diff (unrelated code with no keyword overlap against the violated decision) still beats Ghost Decisions outright — that half stays at 0.0. The tautological-assertion diff (`assert x == y` rewritten to `assert x == x`) is now caught by a new, purpose-built detector (`core/reward_hacking/detector.py`) that needs no decision at all — it looks at the diff's own deletions and additions for a rewrite that can never fail again, scoped to file paths or decision context naming something high-risk (auth, payment, credentials, etc.). It runs alongside Ghost on every real pre-write check (`core/ghost/preventive_router.py`), not as a separate opt-in path, and is deliberately high-precision/low-recall rather than comprehensive — the goal was moving the published number honestly, not claiming the category solved.

**Multi-step drift stays at 0.0** — a decision violated gradually across several individually-clean diffs, none of which trips a warning on its own, because Ghost (and the new assertion-weakening detector) both check one diff at a time with no session-level memory. This is the harder, still-open half of this grant's reward-hacking and execution-boundary-drift focus; closing it (a session-aware detection layer accumulating signal across a rolling window of diffs, not more keyword scenarios) is the highest-leverage remaining use of grant funding.

**Quantitative pilot: real production prevention signal.** Distinct from Drift-Bench above (synthetic scenarios built to probe specific failure modes): `core/prevention_report.py` aggregates the append-only audit trail (`core/audit.py`) into real detection/override signal from Tropelex's own actual development history, not a constructed session. As of 2026-08-31, the project's own audit log (249 total events since the gate mechanism shipped 2026-08-09) shows 6 prevention-relevant events over roughly three weeks of real multi-agent development on this codebase: 2 `gate_warned` (medium-severity Ghost warnings), 4 `contradiction_escalated` (high-severity contradiction findings), 0 `gate_blocked`, 0 overrides — override rate 0.0. Reproducible directly against any live instance's own history via `GET /{project}/prevention-report`.

Honest read of a small sample: zero overrides in three weeks doesn't establish a low false-positive rate — with only 6 signal events total, the sample is too small to support a rate claim, and it's equally consistent with the gate rarely firing on real work as with it firing and simply not yet being disputed. What it does establish is that the mechanism is live, has been exercised under real multi-agent development for three weeks, and every firing — and every non-override where nothing was contested — is independently reconstructable from the audit trail rather than asserted from memory. A larger-volume study (more projects, a longer window, or deliberately constructed sessions that exercise the override flow, which real usage hasn't touched yet) is the natural next step once usage grows past one project's early history.

Ghost Decisions itself runs on keyword/topic overlap, not semantic understanding, by design choice rather than oversight: an embedding-similarity upgrade was built (`core/ghost/preventive.py` accepts optional decision/diff embeddings) and evaluated before being wired into the live gate. A dry-run found true-positive and false-positive similarity scores (0.29 vs. 0.65) don't separate cleanly — shared surface vocabulary between unrelated decisions and diffs produces false-positive similarity as high as genuine matches. It was deliberately not shipped to the live path rather than shipping a detector that doesn't reliably discriminate. An LLM-based intent check (not raw embedding similarity) is the next candidate, not yet built or evaluated.

Session-Shape baselining (anomaly detection on session-level behavioral metrics: edit velocity, revert rate, file churn) is implemented and tested, but deliberately observational only — no anomaly currently escalates to a review trigger or gate action. Wiring that connection is open, pending real base-rate data to set thresholds that won't produce noise-level false-positive rates in practice.

## Current State
This is an early-stage, actively developed open-source project, not a completed research product. The primitives above are implemented and tested; the benchmark suite and cross-runtime adapter are proposed work this grant would fund.
