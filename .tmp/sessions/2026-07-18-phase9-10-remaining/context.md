# Task Context: Phases 9-10 — All Remaining Features

Session ID: 2026-07-18-phase9-10-remaining
Created: 2026-07-18T00:00:00Z
Status: in_progress

## Current Request
Implement all 7 remaining wishlist features across Phases 9-10.

## Context Files (Standards to Follow)
- /home/retroporter/.config/opencode/context/core/standards/code-quality.md (MANDATORY)
- /home/retroporter/.config/opencode/context/core/standards/test-coverage.md

## Reference Files (Source Material)
- core/knowledge_decay.py — Confidence scoring
- core/decision_tree.py — Decision relationships, traversal
- core/impact/analysis.py — Impact scoring, reversals
- core/agent_skills.py — AgentSkillGraph, PromptGenealogy
- core/rag.py — Cross-project learning, keyword matching
- core/memory/manager.py — Memory storage (with file locking)
- core/session_replay.py — Session snapshots, rollback
- core/health/dashboard.py — Health dashboard integration
- core/handoff/packet_builder.py — Handoff packets (for Digital Twin integration)
- core/tropebook/research.py — Web research (for Federated Benchmarking)
- core/tropebook/web/server.py — Router mounting point

## Components

### Phase 9: Tier 2 Features

#### 1. Decision Market / Calibration Score (#14)
**Files:** core/market/bettor.py, core/market/calibration.py, core/market/router.py
**Purpose:** Team members place confidence bets on decisions; track calibration over time.
**API:** POST /api/memory/{project}/market/bet, GET /api/memory/{project}/market/calibration, GET /api/memory/{project}/market/leaderboard
**Key:** Track bet accuracy against outcomes (reversal rate), per-person calibration scores, category-specific accuracy, leaderboards.

#### 2. Memory Lens — IDE Inline Annotations (#15)
**Files:** core/lens/annotator.py, core/lens/router.py
**Purpose:** Decision annotations for code editors — hover context, provenance, drift detection.
**API:** POST /api/memory/{project}/lens/annotate — {file_path, line_number} → annotations; GET /api/memory/{project}/lens/scan/{file_path} → all annotations for a file
**Key:** Maps code patterns to decisions, returns inline annotation data. VS Code extension can consume this API.

#### 3. Bidirectional Slack Decision Capture (#17)
**Files:** core/slack/capture.py, core/slack/extractor.py, core/slack/router.py
**Purpose:** Capture decisions from Slack-style chat messages, extract implicit decisions.
**API:** POST /api/memory/{project}/slack/capture — capture a decision from chat; POST /api/memory/{project}/slack/extract — extract decisions from a thread
**Key:** `/tropelex decide "..."` captures inline, automatic extraction from chat threads, conflict detection on capture.

### Phase 10: Tier 3 Features

#### 4. Memory Time-Travel Debugger (#23)
**Files:** core/timetravel/snapshot.py, core/timetravel/router.py
**Purpose:** Check out project memory as of any past date.
**API:** GET /api/memory/{project}/timetravel/{date} → memory as of date; POST /api/memory/{project}/timetravel/diff — diff between two dates
**Key:** Uses session_replay snapshots, reconstructs memory state at any point in time.

#### 5. Contradiction Detection (Active) (#24)
**Files:** core/contradictions/detector.py, core/contradictions/router.py
**Purpose:** Scan for unresolved contradictions between active decisions.
**API:** GET /api/memory/{project}/contradictions → list of contradictions
**Key:** Semantic similarity matching (keyword overlap), classification (direct, implicit, temporal), integration with Health Dashboard.

#### 6. "Digital Twin" Contributor Personas (#25)
**Files:** core/personas/persona_builder.py, core/personas/router.py
**Purpose:** Synthesize readable persona summaries from agent proficiency tracking.
**API:** GET /api/memory/{project}/personas/{agent} → persona summary; GET /api/memory/{project}/personas → all personas
**Key:** Uses agent_skills.py data, generates strength/weakness summaries, integrates with handoff packets.

#### 7. Federated Anonymized Benchmarking (#26)
**Files:** core/federation/anonymizer.py, core/federation/aggregator.py, core/federation/router.py
**Purpose:** Opt-in, privacy-preserving sharing of structural statistics across installs.
**API:** POST /api/memory/{project}/federation/share — share anonymized stats; GET /api/federation/benchmarks — aggregate benchmarks
**Key:** Structural-only sharing (no decision text), aggregate pattern statistics, opt-in/opt-out.

## Constraints
- All code follows code-quality.md: pure functions, <50 lines, composition
- Result type for business logic, domain exceptions at IO boundaries
- No silent failures, every error path tested
- Pydantic validation at every API boundary
- Each feature in its own directory under core/
- Tests follow test-coverage.md
- Linux only, Python 3.12+

## Exit Criteria
- [ ] All 7 features implemented with REST API endpoints
- [ ] All routers mounted in server.py
- [ ] Tests pass for all new code
- [ ] Existing 1112 tests still pass
- [ ] UI updated with navigation entries
- [ ] Wishlist.md updated
