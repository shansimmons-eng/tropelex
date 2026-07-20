# Task Context: Phase 6 — Sustainability & Implicit Signals

Session ID: 2026-07-18-phase6-sustainability
Created: 2026-07-18T00:00:00Z
Status: in_progress

## Current Request
Implement Phase 6 of the Tropelex wishlist: 4 features that address memory growth, pre-write guardrails, implicit friction capture, and predictive context assembly. All code must follow updated error handling standards (Result type, domain exceptions, no silent failures).

## Context Files (Standards to Follow)
- /home/retroporter/.config/opencode/context/core/standards/code-quality.md (MANDATORY — updated with robust error handling requirements)
- /home/retroporter/.config/opencode/context/core/standards/test-coverage.md

## Reference Files (Source Material to Look At)
- core/ghost/pattern_matcher.py — Ghost detection logic to reuse for preventive checks
- core/ghost/detector.py — Ghost detection orchestration
- core/ghost/router.py — Existing ghost decisions API
- core/handoff/packet_builder.py — Token-budget trimming (generalizes to prefetch assembler)
- core/impact/analysis.py — Impact scoring (reused in prefetch relevance)
- core/agent_skills.py — AgentSkillGraph + PromptGenealogy (tuning + genealogy pattern)
- core/context-compressor/compressor.py — Compression strategies (used by prefetch tuner)
- core/knowledge_decay.py — Confidence scoring (used in prefetch relevance)
- core/rag.py — Embeddings for semantic similarity (used in prefetch relevance)
- core/decision_tree.py — Supersession chains (used in compaction)
- core/memory/manager.py — Memory storage (compaction writes here)
- core/health/dashboard.py — Health dashboard (friction feeds into this)
- core/tropebook/web/server.py — Router mounting point
- core/standards/code-quality.md — Error handling checklist

## External Docs Fetched
(none — all dependencies are internal)

## Components

### 1. Preventive Ghost Decision Checks (Pre-Write Hook)
**Files:** core/ghost/preventive.py, core/ghost/preventive_router.py
**Reuse:** pattern_matcher.py (score_diff, jaccard keywords), detector.py (load active decisions)
**API:** POST /api/memory/{project}/ghost-check — body: {diff: str} → warnings before write
**Error handling:** Result type; ValidationError for bad diffs, MemoryError for missing project
**Key:** Same detection logic, different trigger point. Run as pre-edit hook, surface warning before write.

### 2. Memory Compaction / Epoch Summarization
**Files:** core/compaction/compactor.py, core/compaction/epoch.py, core/compaction/router.py
**Reuse:** decision_tree.py (supersession chains), knowledge_decay.py (confidence tiers), memory/manager.py (read/write)
**API:** POST /api/memory/{project}/compact — triggers compaction pass; GET status
**Error handling:** Result type; CompactionError for failures, archive originals never delete
**Key:** LLM-driven merge of superseded chains → epoch summaries. Archive originals for time-travel.

### 3. Friction Mining (Implicit Signal Capture)
**Files:** core/friction/miner.py, core/friction/router.py
**Reuse:** health/dashboard.py (friction scores feed into health)
**API:** POST /api/memory/{project}/friction/scan — body: {session_transcript: str} → friction signals
**Error handling:** Result type; ValidationError for bad input
**Key:** Transcript pattern detection (rephrasing, retries, rapid edits) → implicit low-confidence zones. No explicit recording needed.

### 4. Predictive Context Prefetch / Budget-Aware Assembler
**Files:** core/prefetch/relevance.py, core/prefetch/assembler.py, core/prefetch/tuner.py, core/prefetch/genealogy.py, core/prefetch/router.py
**Reuse:** impact/analysis.py (impact scores), agent_skills.py (proficiency), knowledge_decay.py (confidence), packet_builder.py (_trim_to_budget, _decision_matches_category), embeddings.py (semantic similarity), context-compressor/compressor.py (compression levels)
**API:** POST /api/memory/{project}/prefetch — {task, token_budget} → bundle + near_misses + bundle_id; POST /api/memory/{project}/prefetch/{bundle_id}/outcome
**Error handling:** Result type; PrefetchError, ValidationError
**Key:** Relevance = w_impact * impact + w_category * category_match + w_confidence * decay + w_semantic * cosine_sim. Knapsack assembler with near-miss transparency. Genealogy feedback loop (precision + recall proxy). Skill-aware tuning (widen for novice, tighten for expert).

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
- [ ] All 4 features implemented with REST API endpoints
- [ ] All routers mounted in server.py
- [ ] All error handling follows updated code-quality.md (Result type, domain exceptions, no silent failures)
- [ ] Tests pass for all new code (>90% business logic, >100% public APIs)
- [ ] Existing 664 tests still pass
- [ ] UI updated with navigation entries for new features
- [ ] Wishlist.md updated with implementation status
