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
Drift-Bench (14 scenarios, 6 categories, expanded 2026-08-31 with a second reward-hacking evasion shape and a new multi-step-drift category) currently measures 0.5714 overall detection with 0.0 false positives anywhere in the corpus:

| Category | Detection rate | False-positive rate |
|---|---|---|
| Silent objective drift | 1.0 | 0.0 |
| Unresolved conflicting decisions | 1.0 | 0.0 |
| Tool-output injection | 1.0 | 0.0 |
| Handoff constraint-dropping | 1.0 | 0.0 |
| Test-passing reward hacking | **0.0** | 0.0 |
| Multi-step drift | **0.0** | 0.0 |

The two 0.0 categories are published on purpose, not hidden in the aggregate: **test-passing reward hacking** — a keyword-evasion diff (functionally reward-hacking behavior described in language that avoids the detector's keyword overlap) beats the current Ghost Decisions detector outright, and a second, independent evasion shape (weakening a test assertion into a tautology instead of adding unrelated code) beats it the same way — and **multi-step drift** — a decision violated gradually across several individually-clean diffs, none of which trips a warning on its own, because Ghost checks one diff at a time with no session-level memory. Both gaps are directly relevant to this grant's own reward-hacking and execution-boundary-drift focus; closing them (a semantic/session-aware detection layer, not more keyword scenarios) is the highest-leverage use of grant funding, not a general benchmark expansion.

Ghost Decisions itself runs on keyword/topic overlap, not semantic understanding, by design choice rather than oversight: an embedding-similarity upgrade was built (`core/ghost/preventive.py` accepts optional decision/diff embeddings) and evaluated before being wired into the live gate. A dry-run found true-positive and false-positive similarity scores (0.29 vs. 0.65) don't separate cleanly — shared surface vocabulary between unrelated decisions and diffs produces false-positive similarity as high as genuine matches. It was deliberately not shipped to the live path rather than shipping a detector that doesn't reliably discriminate. An LLM-based intent check (not raw embedding similarity) is the next candidate, not yet built or evaluated.

Session-Shape baselining (anomaly detection on session-level behavioral metrics: edit velocity, revert rate, file churn) is implemented and tested, but deliberately observational only — no anomaly currently escalates to a review trigger or gate action. Wiring that connection is open, pending real base-rate data to set thresholds that won't produce noise-level false-positive rates in practice.

## Current State
This is an early-stage, actively developed open-source project, not a completed research product. The primitives above are implemented and tested; the benchmark suite and cross-runtime adapter are proposed work this grant would fund.
