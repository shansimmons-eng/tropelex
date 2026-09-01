# FAR AI Research Grant Proposal: Tropelex

## Project Title
Tropelex: Decision Protocols and Calibration Tracking for Cooperative Multi-Agent Alignment

## Abstract
Cooperative multi-agent systems need verifiable mechanisms for rationale transfer, confidence signaling, and conflict resolution across independent agent boundaries. Tropelex implements a multi-agent coordination layer — structured Agent Handoff Packets, a decision-confidence calibration mechanism with cross-agent coordination-drift detection, and opt-in cross-install benchmark comparison — aimed at reducing informational decay and misaligned signaling when autonomous agents delegate subtasks or share system state.

## Technical Alignment Problems Addressed
- **Context Loss Across Agent Boundaries:** In multi-agent pipelines, sub-agents often receive task outputs without the underlying rationale, leading to compound errors and uncoordinated behavior.
- **Uncalibrated Agent Signaling:** Autonomous agents lack native incentives to report honest uncertainty, leading to overconfident execution of ambiguous instructions.

## Architecture & Protocol Primitives
- **Context & Rationale Transfer (`Agent Handoff Packets`):** Role-aware context bundles carrying decision history, rationale, and active constraints across agent handoffs.
- **Honest Signaling & Calibration (`Decision Market`):** A confidence-tracking mechanism where agents record bets on proposed execution paths, building a calibration leaderboard over time.
- **Coordination Drift Detection (`core/market/coordination.py`):** Detects declining agreement between multiple agents' calibration profiles over time — a distinct signal from any single agent's individual accuracy, surfacing when cooperating agents are diverging from each other even when no individual agent looks miscalibrated on its own.
- **Cross-Install Comparison (`Benchmarks`):** Opt-in comparison of decision-graph structural statistics (not decision text) across installs via a portable JSON export/import bundle handed between machines as a plain file — no networking, despite the feature's earlier "Federated Benchmarking" name implying otherwise; renamed once that mismatch was noticed.

See [SAFETY.md](../SAFETY.md) for the full mapping of these features to alignment terminology, and the project [README](../README.md) for the complete feature set.

## Deliverables & Milestones
1. **Multi-Agent Coordination Benchmark:** Evaluate context retention and goal alignment across chained sub-agent delegations using Tropelex handoff packets versus naive context passing.
2. **Open Protocol Specification:** ✅ Published 2026-08-31 — [`docs/protocols/handoff-packet-spec.md`](protocols/handoff-packet-spec.md) documents the packet wire format, must-survive protection, completeness verification, and the packet-hashing scheme (empirically verified against a real running instance, not just read off the source) independent of the Python implementation. **A first cross-framework spike shipped 2026-09-01**: [`core/handoff/adapters/langgraph_adapter.py`](../core/handoff/adapters/langgraph_adapter.py) is a real LangGraph node (`StateGraph` → `compile()` → `ainvoke()`) that calls Tropelex's own `generate_handoff` in-process and carries the resulting packet — including `must_survive_decision_ids` and `packet_hash` — through LangGraph's own state-passing execution model. Live-verified, not just written: `python3 scripts/adapters/langgraph_handoff_demo.py` runs it end to end. Deliberately narrow, per this deliverable's own scope: one framework (LangGraph), one direction (producer only — Tropelex generates a packet that LangGraph's state carries; nothing here validates Tropelex *consuming* a LangGraph-native object), and no AutoGen or CrewAI coverage at all. General cross-framework compatibility, a consumer-direction spike, and AutoGen/CrewAI specifically remain proposed future work — this is one concrete, checkable data point in that direction, not a claim the broader question is answered.
3. **Calibration Study:** An empirical report on whether confidence-tracking reduces multi-agent coordination failures in ambiguous-goal environments, building on the existing Decision Market implementation.

## Evaluation & Limitations
Coordination Drift Detection has no dedicated benchmark yet: it's implemented and unit-tested against synthetic calibration sequences, but there's no quantitative study of detection accuracy across realistic multi-agent divergence scenarios, and no measured false-positive rate under normal (non-diverging) multi-agent variation. That study is exactly what deliverable #1 above would fund — it doesn't exist today.

The mechanism enforcing gate behavior (documented in `SAFETY.md`'s "Configurable Gate-Severity Policy" section) started as a flat severity-tier-to-action mapping and has since (2026-08-31) gained an ordered rule layer (`gate_rules`) that can condition the resolved action on severity, the checking agent's identity, or the violated decision's category. Still deliberately narrow: rule conditions are three literal-equality checks, ANDed, with no boolean operators and no expression evaluator — auditable specifically because a rule list stays fully readable top to bottom, not because it's unable to express more. Genuinely richer inter-agent contracts (arbitrary conditions, cross-signal composition, coordination-drift-state as a condition) remain open design work, not a small extension of what exists now.

Cross-framework protocol compatibility is mostly still unproven in practice. The handoff packet schema (`core/handoff/packet_builder.py`) was exercised only against Claude Code / MCP clients until 2026-09-01, when a first spike (see Deliverable #2 above) ran it for real inside LangGraph's own execution model — one framework, one direction (producer), not the general claim. AutoGen and CrewAI remain completely untested against their actual multi-agent runtimes, and nothing validates Tropelex *consuming* a LangGraph-native object either. The bulk of Deliverable #2 is still proposed work, not a retrofit of something already validated elsewhere — this spike narrows the gap by one concrete data point, it doesn't close it.

## Current State
The handoff packet, decision market, coordination-drift, and cross-install benchmark primitives are implemented in the current codebase (2,674+ passing unit tests as of this writing). Cross-framework protocol compatibility and the formal benchmark suite are proposed work this grant would fund — this is an early-stage open-source project, not a finished research artifact.
