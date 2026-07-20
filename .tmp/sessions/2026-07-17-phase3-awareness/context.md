# Task Context: Phase 3 — Awareness Features

Session ID: 2026-07-17-phase3-awareness
Created: 2026-07-17T00:00:00+00:00
Status: in_progress

## Current Request
Add three new awareness features to Tropelex:
1. Ghost Decisions — Silent Drift Detection
2. Explainable Memory — "Why do we...?" Chat
3. Agent Handoff Packets

## Context Files (Standards to Follow)
- /home/retroporter/.config/opencode/context/core/standards/code-quality.md
- /home/retroporter/.config/opencode/context/core/standards/test-coverage.md

## Reference Files (Source Material to Look At)
- /home/retroporter/Tropelex/core/git_integration.py
- /home/retroporter/Tropelex/core/decision_tree.py
- /home/retroporter/Tropelex/core/rag.py
- /home/retroporter/Tropelex/core/impact/analysis.py
- /home/retroporter/Tropelex/core/health/dashboard.py
- /home/retroporter/Tropelex/core/health/router.py
- /home/retroporter/Tropelex/core/knowledge_decay.py
- /home/retroporter/Tropelex/core/agent_skills.py
- /home/retroporter/Tropelex/core/tropebook/web/server.py
- /home/retroporter/Tropelex/UI/animated_tropebook_dashboard/code.html

## External Docs Fetched
None required — all built on existing internal primitives.

## Components

### 1. Ghost Decisions — Silent Drift Detection
Detect when code quietly contradicts recorded decisions without anyone saying so.
- Pattern matcher comparing decision text against git diffs
- Diff hunk analysis (e.g., "snake_case" vs camelCase)
- Confidence scoring based on diff severity and decision confidence
- API endpoint: GET /api/memory/{project}/ghost-decisions
- Integration with Health Dashboard

### 2. Explainable Memory — "Why do we...?" Chat
Conversational front-end that fuses RAG + decision tree + impact analysis into causal answers.
- Natural language "why" questions answered with full causal chain
- Decision provenance (who, when, confidence)
- Supersession chain (what replaced this, if anything)
- Downstream impact (what this decision caused)
- Source citations (git commits, session history)
- API endpoint: POST /api/memory/{project}/explain

### 3. Agent Handoff Packets
Generate role-aware context bundles when one agent hands off to another.
- Role-specific context slicing (different agents get different memory slices)
- Formatted for target agent type (e.g., TestEngineer gets test-relevant decisions + coverage gaps)
- Token-budget-aware (fits within target agent's context window)
- Includes recent session state and active decisions
- API endpoint: POST /api/memory/{project}/handoff

## Constraints
- Linux-native project — no Windows paths or commands
- All code follows code-quality.md: pure functions, <50 lines, composition, dependency injection
- All tests follow test-coverage.md: AAA pattern, >90% on business logic, >100% on public APIs
- No external package dependencies — build on existing primitives
- Routers must be mounted in server.py

## Exit Criteria
- [ ] Ghost Decisions detects silent drift between decisions and code
- [ ] Explainable Memory answers "why" questions with causal chain
- [ ] Agent Handoff generates role-specific context packets
- [ ] All features have REST API endpoints
- [ ] All features have >90% test coverage on business logic
- [ ] All tests pass (582 existing + new)
- [ ] UI dashboard wired to new endpoints
