# Tropelex Wishlist

**Novel features and improvements planned for future development.**

---

## High Priority (Core Improvements)

### 1. Versioned Memory Snapshots
**Purpose:** Automatic versioning of memory state with diff visualization.

**Why:** Currently session replay is manual. Automatic snapshots would create a complete audit trail.

**Features:**
- Auto-snapshot on every memory mutation
- Visual diff between any two snapshots
- Branch/merge support for parallel experiments
- Storage-efficient delta compression

---

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

## Medium Priority (Enhanced Features)

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

## Low Priority (Experimental)

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

### 19. Session Replay with AI Analysis
**Purpose:** AI-generated insights from session diffs.

**Why:** Session diffs are raw data. AI analysis would extract actionable insights.

**Features:**
- Auto-summarize session changes
- Identify decision patterns across sessions
- Suggest process improvements
- Detect regressions or repeated work
- Generate retrospective reports

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

**Status:** ✅ Implemented (core/corroboration/)

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

### 34. Predictive Context Prefetch / Budget-Aware Assembler
**Purpose:** Predict the ideal minimal context bundle for a task before the agent starts, sized to a token budget, prioritized by impact score rather than recency.

**Why:** Context compression is reactive — applied after content is already selected. This closes the loop between context-compressor, impact analysis, and agent skills to predict what the agent needs, sized to budget, and learns from outcomes. Attacks the real pain: context bloat vs. missing the one decision that matters.

**Features:**
- Relevance scoring: composite of impact score, category match, decay confidence, semantic similarity
- Budget-aware knapsack assembler: value-density greedy + exact DP pass for boundary optimization
- Near-miss transparency: excluded items surfaced with scores, not silently dropped
- Skill-aware tuning: widen budget for novice categories, tighten for expert
- Genealogy/feedback loop: precision (included items referenced) and recall proxy (requested but excluded)
- Weight improvement over time from outcome data
- Reuses impact/analysis.py, agent_skills.py, packet_builder.py trimming logic — smallest diff for value

**API:**
- `POST /api/memory/{project}/prefetch` — task + token_budget → bundle + near_misses + bundle_id
- `POST /api/memory/{project}/prefetch/{bundle_id}/outcome` — referenced_ids + requested_but_missing

**Status:** ✅ Implemented (core/prefetch/)

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
- ✅ 1246 tests passing (up from 262)
- ✅ 7 previously untested subsystems now have full coverage (3,093 lines)
- ✅ Background scheduler for automatic periodic tasks
- ✅ SSRF protection, file locking, atomic memory writes
- ✅ Corroboration results writing back to decision confidence scores
- ✅ Friction mining wired to session-end processing
- ✅ Session-start context using handoff packets + cross-project briefing

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

**Last Updated:** 2026-07-19
**Status:** All Features Implemented + Comprehensive Test Suite
**Next Review:** 2026-08-15
