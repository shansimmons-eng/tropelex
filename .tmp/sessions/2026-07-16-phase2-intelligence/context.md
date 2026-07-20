# Task Context: Phase 2 Intelligence Features

Session ID: 2026-07-16-phase2-intelligence
Created: 2026-07-16T15:00:00Z
Status: in_progress

## Current Request
Implement 4 Phase 2 intelligence features from wishlist.md:
1. Memory Health Dashboard
2. Cross-Project Learning Automation
3. Research Feed Intelligence
4. Decision Impact Analysis

## Context Files (Standards to Follow)
- /home/retroporter/.config/opencode/context/core/standards/code-quality.md
- /home/retroporter/.config/opencode/context/core/standards/test-coverage.md

## Reference Files (Source Material)
- core/knowledge_decay.py — decay_score, score_decisions, get_stale_decisions, get_confidence_summary
- core/decision_tree.py — DecisionTree with supersedes/caused_by/related relationships
- core/rag.py — MemoryRAG.retrieve, CrossPollinator.find_transferable_knowledge
- core/tropebook/research_feeds.py — ResearchFeedManager with feed CRUD and run tracking
- core/git_integration.py — sync_repo_to_memory, get_deep_repo_summary
- core/tropebook/web/server.py — existing API patterns

## Components

### 1. Memory Health Dashboard
- Service: core/health/dashboard.py — aggregate health metrics
- Endpoint: GET /api/memory/{project}/health
- Metrics: stale decisions, coverage gaps, growth trends, quality score
- Tests: tests/test_health_dashboard.py

### 2. Cross-Project Learning Automation
- Service: core/rag.py extensions — auto-detect similar projects, periodic suggestions
- Endpoint: GET /api/memory/{project}/auto-suggestions
- Tests: tests/test_auto_cross_pollinate.py

### 3. Research Feed Intelligence
- Service: core/tropebook/feed_intelligence.py — trend detection, anomaly flagging
- Endpoint: GET /api/research-feeds/{feed_id}/intelligence
- Tests: tests/test_feed_intelligence.py

### 4. Decision Impact Analysis
- Service: core/impact/analysis.py — link decisions to commits, reversal tracking
- Endpoint: GET /api/memory/{project}/impact
- Tests: tests/test_decision_impact.py

## Constraints
- Linux-only, no Windows paths
- Follow code-quality.md: pure functions, <50 lines, composition
- Must pass all 495 existing tests
- Each new module must have >90% test coverage

## Exit Criteria
- [ ] Memory Health Dashboard endpoint + service + tests
- [ ] Cross-Project Learning Automation endpoint + service + tests
- [ ] Research Feed Intelligence endpoint + service + tests
- [ ] Decision Impact Analysis endpoint + service + tests
- [ ] All 495+ tests still pass
- [ ] All new routers mounted in server.py
