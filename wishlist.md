# Tropelex Wishlist

**Novel features and improvements planned for future development.**

Grouped by function (what the feature is *for*), not by build priority or chronology — mirrors the dashboard sidebar's category structure. See `## Implementation Roadmap` below for the phase-by-phase build history.

---

## Content

### 3. Knowledge Graph Visualization
**Purpose:** Interactive graph showing decisions, relationships, and confidence.

**Why:** Decision trees are linear. A full graph shows how knowledge connects.

**Features:**
- Force-directed graph layout
- Node sizing by confidence/age
- Edge coloring by relationship type
- Click-to-drill into decision details
- Filter by date range, confidence tier, category

**Status:** ✅ Implemented (core/graph_router.py)

---

## Quality & Integrity

### 2. Memory Health Dashboard
**Purpose:** Monitor memory quality, freshness, and coverage.

**Why:** Decisions decay, patterns become stale. Users need visibility into memory health.

**Features:**
- Stale decision alerts
- Coverage metrics (what categories are missing)
- Growth trends over time
- Quality scores per project
- Recommendations for memory maintenance

**Status:** ✅ Implemented (core/health/)

---

### 5. Decision Impact Analysis
**Purpose:** Track how decisions affected subsequent work.

**Why:** We record decisions but don't measure their outcomes.

**Features:**
- Link decisions to subsequent commits/tasks
- Track decision reversal rates
- Measure time-to-value for decisions
- Identify high-impact vs low-impact decisions
- ROI scoring for architectural choices

**Status:** ✅ Implemented (core/impact/)

---

### 6. Ghost Decisions — Silent Drift Detection
**Purpose:** Detect when code quietly contradicts recorded decisions without anyone saying so.

**Why:** The #1 real failure mode in every team's architecture docs — docs say X, code does Y, nobody notices for months. Tropelex records decisions and detects when a new decision supersedes an old one, but has no idea when code silently drifts from documented decisions.

**Features:**
- Diff incoming commits against the decision corpus
- Pattern-match decision text against diff hunks (e.g., "snake_case" vs camelCase in code)
- Flag silent decision drift as "ghost decisions" — contradictions nobody documented
- Surface drift in Health Dashboard alongside stale decisions
- Confidence scoring based on diff severity and decision confidence

**Status:** ✅ Implemented (core/ghost/)

---

### 20. Knowledge Decay Prevention
**Purpose:** Auto-refresh stale decisions.

**Why:** Decisions decay naturally. Proactive refresh would maintain relevance.

**Features:**
- Periodic validation prompts
- Cross-reference with current codebase
- Auto-suggest decision reviews
- Decay rate tuning per category
- Preservation rules for critical decisions

**Status:** ✅ Implemented (core/knowledge_decay.py)

---

### 21. Memory Analytics
**Purpose:** Usage patterns, growth trends, quality metrics.

**Why:** Analytics would reveal how memory is used and where it's most valuable.

**Features:**
- Usage frequency per component
- Growth rate tracking
- Quality metrics over time
- ROI analysis per feature
- Capacity planning recommendations

**Status:** ✅ Implemented (core/analytics.py, analytics_router.py)

---

### 22. Decision Confidence Alerts
**Purpose:** Notify when decisions become stale or contradictory.

**Why:** Users don't proactively check confidence scores.

**Features:**
- Email/Slack notifications for low-confidence decisions
- Daily/weekly confidence digest
- Contradiction detection alerts
- Stale decision warnings
- Priority-based alerting (critical decisions first)

**Status:** ✅ Partially implemented (alert_service.py)

---

### 24. Contradiction Detection (Active)
**Purpose:** Actively scan for unresolved contradictions that were never formally reconciled.

**Why:** Decision Tree tracks supersedes/reverts, but doesn't detect live contradictions (e.g., "use REST" and "use GraphQL" both still active with no supersede link).

**Features:**
- Semantic similarity matching between decisions
- Contradiction classification (direct, implicit, temporal)
- Open question surfacing
- Resolution suggestions
- Integration with Health Dashboard

**Status:** ✅ Implemented

---

### 28. Friction Mining (Implicit Signal Capture)
**Purpose:** Auto-detect friction from session transcripts without anyone explicitly logging decisions.

**Why:** Everything currently depends on explicit recording. Real friction — agent getting corrected, human retyping with growing annoyance, repeated reverts — never gets captured. This is the data source current tools (Continue, Cursor, mem0, Zep) don't touch.

**Features:**
- Transcript pattern detection (rephrasing, "no that's wrong", rapid edits)
- Retry loop identification
- Implicit low-confidence zone flagging
- Tech-debt heatmap generation
- Session-level friction scoring
- Integration with Health Dashboard

**Status:** ✅ Implemented (core/friction/)

---

### 29. Preventive Ghost Decision Checks (Pre-Write Hook)
**Purpose:** Run ghost decision detection before an agent finalizes a diff, not after commit.

**Why:** Ghost Decisions (#6) catches drift after a commit lands. By then the agent already wrote the contradicting code. Prevention > detection.

**Features:**
- Pre-edit hook that checks diff against high-confidence active decisions
- Warning surfacing before write finalization
- Configurable severity thresholds
- Skip list for known-safe patterns
- Integration with existing ghost detection logic
- CLI and API surface

**Status:** ✅ Implemented (core/ghost/preventive.py, core/ghost/preventive_router.py)

---

### 30. Rationale Corroboration via Tropebook
**Purpose:** Fact-check decision rationale against the live web using existing research infrastructure.

**Why:** Decisions get recorded with rationale ("chose Postgres for JSON support") but nothing checks whether that rationale still holds. Knowledge Decay handles age, not validity.

**Features:**
- Periodic rationale validation via research feeds
- Cross-reference with Tropebook citations
- Stale rationale flagging with evidence
- Auto-suggest decision review when rationale outdated
- Confidence adjustment based on corroboration
- Integration with Knowledge Decay scoring

**Status:** ❌ Removed (2026-07-28). Web-search-based keyword matching was a poor fit for most real decisions: anything self-referential to the project's own architecture/tests has no public source to corroborate against, so results were consistently irrelevant regardless of query-quality fixes (narration-verb stripping, rationale-only queries, etc. — see git history on `core/corroboration/` before removal). Removed rather than kept as a feature that mostly produced noise.

---

## Explainability & Discovery

### 7. Explainable Memory — "Why do we...?" Chat
**Purpose:** Conversational front-end that fuses RAG + decision tree + impact analysis into causal answers.

**Why:** "Why do we use Postgres instead of MySQL?" should trace the decision, who made it, confidence/tier, what superseded it, and what it caused downstream. This is qualitatively different from search — it's architecture archaeology as a conversation.

**Features:**
- Natural language "why" questions answered with full causal chain
- Decision provenance (who, when, confidence)
- Supersession chain (what replaced this, if anything)
- Downstream impact (what this decision caused)
- Source citations (git commits, session history)

**Status:** ✅ Implemented (core/explain/)

---

### 13. Memory Search API
**Purpose:** Natural language search across all memory.

**Why:** Current search is basic text matching. Semantic search would be more useful.

**Features:**
- Natural language queries ("what did we decide about auth?")
- Context-aware search (project-specific)
- Ranked results by relevance and recency
- Faceted filtering (by date, category, confidence)
- Search suggestions and auto-complete

**Status:** ✅ Implemented (core/search_router.py)

---

### 15. Memory Lens — IDE Inline Annotations
**Purpose:** Ambient decision annotations in code editors, like GitLens but for decisions.

**Why:** Most people never open a dashboard, but everyone reads code. Highest "daily-use stickiness" upgrade.

**Features:**
- Hover annotations on functions/patterns
- Decision provenance inline (who decided, when, confidence)
- Reference count ("referenced 6 times since")
- Diff annotations showing decision drift
- VS Code extension integration

**Status:** ✅ Implemented

---

### 16. Predictive Context Prefetch / Budget-Aware Assembler
**Purpose:** Predict ideal minimal context bundle for a task before the agent starts, sized to a token budget.

**Why:** Context compression is reactive. Proactive prediction prioritizes by impact score rather than recency.

**Features:**
- Task-aware context prediction
- Token budget constraints
- Impact-score prioritization
- Agent-specific tuning (based on prompt genealogy)
- Compression ratio tracking

**Status:** ✅ Implemented (core/prefetch/)

**Implementation detail:** relevance scoring is a composite of impact score, category match, decay confidence, and semantic similarity; assembly uses a budget-aware knapsack (value-density greedy + exact DP pass for boundary optimization); near-misses are surfaced with their scores rather than silently dropped; a genealogy/feedback loop tracks precision (included items referenced) and recall proxy (requested but excluded) to improve weights over time. Reuses `impact/analysis.py`, `agent_skills.py`, and `packet_builder.py` trimming logic.

**API:**
- `POST /api/memory/{project}/prefetch` — task + token_budget → bundle + near_misses + bundle_id
- `POST /api/memory/{project}/prefetch/{bundle_id}/outcome` — referenced_ids + requested_but_missing

---

## Safety & Alignment

### 35. Safety Metadata, Review Workflow & Alignment/Governance Scoring
**Purpose:** Risk classification, review workflow, and multi-dimensional alignment/governance scoring for the decision graph.

**Why:** Decisions were recorded with confidence and rationale but no risk classification, review trail, or compliance framing — needed for evaluating Tropelex as safety-relevant infrastructure (see `SAFETY.md`) rather than just a productivity tool.

**Features:**
- Safety metadata on every decision: risk_level, reversibility, affected_systems, safety_category, requires_review
- Safety Dashboard: risk trends, system exposure, aggregate safety score
- Safety Review Workflow: pending queue, approve/reject, reviewer accountability, mitigation suggestions
- Alignment Evaluation: scoring across interpretability, safety, fairness, robustness, governance
- Governance Compliance: EU AI Act, NIST, ISO 42001 policy checks
- Fairness Audit, Accountability Tracking, Robustness Testing, Interpretability Reports
- Provenance Chain, Integrity Verification, Tamper Detection, immutable Security Audit Log
- Decision Versioning with rollback

**Status:** ✅ Implemented — but as an exception to this codebase's own pattern: every other feature above ships as its own `core/<name>/` module with a router; this one (~3,200 lines) is inline in `core/tropebook/web/server.py`. Candidate for extraction into `core/safety/` + `core/governance/`. Tests: `tests/test_safety_features.py`, `tests/test_alignment_governance.py`, `tests/test_far_cais_sff.py`.

---

### 36. Synthetic Data Policy
**Purpose:** EU AI Act Articles 10 & 50 compliant "nutritional label" for synthetic datasets used in agent training/eval.

**Why:** Decisions can now carry safety metadata, but nothing tracked the provenance and compliance posture of *synthetic data* feeding those decisions.

**Features:**
- Full CRUD for synthetic dataset registration with fidelity, privacy (ε/δ), bias audit, adversarial testing, source data, rationale, distinguishability, model-collapse-prevention, retention, and attestation metadata
- 10 blocking compliance gates run per policy
- UI registration form + compliance dashboard
- Aggregate statistics across all registered policies

**Status:** ✅ Implemented (`core/tropebook/web/server.py` — same inline-implementation caveat as #35). Tests: `tests/test_synthetic_data_policy.py` — note: 17 of these currently fail only when the full `pytest tests/` suite runs together (pass 100% in isolation); see `design.md`'s Security Features section for the known cross-test state-leak issue.

---

### 37. Agent Surface Audit
**Purpose:** Scan the agent's own harness configuration for risk — secrets, over-broad permissions, hook-injection risk, MCP server risk, and injected instructions.

**Why:** Every other feature in this list audits decisions and code — the things an agent *produces*. Nothing audited the agent's own operating environment (`CLAUDE.md`/`AGENTS.md`, `.mcp.json`, `.claude/settings.json`, hooks, agent/skill definitions), even though a leaked key in a committed config file, an unrestricted `Bash(*)` permission, or a hook that pipes remote content into a shell is a safety-relevant risk that never shows up in the decision graph. Inspired by [AgentShield](https://github.com/affaan-m/agentshield)'s five-category shape, reimplemented as pure functions so it plugs into the same severity-ranked finding pattern Contradictions and Doc Mining already use, rather than shelling out to a separate tool.

**Features:**
- Secrets detection: AWS/GitHub/OpenAI/Anthropic/Slack key patterns, private key headers, generic high-entropy assignments
- Permission auditing: `dangerouslySkipPermissions`, unrestricted `Bash(*)`-style wildcard rules
- Hook injection analysis: `curl|sh`/`wget|sh` patterns, unquoted `eval`, unquoted `$ARGUMENTS` interpolation
- MCP server risk profiling: unpinned `@latest` packages, unresolved env placeholder values
- Agent/skill config review: prompt-injection-style markers ("ignore previous instructions", "disable safety", exfiltration language)
- A–F grade computed from severity-weighted findings; read-only, no files modified
- Defaults to auditing Tropelex's own repo; `repo_path` param audits any other repo

**API:** `POST /api/agent-audit/scan?repo_path=...`

**Status:** ✅ Implemented (`core/agent_audit/`). Lives as the 7th tab in the consolidated Safety & Alignment section rather than its own sidebar entry. Tests: `tests/test_agent_audit.py`.

---

## Memory Lifecycle

### 1. Versioned Memory Snapshots
**Purpose:** Automatic versioning of memory state with diff visualization.

**Why:** Currently session replay is manual. Automatic snapshots would create a complete audit trail.

**Features:**
- Auto-snapshot on every memory mutation
- Visual diff between any two snapshots
- Branch/merge support for parallel experiments
- Storage-efficient delta compression

---

### 11. Memory Backup & Restore
**Purpose:** Export/import memory snapshots for portability.

**Why:** Currently memory is local. Backup enables migration and disaster recovery.

**Features:**
- Full memory export as compressed archive
- Selective backup (specific projects or categories)
- Version-stamped restore points
- Conflict resolution on import
- Cloud storage integration (S3, GCS, etc.)

**Status:** ✅ Implemented (core/sync/)

---

### 19. Session Replay with AI Analysis
**Purpose:** AI-generated insights from session diffs.

**Why:** Session diffs are raw data. AI analysis would extract concrete insights.

**Features:**
- Auto-summarize session changes
- Identify decision patterns across sessions
- Suggest process improvements
- Detect regressions or repeated work
- Generate retrospective reports

**Status:** Open — the one feature on this list not yet implemented.

---

### 23. Memory Time-Travel Debugger
**Purpose:** Check out project memory as of any past date; get agent context as if it were that point in time.

**Why:** Forensic tool for postmortems. "What would an agent operating in March have known when it made this call?"

**Features:**
- Snapshot-as-of-any-date retrieval
- Context generation for historical point-in-time
- Diff between two historical snapshots
- Session replay with original context preserved
- Timeline visualization of memory evolution

**Status:** ✅ Implemented

---

### 27. Memory Compaction / Epoch Summarization
**Purpose:** Prevent memory from growing unbounded by collapsing superseded/low-confidence decision chains into higher-level "epoch summaries."

**Why:** Every feature adds more memory. After 18 months with 2,000 decisions, context injection gets truncated arbitrarily or token budgets balloon. This is the difference between memory that grows and memory that matures.

**Features:**
- Periodic LLM-driven compaction pass
- Merge superseded chains into one-line summaries (e.g., "frontend framework churned 3x in 2026, settled on Svelte, see decision #412")
- Archive originals (never delete) for time-travel/audit
- Confidence-tier-based compaction priority
- Token budget tracking per project
- Compaction history with rollback

**Status:** ✅ Implemented (core/compaction/)

---

## Research & Ingestion

### 4. Cross-Project Learning Automation
**Purpose:** Automatically surface solutions from similar projects.

**Why:** Currently cross-pollination is manual. Automation would catch transferable patterns.

**Features:**
- Auto-detect similar projects by tech stack overlap
- Periodic knowledge transfer suggestions
- Solution templates from successful patterns
- Anti-pattern warnings from failures in similar projects

**Status:** ✅ Implemented (core/rag.py extensions)

---

### 9. Research Feed Intelligence
**Purpose:** AI-powered analysis of research feed results.

**Why:** Feeds collect data but don't analyze patterns or significance.

**Features:**
- Trend detection across feed runs
- Anomaly flagging (unusual results)
- Automatic summarization of feed evolution
- Relevance scoring per feed item
- Cross-feed correlation detection

**Status:** ✅ Implemented (core/tropebook/feed_intelligence.py)

---

### 10. Prompt Effectiveness Tracking
**Purpose:** Track which prompts produced best outcomes.

**Why:** Prompt genealogy tracks compression, but not prompt quality itself.

**Features:**
- A/B test prompt variations
- Outcome correlation (which prompts led to success)
- Prompt templates from high-performing examples
- Automatic prompt refinement suggestions
- Context-aware prompt selection

---

### 12. Research Feed Alerts
**Purpose:** Email/Slack notifications for feed updates.

**Why:** Users check feeds manually. Alerts would surface important changes.

**Features:**
- Configurable alert triggers (new results, trend changes)
- Email digest (daily/weekly summary)
- Slack/Discord webhook integration
- Alert rules (only notify for high-relevance items)
- Quiet hours configuration

**Status:** ✅ Implemented (core/tropebook/alert_service.py, alert_router.py)

---

## Team & Collaboration

### 8. Agent Handoff Packets
**Purpose:** Generate role-aware context bundles when one agent hands off to another.

**Why:** Tropelex is used inside multi-subagent systems. When one agent's session ends and hands off to a different specialist, generate a role-aware context packet — "here's what a TestEngineer specifically needs to know" vs "here's what a Frontend specialist needs."

**Features:**
- Role-specific context slicing (different agents get different memory slices)
- Formatted for target agent type (e.g., TestEngineer gets test-relevant decisions + coverage gaps)
- Token-budget-aware (fits within target agent's context window)
- Includes recent session state and active decisions
- API endpoint for programmatic generation

**Status:** ✅ Implemented (core/handoff/)

---

### 14. Decision Market / Calibration Score
**Purpose:** Team members place confidence bets on decisions; track calibration over time.

**Why:** Gamifies retrospective honesty. "Alice's gut calls are 85% accurate; Bob is overconfident on auth decisions." Genuinely novel — not in Continue, Cursor, mem0, or Zep.

**Features:**
- Place confidence bets before decisions are finalized
- Track bet accuracy against outcomes (reversal rate)
- Per-person calibration scores
- Category-specific accuracy (e.g., "85% on auth, 60% on DB")
- Calibration leaderboards

**Status:** ✅ Implemented (core/market/)

---

### 17. Bidirectional Slack Decision Capture
**Purpose:** Capture decisions at the moment they're made in chat, where most undocumented decisions happen.

**Why:** Current Slack integration is one-way (alerts). Bidirectional removes the friction of logging decisions after the fact.

**Features:**
- `/tropelex decide "..."` captures decisions inline
- `/tropelex ask "why did we pick Redis"` queries memory
- Automatic decision extraction from chat threads
- Slack thread context preservation
- Conflict detection on capture

**Status:** ✅ Implemented

---

### 18. Collaborative Memory
**Purpose:** Share memory between multiple agents/projects.

**Why:** Currently memory is isolated. Collaboration would enable team knowledge sharing.

**Features:**
- Multi-agent memory access
- Conflict resolution for concurrent writes
- Permission-based access control
- Change tracking per agent
- Merge strategies for parallel edits

**Status:** ✅ Implemented (core/collaboration/, WebSocket-based)

---

### 25. "Digital Twin" Contributor Personas
**Purpose:** Synthesize readable persona summaries from agent proficiency tracking.

**Why:** "This agent tends to over-engineer auth flows, prefers functional patterns, rarely reverts DB decisions." Auto-generated calibration notes for code reviewers.

**Features:**
- Per-agent personality summaries
- Strength/weakness analysis by category
- Historical accuracy tracking
- Review focus suggestions
- Integration with Agent Handoff Packets

**Status:** ✅ Implemented

---

### 31. PR Bot Delivery Surface
**Purpose:** Deliver ghost decisions, contradictions, and health scores as PR comments where developers actually work.

**Why:** All detection features live in a dashboard nobody opens mid-workflow. Distribution is the actual bottleneck for adoption.

**Features:**
- GitHub/GitLab bot integration
- PR comment generation with relevant decisions
- Diff-aware context injection
- Decision relevance scoring per PR
- Conflict detection on PR content
- Configurable comment templates

**Status:** ✅ Implemented (core/prbot/)

---

### 32. Narrative Mode (Non-Technical Audience)
**Purpose:** Generate readable prose summaries of project history for founders, PMs, and new hires.

**Why:** ADRs and decision timelines are built for engineers. Nothing produces something a non-technical person could read on day one.

**Features:**
- Decision graph to prose conversion
- Git history integration
- "What was tried, what failed, why" narratives
- Multiple audience presets (investor, new hire, PM)
- Timeline visualization
- Export to markdown/PDF

**Status:** ✅ Implemented (core/narrative/)

---

## Integrations & Ops

### 26. Federated Anonymized Benchmarking
**Purpose:** Opt-in, privacy-preserving sharing of structural statistics across Tropelex installs.

**Why:** "Projects using FastAPI+Postgres have a 12% ORM-choice reversal rate." Network effect from aggregate benchmarking.

**Features:**
- Structural-only sharing (no decision text)
- Aggregate pattern statistics
- Benchmark comparison reports
- Opt-in/opt-out per project
- Central aggregation service

**Status:** ✅ Implemented

---

### 33. Cost Ledger (Decision Impact ROI)
**Purpose:** Track actual dollars/tokens spent per decision to give ROI scoring a real denominator.

**Why:** Decision Impact Analysis measures reversal rate and time-to-value, but not actual cost. Token/session tracking exists but isn't rolled up per decision.

**Features:**
- Per-decision token cost tracking
- Rework cost calculation on reversals
- Agent time attribution
- ROI scoring with real denominators
- Cost trend analysis
- Budget alerts per project

**Status:** ✅ Implemented (core/cost/)

---

## Implementation Roadmap

### Phase 1: Foundation (Complete)
- ✅ Memory Manager with versioning
- ✅ Decision Trees with relationships
- ✅ Knowledge Decay scoring
- ✅ Session Replay with rollback
- ✅ Research Feeds with scheduling

### Phase 2: Intelligence (Complete)
- ✅ Memory Health Dashboard
- ✅ Decision Impact Analysis
- ✅ Research Feed Intelligence
- ✅ Cross-Project Learning Automation
- ✅ Memory Analytics
- ✅ Knowledge Graph Visualization
- ✅ Memory Search API
- ✅ Research Feed Alerts
- ✅ Memory Backup & Restore (Sync)
- ✅ Collaborative Memory (WebSocket)

### Phase 3: Awareness (Complete)
- ✅ Ghost Decisions — Silent Drift Detection
- ✅ Explainable Memory Chat ("Why do we...?")
- ✅ Agent Handoff Packets
- ✅ Memory Debt Score (complement to Health Dashboard)

### Phase 4: Intelligence (Complete)
- ✅ Decision Market / Calibration Score
- ✅ Memory Lens — IDE Inline Annotations
- ✅ Predictive Context Prefetch
- ✅ Bidirectional Slack Decision Capture

### Phase 5: Meta (Complete)
- ✅ Memory Time-Travel Debugger
- ✅ Contradiction Detection (Active)
- ✅ "Digital Twin" Contributor Personas
- ✅ Federated Anonymized Benchmarking

### Phase 6: Sustainability & Implicit Signals (Complete)
- ✅ Preventive Ghost Decision Checks (Pre-Write Hook)
- ✅ Memory Compaction / Epoch Summarization
- ✅ Friction Mining (Implicit Signal Capture)
- ✅ Predictive Context Prefetch / Budget-Aware Assembler

### Phase 7: Validation & Cost Intelligence (Complete)
- ✅ Rationale Corroboration via Tropebook
- ✅ Cost Ledger (Decision Impact ROI)

### Phase 8: Distribution & Narrative (Complete)
- ✅ PR Bot Delivery Surface
- ✅ Narrative Mode (Non-Technical Audience)

### Phase 9: Testing & Infrastructure (Complete)
- ✅ 1292 tests passing (up from 262)
- ✅ 7 previously untested subsystems now have full coverage (3,093 lines)
- ✅ Background scheduler for automatic periodic tasks
- ✅ SSRF protection, file locking, atomic memory writes
- ✅ Corroboration results writing back to decision confidence scores
- ✅ Friction mining wired to session-end processing
- ✅ Session-start context using handoff packets + cross-project briefing
- ✅ Friction Mining UI fix — "Scan for Friction" button now works (was missing JS handler)

### Phase 10: Deep Research & Emacs Integration (Complete)
- ✅ Deep Research (last30days engine) — multi-source research with LLM synthesis
- ✅ Deep Research feed provider (`research_provider: "deep_research"`)
- ✅ Deep Research UI section + Settings panel for source keys
- ✅ Deep Research synthesis driver (pipeline + LLM + HTML in one pass)
- ✅ Emacs integration package (`emacs/tropelex-capture.el`)
- ✅ Feed intelligence 404 fix (was using wrong storage path)
- ✅ Slack capture / market router fix (`load_project_memory` → `get_project_memory`)
- ✅ BRAVE_SEARCH_API_KEY → BRAVE_API_KEY bridge for engine subprocess
- ✅ Security: masking AUTH_TOKEN, CT0, BSKY_APP_PASSWORD in settings API
- ✅ Unsaved settings prompt (beforeunload + nav guard)
- ✅ Project selection persistence fix (localStorage restore on init)

### Phase 11: Dashboard Overhaul & Emacs Magit/LSP (Complete)
- ✅ Dashboard: Git Status, Key Decisions, Impact cards with colored header bars
- ✅ Dashboard: Emacs added to Getting Started checklist
- ✅ Dashboard: Section state persistence (inputs + results saved across navigations)
- ✅ Dashboard: Logo animation (tl.png + pulsing dot)
- ✅ Dashboard: Favicon change (TL1.ico)
- ✅ Dashboard: "Power Up with Emacs" button linking to help docs
- ✅ Emacs: Magit integration — auto-capture decisions from git commits
- ✅ Emacs: LSP context — captures include function name/type from eglot/lsp-mode/treesit
- ✅ Emacs: Code context in decision captures (function name, class, type)
- ✅ 17 router `_load_memory` fixes — all routers now use MemoryManager
- ✅ Run Pipeline button fix (missing element ID)
- ✅ 46 new tests (test_deep_research.py, test_router_fixes.py, test_last30days_runner.py)

### Phase 12: Safety, Alignment & Governance (Complete, uncommitted)
- ✅ Safety Metadata on decisions (risk_level, reversibility, affected_systems, safety_category, requires_review)
- ✅ Safety Dashboard, Decision Impact Analysis, Safety Review Workflow
- ✅ Alignment Evaluation, Governance Compliance (EU AI Act, NIST, ISO 42001)
- ✅ Fairness, Accountability, Robustness, Interpretability, Transparency reports
- ✅ Provenance Chain, Integrity Verification, Tamper Detection, Security Audit Log
- ✅ Decision Versioning with rollback
- ✅ Synthetic Data Policy framework (EU AI Act Art. 10 & 50) with 10 blocking compliance gates
- ✅ 116 new tests (1292 → 1408 total, all passing together)
- ✅ Fixed a cross-test rate-limiter state leak (`tests/conftest.py`) that was causing 21 failures in this area when the full suite ran together — see `design.md` §17
- ⚠️ Known gap: implemented inline in `core/tropebook/web/server.py` rather than a dedicated `core/` module (breaks the pattern every prior phase followed)

---

### Phase 13: Agent Surface Audit & Cross-Connections (Complete)
- ✅ Agent Surface Audit (`core/agent_audit/`, feature #37) — scans the agent's own harness config (CLAUDE.md/AGENTS.md, .mcp.json, .claude/settings.json, hooks, agent/skill definitions) for secrets, over-broad permissions, hook-injection risk, MCP server risk, and injected instructions. Inspired by AgentShield.
- ✅ Safety & Alignment dashboard consolidation: 6 separate sidebar sections (Safety Dashboard, Alignment, Governance, Provenance, Reviews, Synthetic Data) collapsed into one sidebar entry with 7 in-page tabs (the 6 plus Agent Audit), each lazy-loaded on selection instead of all six loading eagerly together
- ✅ Cross-connect: Friction Mining → Safety score. Recent friction history (capped, last 10 scans) now contributes a bounded penalty to the aggregate safety score, not just the Health Dashboard. Also fixed: `friction_history` was read by `/friction/summary` but nothing had ever written to it — the scan endpoint now persists results.
- ✅ Cross-connect: Contradictions / Doc Mining → Safety Review queue. High-severity contradictions and doc-vs-decision findings auto-escalate their decisions' `requires_review` flag instead of only surfacing in their own tabs.
- ✅ Cross-connect: Personas + Decision Market → Safety Review queue. A decision touching a category that's *both* a known persona weakness *and* has poor market calibration auto-escalates — neither signal alone is enough, since every project has some weak category and some mediocre bet.
- ✅ Cross-connect: Cost Ledger ↔ Decision Market. New `GET /{project}/cost/compounding-risk` surfaces decisions with real rework cost *and* poor calibration in the same category — previously these lived in unconnected tabs.
- ✅ Cross-connect: PR Bot → Safety & Alignment. PR comments now include a "Safety & Alignment" section for any relevant decision that's high/critical risk or flagged for review — previously PR Bot only surfaced ghost decisions and health scores.
- ✅ Cross-connect: Federation (renamed Benchmarks) → safety-posture benchmarking. `AnonymizedStats` gained `avg_safety_score` and `risk_level_distribution`, threaded through share/aggregate/compare — anonymized safety posture, not just structural stats like reversal rate.
- ✅ 66 new tests (1408 → 1474 total, all passing together)

---

### Phase 14: Integration Debt, Data Integrity & Search Resilience (Complete)
- ✅ Wired 5 previously-built-but-orphaned endpoints into the dashboard: `handoff/roles`, `agent-skills/briefing`, `cross-pollinate/briefing`, `sessions/weekly-summary` (also fixed a real route-shadowing bug — it was registered after `/sessions/{session_id}` and so was permanently unreachable), and `cost/compounding-risk`.
- ✅ Deleted Research Chains (`core/research_chains.py`) — redundant with Deep Research + Feeds, confirmed unused anywhere in the UI.
- ✅ Wired Memory Lens into the VS Code extension (inline hover annotations, `tropelex.scanFileForDecisions` command).
- ✅ Fixed Deep Research not persisting Hybrid/Citation-Grade runs (only `last30days` runs were ever saved) and a related bug where those runs would have rendered as raw unrendered markdown instead of HTML.
- ✅ Fixed a real `knowledge_decay.score_decision` bug: self-comparison used object identity (`is`) instead of `id` equality, silently inflating every decision's confidence score whenever callers passed reconstructed objects (e.g. `DecisionTree` nodes) rather than the original list — this broke Memory Compaction's stale-chain detection universally, not just for test data.
- ✅ Git sync repo-fingerprint safeguard: `sync_repo_to_memory` now fingerprints a repo (origin remote URL, falling back to root commit hash) and blocks a later sync from a different repo into the same project instead of silently mixing histories, with a `force` override. Root cause of an earlier real incident where a project's memory got contaminated with another repo's commits.
- ✅ Renamed Federation → Benchmarks — the old name implied cross-machine networking it never had (confirmed zero networking code). Added genuine cross-install comparison via `GET /benchmarks/export` / `POST /benchmarks/import`: a portable JSON bundle handed between installs as a plain file, no network call.
- ✅ Fixed Account Backup silently importing zero citations on every import, always — it iterated `tropebook.citations` (a dict keyed by ID) as if it were a list, so the `isinstance(citation, dict)` check that followed could never pass. New `Tropebook.import_bundle()` also preserves citation IDs so relationship-graph edges survive the round trip, which the old `add()`-based path could never have restored even once the iteration bug was fixed.
- ✅ Fixed Account Backup export leaking live credentials: its secret-exclusion list only covered 6 of the 17 keys the Settings API treats as credentials, so `BSKY_APP_PASSWORD`, `CT0` (X/Twitter session cookie), and others were written into exported JSON despite the UI's claim that "API keys are excluded." Both lists now come from one shared `SECRET_ENV_KEYS` set.
- ✅ Search fallback waterfall for Auto-Research (`/api/research/auto`): Brave → Exa → Serper → DuckDuckGo, matching the tiering `last30days` already had — previously this endpoint was Brave-or-DuckDuckGo only, with Exa/Serper keys accepted by Settings but never consulted here. Documented in `API_KEYS.md`/Settings/guide, including that Brave dropped its free tier in Feb 2026 (now $5 prepaid minimum, ~$0.003–$0.005/query).
- ✅ Decision Market: added `DELETE /{project}/market/clear` (previously no way to wipe accumulated bet data short of hand-editing memory JSON) and documented `agent_name` naming conventions, including the caveat that Agent Skills tracks proficiency per-project, not per-agent, unlike Decision Market's genuinely per-agent calibration.
- ✅ Removed 4 cross-project-contaminated decisions from a project's memory (verified via git hash cross-reference — they were verbatim Tropelex commits mined into an unrelated project).
- ✅ ~32 new tests across this phase, full suite passing together (1434 total).

---

## Technical Notes

### Storage Considerations
- Versioned snapshots will need delta compression
- Knowledge graph requires graph database or adjacency list
- Collaborative memory needs conflict resolution

### Performance Considerations
- Semantic search requires embeddings (already have embeddings.py)
- Graph visualization needs efficient traversal
- Alert system needs background workers

### Integration Points
- All features expose REST API endpoints
- UI updates are incremental (no full page reloads)
- CLI mirrors all API functionality
- Background scheduler runs automatic periodic tasks

---

## Success Metrics

### Memory Quality
- Decision confidence scores > 0.7 average
- Session history coverage > 90%
- Pattern detection accuracy > 80%

### User Engagement
- Daily active usage of memory features
- Research feed run frequency
- Decision recording rate

### Knowledge Growth
- Memory size over time
- Cross-project transfers
- Pattern library expansion

---

**Last Updated:** 2026-07-30
**Status:** All features implemented except #19 (Session Replay with AI Analysis, still open) + Deep Research + Emacs Magit/LSP + Dashboard Overhaul + Safety, Alignment & Governance (Phase 12) + Agent Surface Audit, Safety & Alignment tab consolidation, and 6 cross-feature safety connections (#37, Phase 13) + integration-debt cleanup, data-integrity fixes, and search resilience (Phase 14). #30 (Rationale Corroboration) removed 2026-07-28 — see its entry above.
**Next Review:** 2026-08-15
