# Task Context: Phase 7 — Validation & Cost Intelligence

Session ID: 2026-07-18-phase7-validation
Created: 2026-07-18T00:00:00Z
Status: in_progress

## Current Request
Implement Phase 7 of the Tropelex wishlist: 2 features that validate decision rationale against the live web and track actual cost per decision.

## Context Files (Standards to Follow)
- /home/retroporter/.config/opencode/context/core/standards/code-quality.md (MANDATORY — updated with robust error handling requirements)
- /home/retroporter/.config/opencode/context/core/standards/test-coverage.md

## Reference Files (Source Material to Look At)
- core/knowledge_decay.py — Confidence scoring (reused for rationale validation baseline)
- core/tropebook/research.py — BraveSearch, web research (used for corroboration lookups)
- core/impact/analysis.py — Impact scoring pattern (reference for cost rollup design)
- core/rag.py — Keyword matching, cross-project learning
- core/decision_tree.py — Decision relationships (ancestors/descendants for cost tracing)
- core/memory/manager.py — Memory storage (cost ledger writes here)
- core/agent_skills.py — PromptGenealogy pattern (genealogy feedback loop pattern to mirror)
- core/tropebook/web/server.py — Router mounting point
- core/standards/code-quality.md — Error handling checklist

## External Docs Fetched
(none — all dependencies are internal)

## Components

### 1. Rationale Corroboration via Tropebook
**Files:** core/corroboration/corroborator.py, core/corroboration/router.py
**Reuse:** tropebook/research.py (BraveSearch for web lookups), knowledge_decay.py (confidence scoring), rag.py (keyword matching)
**API:** POST /api/memory/{project}/corroborate — {decision_id} → CorroborationReport
**Error handling:** Result type; CorroborationError, MemoryError, ValidationError
**Key:** Periodically take a decision's rationale and run it through research infrastructure to check if stated justification is still current. Flag stale rationale with evidence. Confidence adjustment based on corroboration.
**Output:** CorroborationReport with: decision_id, rationale, research_findings[], status (supported|outdated|contradicted|unverifiable), confidence_adjustment, evidence_urls[]

### 2. Cost Ledger (Decision Impact ROI)
**Files:** core/cost/ledger.py, core/cost/tracker.py, core/cost/router.py
**Reuse:** impact/analysis.py (impact scoring for cost attribution), decision_tree.py (ancestors/descendants for cost tracing), knowledge_decay.py (confidence for weighting)
**API:** POST /api/memory/{project}/cost/record — record cost event; GET /api/memory/{project}/cost/report — full cost report; GET /api/memory/{project}/cost/decision/{decision_id} — per-decision cost
**Error handling:** Result type; CostError, MemoryError, ValidationError
**Key:** Track actual dollars/tokens spent per decision. Record cost events (agent time, rework, API calls). Roll up into per-decision cost reports. ROI scoring with real denominators. Cost trend analysis.
**Output:** CostReport with: total_cost, cost_per_decision[], rework_costs, roi_scores, trend_data

## Constraints
- All code follows code-quality.md: pure functions, <50 lines, composition, dependency injection
- Result type for business logic, domain exceptions at IO boundaries
- No silent failures, no bare except, every error path tested
- Pydantic validation at every API boundary
- Each feature in its own directory under core/
- Routers mounted in server.py
- Tests follow test-coverage.md: AAA pattern, >90% on business logic, >100% on public APIs
- Reuse existing functions — don't reimplement what's already battle-tested
- Linux only, Python 3.12+, no Windows paths

## Exit Criteria
- [ ] All 2 features implemented with REST API endpoints
- [ ] All routers mounted in server.py
- [ ] All error handling follows updated code-quality.md (Result type, domain exceptions, no silent failures)
- [ ] Tests pass for all new code (>90% business logic, >100% public APIs)
- [ ] Existing 890 tests still pass
- [ ] UI updated with navigation entries for new features
- [ ] Wishlist.md updated with implementation status
