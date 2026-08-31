# Survival and Flourishing Fund (SFF) Proposal: Tropelex

## Project Title
Tropelex: Open-Source Deterministic Safety Tooling for Autonomous Agent Control Pipelines

## Executive Summary
The Survival and Flourishing Fund prioritizes working, open-source alignment software built by independent developers with demonstrated execution capacity. Tropelex is an actively developed decision-memory and drift-detection framework aimed at reducing autonomous agent misbehavior. It ships with a terminal user interface (TUI), a Model Context Protocol (MCP) server, and a test suite of 2,674+ passing unit tests as of this writing.

## Shipped Architecture & Verification State
Tropelex is a live, working codebase (`shansimmons-eng/tropelex`):
- **Decision Audit Graph:** Records human decisions and rationale so agent-proposed changes can be checked against stated intent.
- **Prompt Injection & Payload Sanitization (`Context Compressor`):** Normalizes and filters untrusted inputs before context injection, reducing the surface available to injected instructions.
- **Guardrail Decay Management (`Knowledge Decay`):** Degrades confidence scores on stale decisions over time, prompting re-verification of aging policies rather than letting them silently retain full authority.
- **Tamper-Evident Decision History (`Provenance Chain`):** Every decision carries a content hash resynced on each legitimate mutation and logged as its own hash-chained audit event; `verify_integrity` independently cross-checks a decision's current hash against the audit trail's own record, catching direct edits to the underlying store that bypass the API entirely.
- **Instance Access Control (`Shared-Secret Authentication`):** Every mutating API call requires an instance-scoped secret unless the request is a verified same-origin browser call, with a separate Host-header check closing the DNS-rebinding gap CORS alone doesn't cover — closing the "any local process can mutate decision history" gap in what is otherwise a local write surface.
- **Integrations:** MCP server interface for Claude Code, a terminal UI for monitoring, and a pre-write hook for diff-time checks.

See [SAFETY.md](../SAFETY.md) for the full mapping of these features to safety terminology, and the project [README](../README.md) for the complete feature set.

## Applicant Track Record & Prior Art
Tropelex's author has a public prior project, [Sovereign_Mirror](https://github.com/shansimmons-eng/Sovereign_Mirror), described as a distributed governance system with mathematically verified logic gates (hybrid Jotai/Zustand/Redux state architecture). This proposal is submitted by an independent developer, not a funded lab — track record should be evaluated against the shipped code in both repositories.

## Grant Execution Plan
SFF non-dilutive grant funding would support continued independent development focused on:
1. Extending Tropelex integration to additional open-source agent frameworks beyond the current Claude Code / MCP target.
2. Running structured drift and contradiction-detection analysis on real multi-step coding sessions.
3. Maintaining Tropelex as an unencumbered open-source safety primitive.

## Evaluation & Limitations
Safety-relevant logic is real and tested, but currently scattered rather than consolidated: it lives across `core/ghost/`, `core/safety_budget.py`, `core/goals/`, `core/contradictions/`, `core/handoff/`, `core/session_shape/`, `core/driftbench/`, and `core/market/`, plus roughly 150 lines still inline in `core/tropebook/web/server.py`. A `core/safety/` module exists as a named home but today holds one gate, not a consolidation of the rest. For an external auditor trying to review "the safety surface" as a bounded unit, this is a genuine reviewability gap, not a documentation gap — it's a code-organization limitation, acknowledged directly rather than glossed over. Consolidating it into one auditable module is exactly the kind of packaging work reviewer-facing grant funding is well-suited to, distinct from new safety mechanisms.

Track record risk is real: this is a single independent developer, not a funded lab or team, and no external code review has occurred to date. The mitigating evidence is process discipline visible in the repository itself — a test suite of 2,674+ passing tests, and a demonstrated pattern of catching and correcting the project's own overclaims before they were flagged externally (e.g., renaming a feature away from "Federated Benchmarking" once the name was found to imply networking that never existed, and declining to ship an embedding-similarity drift detector after evaluation showed it didn't discriminate reliably — see `docs/cais-summary.md`'s Evaluation & Limitations section). That's evidence of a working self-correction habit, not evidence against the underlying bus-factor risk, which remains real.

## Current State
This is an early-stage, actively developed open-source project maintained by a single independent developer. Claims above are limited to what is verifiable in the current codebase and public repositories; roadmap items are proposed future work, not completed deliverables.
