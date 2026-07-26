# FAR AI Research Grant Proposal: Tropelex

## Project Title
Tropelex: Decision Protocols and Calibration Tracking for Cooperative Multi-Agent Alignment

## Abstract
Cooperative multi-agent systems need verifiable mechanisms for rationale transfer, confidence signaling, and conflict resolution across independent agent boundaries. Tropelex implements a multi-agent coordination layer — structured Agent Handoff Packets, a decision-confidence calibration mechanism, and opt-in federated benchmarking — aimed at reducing informational decay and misaligned signaling when autonomous agents delegate subtasks or share system state.

## Technical Alignment Problems Addressed
- **Context Loss Across Agent Boundaries:** In multi-agent pipelines, sub-agents often receive task outputs without the underlying rationale, leading to compound errors and uncoordinated behavior.
- **Uncalibrated Agent Signaling:** Autonomous agents lack native incentives to report honest uncertainty, leading to overconfident execution of ambiguous instructions.

## Architecture & Protocol Primitives
- **Context & Rationale Transfer (`Agent Handoff Packets`):** Role-aware context bundles carrying decision history, rationale, and active constraints across agent handoffs.
- **Honest Signaling & Calibration (`Decision Market`):** A confidence-tracking mechanism where agents record bets on proposed execution paths, building a calibration leaderboard over time.
- **Decentralized Multi-Agent Evaluation (`Federated Benchmarking`):** An opt-in, privacy-preserving mechanism for cross-install comparison of decision-graph statistics without exposing local codebase contents.

See [SAFETY.md](../SAFETY.md) for the full mapping of these features to alignment terminology, and the project [README](../README.md) for the complete feature set.

## Deliverables & Milestones
1. **Multi-Agent Coordination Benchmark:** Evaluate context retention and goal alignment across chained sub-agent delegations using Tropelex handoff packets versus naive context passing.
2. **Open Protocol Specification:** A documented schema for inter-agent rationale transmission, with the goal of compatibility beyond the current Claude Code / MCP integration (e.g., AutoGen, CrewAI, LangGraph) as proposed future work.
3. **Calibration Study:** An empirical report on whether confidence-tracking reduces multi-agent coordination failures in ambiguous-goal environments, building on the existing Decision Market implementation.

## Current State
The handoff packet, decision market, and federated benchmarking primitives are implemented in the current codebase (1,400+ passing unit tests as of this writing). Cross-framework protocol compatibility and the formal benchmark suite are proposed work this grant would fund — this is an early-stage open-source project, not a finished research artifact.
