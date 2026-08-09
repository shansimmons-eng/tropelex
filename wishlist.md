# Tropelex Wishlist

**Novel features and improvements planned for future development.**

Grouped by function (what the feature is *for*), not by build priority or chronology, mirroring the dashboard sidebar's category structure. See `## Implementation Roadmap` below for the phase-by-phase build history.

---

## Engine Core

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

### 6. Ghost Decisions: Silent Drift Detection
**Purpose:** Detect when code quietly contradicts recorded decisions without anyone saying so.

**Why:** The #1 real failure mode in every team's architecture docs: docs say X, code does Y, nobody notices for months. Tropelex records decisions and detects when a new decision supersedes an old one, but has no idea when code silently drifts from documented decisions.

**Features:**
- Diff incoming commits against the decision corpus
- Pattern-match decision text against diff hunks (e.g., "snake_case" vs camelCase in code)
- Flag silent decision drift as "ghost decisions": contradictions nobody documented
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

**Why:** Everything currently depends on explicit recording. Real friction (agent getting corrected, human retyping with growing annoyance, repeated reverts) never gets captured. This is the data source current tools (Continue, Cursor, mem0, Zep) don't touch.

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

**Status:** ❌ Removed (2026-07-28). Web-search-based keyword matching was a poor fit for most real decisions: anything self-referential to the project's own architecture/tests has no public source to corroborate against, so results were consistently irrelevant regardless of query-quality fixes (narration-verb stripping, rationale-only queries, etc., see git history on `core/corroboration/` before removal). Removed rather than kept as a feature that mostly produced noise.

---

### 45. Session-Shape Baselining (Tool-Call/Token/Latency Drift Signals)
**Purpose:** Baseline the *shape* of a normal session — tool-call counts, tool-call variance, token counts, latency, hang duration, output size — so a deviation from that baseline becomes a detectable signal, not something only noticed in hindsight.

**Why:** From the earliest brainstorm this project had on drift (before it had any concrete shape): does an agent use consistent tool calls or shift around session to session? Does output size vary significantly for the same call? Which calls fail? When something that normally hangs suddenly stops — what does that mean, and is it actually progress or a silent failure? Friction Mining (#28) captures *language*-level signals (corrections, retries, escalation); nothing captures *behavioral telemetry*-level signals the same way. The trigger registry (`core/triggers/`, added alongside the tag-required gate) formalizes "event → check → logged result" for git-level events (pre-push checks) — this would be the same pattern applied to in-session telemetry instead. Tracked live as goal `063021bb1eb3` in the `tropelex` project.

**Why now, specifically:** the [emergentmind.com/topics/agent-drift](https://www.emergentmind.com/topics/agent-drift) research pass (2026-08-07) reports drift incidence approximating 50% in multi-agent LLM workflows by 600 interactions — the base rate is high enough that this isn't a rare-edge-case feature, it's closer to a default failure mode worth actually instrumenting for.

**Status:** Open. Proposed early in the session that led to #35/#40/#41/#43/#44 — the oldest unimplemented idea in this list, finally given a number once the surrounding infrastructure (trigger registry, Goals, drift detection) existed to build it on.

---

### 50. Error Handling Audit: Unguarded Writes + Result-Type Consolidation
**Purpose:** A real audit of "how robust is error handling here," prompted directly by the pre-push hook's `check_error_handling_present` warnings (#40's trigger registry) rather than assumed from the check's raw output.

**Why:** The check itself only scans `core/*/router.py` — it never looks at `server.py`'s ~150 inline endpoints, so its count is an undercount of what exists to check, not an overcount. Of what it *did* flag, most were false positives: routers built around a `_load_memory`/`_save_memory` helper pair have real error handling in `_load_memory` (try/except, logged, clean 404/500) that the check can't see one function away. But digging past the false positives surfaced a real, systemic gap: `_save_memory` had **no error handling at all**, in every router where that helper exists (market, goals) — a disk-full, permission, or lock-contention failure on write would have surfaced as a raw unhandled exception instead of a clean logged 500. Not something introduced this session; goals' router faithfully copied an already-present gap in market's.

Separately, auditing the *other* half of error handling (business-logic `Result`/`Ok`/`Err` — used for expected failures like validation and not-found) found it consistently well-designed everywhere it's used, but independently copy-pasted byte-for-byte in **17 separate files** rather than shared from one place. `core/goals` was the only module importing it from elsewhere (from `core.market`) instead of redefining it — everyone else, including the one module flagged earlier this session as "the inconsistency," redefines its own copy.

**Features:**
- New `core/result.py` — the actual canonical `Result`/`Ok`/`Err`, replacing 17 independent copies (`agent_audit`, `benchmarks`, `contradictions`, `cost`, `docmine`, `friction/miner`, `ghost/preventive`, `lens`, `market`, `narrative`, `personas`, `prbot`, `prefetch/{assembler,genealogy,tuner}`, `slack`, `timetravel`). Domain-specific exceptions (`MarketError`, `ContradictionError`, etc.) stayed put — legitimately domain-specific, not part of the generic type. `core/goals` updated to import from `core.result` directly instead of the `core.market` stopgap.
- `_save_memory` in both `core/market/router.py` and `core/goals/router.py` now wrapped in try/except, matching `_load_memory`'s existing pattern exactly (log + clean `HTTPException(500)`).

**Status:** ✅ Implemented. Tests: `TestSaveMemoryErrorHandling` in `tests/test_market_router.py` and `tests/test_goals.py` (monkeypatches `MemoryManager.save_project_memory` to raise, asserts the response is FastAPI's structured `{"detail": ...}` shape — proof the guard is what's producing the response, not just that *some* 500 comes back). Full suite at 1651 passing.

---

## Explainability & Discovery

### 7. Explainable Memory: "Why do we...?" Chat
**Purpose:** Conversational front-end that fuses RAG + decision tree + impact analysis into causal answers.

**Why:** "Why do we use Postgres instead of MySQL?" should trace the decision, who made it, confidence/tier, what superseded it, and what it caused downstream. This is qualitatively different from search: it's architecture archaeology as a conversation.

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

### 15. Memory Lens: IDE Inline Annotations
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
- `POST /api/memory/{project}/prefetch`: task + token_budget → bundle + near_misses + bundle_id
- `POST /api/memory/{project}/prefetch/{bundle_id}/outcome`: referenced_ids + requested_but_missing

---

## Safety & Alignment

### 35. Safety Metadata, Review Workflow & Alignment/Governance Scoring
**Purpose:** Risk classification, review workflow, and multi-dimensional alignment/governance scoring for the decision graph.

**Why:** Decisions were recorded with confidence and rationale but no risk classification, review trail, or compliance framing, which is needed for evaluating Tropelex as safety-relevant infrastructure (see `SAFETY.md`) rather than just a productivity tool.

**Features:**
- Safety metadata on every decision: risk_level, reversibility, affected_systems, safety_category, requires_review
- Safety Dashboard: risk trends, system exposure, aggregate safety score
- Safety Review Workflow: pending queue, approve/reject, reviewer accountability, mitigation suggestions
- Alignment Evaluation: scoring across interpretability, safety, fairness, robustness, governance
- Governance Compliance: EU AI Act, NIST, ISO 42001 policy checks
- Fairness Audit, Accountability Tracking, Robustness Testing, Interpretability Reports
- Provenance Chain, Integrity Verification, Tamper Detection, immutable Security Audit Log
- Decision Versioning with rollback

**Status:** ✅ Implemented. As an exception to this codebase's own pattern: every other feature above ships as its own `core/<name>/` module with a router; this one (~3,200 lines) is inline in `core/tropebook/web/server.py`. Candidate for extraction into `core/safety/` + `core/governance/`. Tests: `tests/test_safety_features.py`, `tests/test_alignment_governance.py`, `tests/test_far_cais_sff.py`.

---

### 36. Synthetic Data Policy
**Purpose:** EU AI Act Articles 10 & 50 compliant "nutritional label" for synthetic datasets used in agent training/eval.

**Why:** Decisions can now carry safety metadata, but nothing tracked the provenance and compliance posture of *synthetic data* feeding those decisions.

**Features:**
- Full CRUD for synthetic dataset registration with fidelity, privacy (ε/δ), bias audit, adversarial testing, source data, rationale, distinguishability, model-collapse-prevention, retention, and attestation metadata
- 10 blocking compliance gates run per policy
- UI registration form + compliance dashboard
- Aggregate statistics across all registered policies

**Status:** ✅ Implemented (`core/tropebook/web/server.py`, same inline-implementation caveat as #35). Tests: `tests/test_synthetic_data_policy.py` (note: 17 of these currently fail only when the full `pytest tests/` suite runs together (pass 100% in isolation); see `design.md`'s Security Features section for the known cross-test state-leak issue).

---

### 37. Agent Surface Audit
**Purpose:** Scan the agent's own harness configuration for risk: secrets, over-broad permissions, hook-injection risk, MCP server risk, and injected instructions.

**Why:** Every other feature in this list audits decisions and code: the things an agent *produces*. Nothing audited the agent's own operating environment (`CLAUDE.md`/`AGENTS.md`, `.mcp.json`, `.claude/settings.json`, hooks, agent/skill definitions), even though a leaked key in a committed config file, an unrestricted `Bash(*)` permission, or a hook that pipes remote content into a shell is a safety-relevant risk that never shows up in the decision graph. Inspired by [AgentShield](https://github.com/affaan-m/agentshield)'s five-category shape, reimplemented as pure functions so it plugs into the same severity-ranked finding pattern Contradictions and Doc Mining already use, rather than shelling out to a separate tool.

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

### 40. Injection Sentinel: Ingested-Content Screening
**Purpose:** Screen externally-sourced content for injected instructions before it's written into memory that a future agent session will read back as trusted context.

**Why:** Tropelex ingests content it doesn't originate: web-researcher search/scrape results, docmine-scanned files, and Slack/Emacs `capture_decision` text all get written into `memory["decisions"]` or the citation graph. Nothing currently screens that content before storage. A scraped page or a pasted message with embedded instructions ("ignore the above and...") sits quietly in a decision's `context` field until a later session reads it back as memory and treats it as instructions rather than data — a stored-prompt-injection vector, distinct from Agent Surface Audit (#37), which scans the harness's *own* config rather than content flowing *through* it. Came out of a brainstorm on what to take from 2026 industry guardrail architectures (Tencent's Agently Mail two-stage confirmation, generic "injection sentinel" input-filtering layers), reframed for what Tropelex actually is — a memory store being read back into future context, not an inference-serving pipeline protecting downstream compute cost.

**Features (proposed):**
- Cheap regex/heuristic scan at the three ingestion points: `core/tropebook/web_researcher_client.py` / `research_pipeline.py` results, `core/docmine/` file scans, and `core/slack/capture.py`
- Reuses the prompt-injection marker patterns Agent Surface Audit (#37) already has for config scanning, extended to freeform ingested text
- Flag, don't silently drop: a hit gets a `content_flags` marker on the stored item rather than being blocked outright — consistent with the project's "surface friction, don't hide it" pattern established for the decision `safety_category` gate (#35), not a silent filter
- Severity-ranked findings, same shape as Contradictions/Doc Mining

**Status:** Open. Proposed 2026-08-06.

---

### 41. Goal Entity & Alignment Layers
**Purpose:** A first-class, prospective `Goal` object — what a project is aiming at, before decisions accumulate under it — mapped onto AI alignment theory's outer/inner/behavioral layers.

**Why:** Decisions capture what *was* decided, retrospectively. Nothing captured what was being aimed at, prospectively. This came out of a conversation mapping Tropelex onto outer alignment (is the specified goal itself right — nothing to point at, until this), inner alignment (does pursuit match the stated goal — Ghost Decisions already did this shape for decision-vs-code, extended here to goal-vs-decision), and behavioral alignment (Decision Market/Friction/Agent Skills already measure this, but couldn't be sliced by goal). Discovered along the way: the codebase already had `/{project}/alignment/drift` — real baseline-vs-recent risk/review-rate drift detection, just unscoped and dead in the dashboard ("not enough data"). Extended rather than duplicated.

**Features:**
- Goal schema: `text`, `status` (proposed → active → achieved|abandoned, illegal transitions rejected), `priority` (low/medium/high/critical), `category` — either a bare `SAFETY_CATEGORIES` value or a `"nonsafety:<label>"` namespaced string (precedented by Pattern Learner's `"category:ui"`/`"day:monday"` namespacing, not improvised)
- Neither `status` nor `priority` is gated the way `safety_category` is on Decision (#35) — a goal defaulting to `proposed`/`medium` isn't a silently-guessed value the way an unset safety category was; `category` defaults to `None`, an honest unclassified state
- Full CRUD + dedicated status-transition endpoint (`core/goals/router.py`), project-scoped in the same memory blob as decisions (not a global file, unlike Research Feeds — goals are inherently per-project)
- Two independent drift signals, composed (not duplicated) in `GET /goals/{id}/alignment`: semantic drift (Jaccard keyword overlap between a goal's text and its linked decisions', reusing Ghost Decisions' technique, worst-case aggregated so one badly-drifted decision surfaces immediately rather than being averaged away) and trend drift (the extracted, goal-scoped version of the pre-existing `/alignment/drift` risk/review-rate comparison)
- `Decision.goal_id` — optional FK, validated at the router boundary exactly like Decision Market's `decision_id` validation, never inside pure logic
- Market calibration and friction context composed into the same alignment endpoint — friction is explicitly labeled `friction_penalty_project_wide`, not fabricated as goal-scoped, since `friction_history` entries carry no `decision_id`/`goal_id`
- `propose_goal` MCP tool; `capture_decision` gained an optional `goal_id` param
- Dashboard: new Goals tab next to Memory in Engine Core (list/detail/create, status-transition buttons, inline drift + calibration panels); Add Decision form gained an optional goal-link select

**Status:** ✅ Implemented (`core/goals/`). Tests: `tests/test_goals.py` (42 tests). `core/tropebook/web/server.py`'s `get_alignment_drift` and `_friction_penalty` were refactored into reusable pure functions (`core/goals/drift.py`'s `score_trend_drift`, `core/friction/miner.py`'s `compute_friction_penalty`) as part of this — behavior-preserving, existing test coverage (`tests/test_far_cais_sff.py`) unchanged.

---

### 42. Formalized Goal Adherence Scoring
**Purpose:** Replace `score_trend_drift`'s baseline-vs-recent risk/review-rate comparison with a proper adherence score δ(t) = 1 − A(t), the formalization used in the agent-drift literature.

**Why:** Reading [emergentmind.com/topics/agent-drift](https://www.emergentmind.com/topics/agent-drift) after shipping Goals (#41) surfaced that "Goal Drift" in the literature is exactly what `score_trend_drift` approximates — just less rigorously. Our version compares risk-level/review-rate trend as a proxy; the literature's adherence score is a more principled, purpose-built metric for the same question. Tracked live as goal `a58ac59c62cc` in the `tropelex` project.

**Status:** Open. Proposed 2026-08-07. Low priority — the current approximation is functional; this is a rigor upgrade, not a gap.

---

### 43. Coordination Drift Detection
**Purpose:** Detect declining agreement between multiple agents over time, not just one agent's individual calibration.

**Why:** Decision Market (#14) already tracks each agent's calibration independently (accuracy, overconfidence_index), and the dashboard already shows multiple agents active on the same project (Claude, Gemini, gemini-3.6-flash in Agent Activity Split). Nothing currently asks whether those agents are *converging or diverging from each other* — a distinct signal from individual calibration, and one the agent-drift literature treats as its own category ("Coordination Drift," tracked via cumulative agreement rates). Tracked live as goal `a8c978b3ae25` in the `tropelex` project.

**Status:** Open. Proposed 2026-08-07. Not urgent — no current pain point, but a real gap in what's measured.

---

### 44. Goal Re-Anchoring in Context Bundles
**Purpose:** Actively surface a project's active Goals back into a live agent's working context (via `get_context_bundle` / `get_handoff_packet`), instead of Goals sitting passively until someone queries them.

**Why:** The agent-drift literature's top mitigation strategy is "structure the prompt to re-anchor agent intent at each turn" — repeated goal reminders measurably reduce drift. Goals (#41) currently only get read when something explicitly queries `/goals` or `/goals/{id}/alignment`; nothing re-injects them into a session the way decisions already get assembled into context bundles. This is a small extension of existing infrastructure (`core/prefetch/`, `core/handoff/`), not a new subsystem. Tracked live as goal `43f95811bf29` in the `tropelex` project.

**Status:** Open. Proposed 2026-08-07. The single most actionable item from the agent-drift research pass — cheapest to build, most directly matches the "ongoing, not set-and-forget" philosophy behind #35/Needs Attention.

---

### 51. `nonsafety:bug` Convention (Chatbot Alternative)
**Purpose:** A lightweight, no-new-subsystem way to capture bug reports through Goals, offered as the smaller alternative to "add a support chatbot to the project."

**Why:** Asked directly whether a Q&A/bug-report chatbot was worth adding. The honest answer: not yet — no evidence of the external-user support burden that would justify it, and the goal ("capture and track bugs") is already reachable through Goals' existing `nonsafety:<label>` category namespace with zero backend changes. Standardizing on `nonsafety:bug` as a recognized value, rather than everyone inventing their own label (the same "branding" vs "UX" inconsistency already found once in this project's own goals), is what actually needed building.

**Features:**
- `nonsafety:bug` added as a one-click quick-pick in both category selects (the main Goal create form and the goal-candidate review rows) — sits alongside the safety categories and the freeform "other (non-safety)…" option, not buried inside it.
- 🐛 Bugs quick-filter toggle in the Goals tab list pane, using `list_goals`'s existing `category` query param (no backend change — that filter already existed, nothing surfaced it in the UI).
- Category display formatting (`_formatGoalCategory`) renders `nonsafety:bug` as "🐛 bug" instead of the raw string, in both the list and detail views.

**Status:** ✅ Implemented (`UI/animated_tropebook_dashboard/code.html`, pure frontend). Verified live: create with the bug quick-pick → correct 🐛 chip in both list and detail → filter toggle correctly isolates bug-only goals.

---

## Safety Infrastructure Hardening (External Review, 2026-08-08)

An external code review of Tropelex's safety/alignment infrastructure came back with nine categories of suggestions. Verifying its load-bearing claims against the actual code before building on them surfaced two corrections worth stating up front, since they change the prioritization:

- **The review's suggestion #9 says "immutable security audit log + provenance chain: already present; harden it."** That's not accurate as of 2026-08-07: `get_provenance_chain` and `get_security_audit_log` (`core/tropebook/web/server.py`) both recomputed their output from the current, mutable `decisions` list on every GET, with `chain_valid` hardcoded `True` on every entry and no persisted write-time hash anywhere. Editing historical decision data directly in the memory JSON produced a perfectly clean-looking response on the next call — zero indication of tampering. `verify_integrity`'s "hash chain integrity" check computed a hash and then never compared it to anything. `SAFETY.md` itself claims "an immutable decision history" as a core safety primitive; that claim was not true. This is fixed now — see #52 below — but it means "harden" was the wrong verb; "build" was.
- **The review's suggestion #2 treats `core/embeddings.py` as an already-available drop-in for semantic detection upgrades.** It's a pure cosine-similarity storage/query layer (`put`/`search`/`delete`) — it does not generate embeddings. Any semantic upgrade needs vectors computed externally via `OPENAI_API_KEY`, and should follow the project's existing tiered-fallback pattern (e.g. Compression's dictionary-vs-LLM split) rather than being framed as free.

**My prioritization** (informed by, not deferential to, the reviewer's own suggested order): the reviewer's #1 (enforceable gates + override-as-decision) is correctly identified as the highest-leverage item, but it has an unstated prerequisite — an "override" is only a meaningful audit trail entry if the trail it's written into can't be silently rewritten, which wasn't true until #52. So the real order is #52 first (now done), then #53, then the two genuinely cheap items that reuse infrastructure already built this session (#54, reusing the `require_tag`/gate pattern; #55/#56, composing two detectors that already exist), then the larger, more speculative items last.

1. **#52 — Real append-only audit trail.** ✅ Done — see below. Prerequisite for everything that follows.
2. **#53 — Enforceable gates + override-as-decision.** Highest leverage per the reviewer; now has a real trail to write into.
3. **#54 — Required safety metadata for high-risk decisions.** Low-hanging: directly reuses the `require_tag`/`TagRequiredError` pattern from the `safety_category` gate (#35), just extended to more fields under stricter conditions.
4. **#55 / #56 — Doc Mining + Ghost combined-severity alert, Friction → decision promotion.** Low-hanging: both compose detectors that already exist and already produce structured output; no new detection logic needed, just cross-referencing.
5. **#45 (existing) — Session-shape baselining.** Unchanged priority; the reviewer independently flagged it as high-value, which corroborates rather than changes its existing spot on the list.
6. **#57 — Semantic/structural detection upgrade.** Valuable but bigger than it sounds once the `OPENAI_API_KEY` dependency is honestly scoped in; not low-hanging fruit.
7. **#58 — Knowledge Decay loop closure.** Solid, moderate effort, no new subsystem.
8. **#40 (existing) — Injection Sentinel.** The reviewer's #6 maps directly onto an already-scoped wishlist item; noted, not duplicated.
9. **#59 — Signed/hash-chained handoffs + calibration-based authority.** Depends on #52's real chain to be more than cosmetic signing.
10. **#60 — Drift-Bench evaluation harness.** Most valuable long-term, correctly last — needs a whole scenario corpus and CI wiring, not a single pass.

**Added 2026-08-09** (not from the reviewer's list — surfaced by asking "what have we prevented so far?" of the now-complete #52/#53 pair): #61 slots ahead of #45, since it's cheaper than everything below #56 and it's the report that makes #52/#53's investment legible rather than just theoretically load-bearing. #62 slots near #58 — same "make existing detector output actionable instead of descriptive" shape.

11. **#61 — Prevention Report.** ✅ Done — cheapest remaining item on the list: two new event types on call sites that already have the append-audit-event pattern, one aggregation endpoint, no new detection logic.
12. **#62 — Friction persistence + generic review queue.** ✅ Done — direct extension of #56; the review-queue UI it builds is meant to be reused by #39 later rather than rebuilt.

---

### 52. Real Append-Only Provenance Chain & Security Audit Log
**Purpose:** Replace the recomputed-on-every-GET provenance chain and security audit log with a genuine append-only, write-time-hashed store, so tampering with historical data is actually detectable instead of just not-visible.

**Why:** Verified directly against `core/tropebook/web/server.py`: `get_provenance_chain` and `get_security_audit_log` both walked the *current* `decisions` list and recomputed hashes/events from scratch on every request, with `chain_valid: True` hardcoded unconditionally. `verify_integrity` computed a hash per decision but never compared it to anything — the comparison it needed didn't exist. None of the three could ever detect a mismatch, regardless of what was edited. `SAFETY.md` credits Tropelex with "an immutable decision history"; that wasn't true until this fix, and it's a prerequisite for #53 and #59 to mean anything (an override or a signed handoff is only as trustworthy as the trail it's chained into).

**Features:**
- `_append_audit_event(memory, event_type, **fields)` — writes `memory["audit_log"]` entries at the moment an event happens (not derived after the fact), each hash computed once at write time and chained from the *previous stored* entry's hash.
- Wired into the three write sites the audit log's own docstring already promised to cover: `add_decision` (`decision_created`), `submit_safety_review` (`review_submitted`), `create_decision_version` (`version_created`).
- `get_provenance_chain` and `get_security_audit_log` now read `audit_log` directly instead of reconstructing it; `chain_valid` is a real stored-vs-recomputed hash comparison.
- `verify_integrity` gained `_verify_audit_log_chain`, which checks every entry's own hash and its `previous_hash` linkage against the prior entry — a real check where there was previously a no-op.
- Known, honestly-surfaced limitation: no backfill. Only events written after this fix appear in the log; pre-existing decisions have no corresponding entry. Not faked.

**Status:** ✅ Implemented (`core/tropebook/web/server.py`). Tests: `tests/test_far_cais_sff.py` (`TestAuditLogTamperEvidence` — directly edits/deletes an audit_log entry the way a rogue file edit would and proves it's now caught, which the old implementation could never do). Full suite: 1656 passing (was 1651).

---

### 53. Enforceable Preventive Gates + Override-as-Decision
**Purpose:** Turn Preventive Ghost Checks and Contradiction Detection from advisory (agents can ignore them) into a configurable hard gate, with any override captured as its own audited decision.

**Why:** Reviewer's #1, and independently the highest-leverage item on my own pass — everything else in this list assumes agents actually stop and look at what these detectors surface, and nothing currently enforces that. Now unblocked by #52: an override is only meaningful if it's written into a trail that can't be silently rewritten.

**Features:**
- `GET /{project}/ghost-check` (`core/ghost/preventive_router.py`) now resolves each warning's severity to a policy action via `_policy_for` — module default `{"high": "block", "medium": "warn", "low": "log_only"}`, overridable per-project via `memory["gate_policy"]`.
- A `block` verdict with no recorded override raises **HTTP 409** (with the blocking warnings + how to resolve them in the body) instead of returning 200. This isn't cosmetic: `mcp_server/server.py`'s `_request` raises a `RuntimeError` on any non-2xx status, so a blocked ghost-check surfaces as an actual MCP tool failure the calling agent has to handle, not a warning sitting quietly in a 200 payload it can skip past.
- `POST /{project}/decisions/{decision_id}/override` (+ MCP tool `override_ghost_warning`) records an override with `rationale` + `agent_name`, written into `audit_log` (#52) as its own `override` event — same tamper-evident trail as decision creation and review, not a parallel unaudited mechanism. Future warnings against that decision keep showing up (`"overridden": true`), just stop forcing a block.
- Extracted the write-time hash-chain helper (`_append_audit_event`/`_compute_decision_hash`) out of `server.py` into `core/audit.py` once this became the second consumer — matches the `core/result.py` precedent (#50): shared module beats two copies.
- **Deferred, not built this pass:** Contradiction Detection isn't gated yet (Ghost Preventive Check only); trigger-registry integration for git hooks/in-session tool use; session/role-scoped risk-budget auto-escalation. Scoped out deliberately to ship a real, tested v1 rather than a wider, thinner one — same "ship the UI consumer, don't leave it orphaned" discipline as #48.

**Status:** ✅ Implemented (`core/ghost/preventive_router.py`, `core/audit.py`, `mcp_server/server.py`). Tests: `tests/test_ghost_preventive.py` (`TestGhostCheckGatePolicy`, 6 tests — block/warn/log_only resolution, override-then-retry, 404/422 on bad override requests, per-project policy override). Live end-to-end smoke test: created a decision, forced a policy override to block on `medium`, confirmed 409 with the blocking warning, called the override endpoint, confirmed the retry now returns 200 with `overridden: true`, and confirmed the override landed in the real `audit_log` alongside `decision_created`. Full suite: 1662 passing (was 1656).

---

### 54. Required Safety Metadata for High-Risk Decisions
**Purpose:** Extend the existing `require_tag`/`TagRequiredError` gate (built for `safety_category`, #35) so decisions above a risk threshold, or touching listed critical systems, can't be saved without richer safety metadata — not just a category.

**Why:** Reviewer's #7, folded together with two of the smaller items from the reviewer's #9 sub-list (role-based override authority, provenance/confidence labeling for externally-sourced or synthetic memory items) since they're small extensions of the same "make metadata mandatory and honest" theme rather than standalone subsystems — matches this session's repeated "don't build parallel systems for one idea" instinct. Genuinely low-hanging: the gate mechanism, error shape, and 422-with-suggestion UX already exist and are proven; this reuses them rather than designing something new.

**Features:**
- `core/safety/gate.py` — `require_safety_metadata(risk_level, provided_fields, suggested)`, structurally identical to `require_tag`: no-op for low/medium risk, raises `SafetyMetadataRequiredError` (422, with the auto-classifier's suggestion attached, scoped to just the gated fields) once the *resolved* `risk_level` is `high`/`critical` and `reversibility`/`affected_systems`/`requires_review` weren't explicitly set. Wired into `add_decision` right after `safety_metadata` is resolved, so it keys off the actual value being written — including when a caller explicitly marks an otherwise-mild decision `risk_level: "high"` themselves.
- **Caught mid-build**: `mcp_server/server.py`'s `capture_decision` tool previously gave `reversibility`/`requires_review`/`affected_systems` concrete Python defaults (`True`/`False`/`[]`), which meant every field looked "explicitly provided" to this gate even when the calling agent never thought about them — the exact silent-default failure mode this gate exists to close, just reintroduced one layer up. Fixed by making those parameters `None`-default and only including them in the outgoing `safety_metadata` when the agent actually set them, so an agent that doesn't engage with a high-risk decision gets the real 422, not a rubber-stamped write.
- `core/safety/` created as its own module (`__init__.py` + `gate.py`) — start of the extraction the review asked for, scoped honestly: it holds the new gate, not a relocation of the ~150-line inline safety block (`SafetyMetadata`, `_auto_classify_safety`, and the safety-report endpoints) still living in `server.py`. Moving all of that in the same pass as new gating logic risked exactly the kind of wide, hard-to-review change this project has been deliberately avoiding — noted as a deferred fast-follow, not silently dropped.
- **Deferred, not built this pass:** role-based override authority and provenance/confidence discounting for externally-sourced or synthetic memory items (the reviewer's other two #9 sub-items folded in here) — both are additive on top of this gate rather than blocking it, and didn't fit in the same bounded pass.

**Status:** ✅ Implemented (`core/safety/`, `core/tropebook/web/server.py`, `mcp_server/server.py`). Tests: `tests/test_safety_gate.py` (11 tests — pure-function gate logic + end-to-end router behavior, including the "explicit high risk_level on mild text is still gated" case) + 3 existing tests in `tests/test_safety_features.py` updated (they relied on auto-classified high-risk decisions succeeding with only `safety_category` set, which is exactly what this gate now closes). Live end-to-end smoke test against the running server: category-only high-risk decision → 422 with the auto-classifier's suggestion; same request with explicit fields → 200. Full suite: 1673 passing (was 1662).

---

### 55. Doc Mining + Ghost Combined-Severity Alert
**Purpose:** When a decision's supporting docs have drifted *and* its code has drifted, raise one higher-severity combined finding instead of two separate, equally-weighted ones.

**Why:** Reviewer's #9 sub-item. Genuinely low-hanging: Doc Mining and Ghost Decisions are both already built, already produce structured per-decision findings — this is cross-referencing two existing outputs by shared `decision_id`, not new detection logic.

**Correction found mid-build:** the reviewer's framing assumes "Ghost" means the post-hoc `GET /ghost-decisions` endpoint (`core/ghost/detector.py`). That endpoint currently calls `detect_ghost_decisions` with a hardcoded empty `diff_data: list = []` (`core/ghost/router.py`) — git-diff integration was never wired in — so it can never actually surface anything today, joined with anything or not. This aggregator joins Doc Mining against **Preventive Ghost Checks** (`core/ghost/preventive.py`, #53's `check_diff_for_warnings`) instead, which takes a real diff directly and is the endpoint that's actually live. The broken post-hoc endpoint is a separate, real bug — not fixed here, flagged honestly rather than silently worked around.

**Features:**
- `core/docmine/combined.py` — `combine_doc_and_ghost_findings(doc_findings, ghost_warnings)`, a pure join on `decision_id` (`doc_vs_doc` findings don't reference a decision and are ignored; multiple findings/warnings for the same decision keep the worst severity from each side). Any overlap produces a `CombinedAlert` with `combined_severity: "critical"` — stronger than either source's own tier.
- `POST /{project}/drift/combined-check` (`core/docmine/router.py`) — takes the same `diff` + optional `paths` shape as `/ghost-check` and `/docmine/scan` combined, runs both detectors, returns `combined_alerts` alongside each detector's own totals. Doc Mining's existing high-severity auto-escalation still runs unchanged; this doesn't add a second escalation path.
- Refactored `scan_markdown`'s path-resolution/claim-extraction/detection logic into a shared `_run_docmine` helper so both endpoints call the same code instead of duplicating it.
- **Deferred, not built this pass:** surfacing combined alerts in the Needs Attention panel (#35) — that panel is a no-argument GET, and combined-check inherently needs a `diff` to run, so it doesn't fit the same aggregation shape as `get_needs_attention`'s other sources without either an argument or a cached "last combined-check result." Noted as a real follow-up once there's a natural place a diff comes from (e.g. wired into #53's git-hook path).

**Status:** ✅ Implemented (`core/docmine/combined.py`, `core/docmine/router.py`). Tests: `tests/test_docmine.py` (`TestCombineDocAndGhostFindings` — 5 tests on the pure joiner; `TestCombinedDriftCheckRouter` — 3 tests on the endpoint). Live end-to-end smoke test: a decision ("Use Postgres for the primary database"), a doc claiming MySQL, and a diff switching to MySQL — confirmed `doc_severity: high`, `ghost_severity: medium`, `combined_severity: critical` on the same decision. Full suite: 1681 passing (was 1673).

---

### 56. Friction → Decision Promotion
**Purpose:** A high-friction zone (repeated correction, the same linguistic pattern Friction Mining already scores) auto-suggests — or, above a threshold, requires — a real decision or supersede link, instead of just accumulating a friction score nobody acts on.

**Why:** Reviewer's #9 sub-item. Low-hanging: Friction Mining (`core/friction/miner.py`) already computes the penalty; `detect_decisions`-style suggestion is an established pattern (#48's `detect_goals` is the most recent instance). This wires two existing pieces together rather than building new scoring.

**Correction found mid-build:** the reviewer's framing ("crosses a threshold in a given area") assumes friction is trackable by topic/area over time. It isn't: `friction_history` (the persisted, cross-session record) only stores numeric aggregates per scan (`friction_score`, `severity_distribution`, `agent_name`) — no signal text, no topic. The only place text actually exists is `FrictionZone` (line-proximity clusters within one scan's transcript), which was computed and returned but never persisted. So promotion happens per-scan, from a zone's own signals, not from accumulated cross-session history — a materially smaller scope than "area" implied, and the honest one given what data actually exists.

**Features:**
- `suggest_decision_from_zone(zone)` (`core/friction/miner.py`) — pure function, same "suggest, don't save" shape as `detect_goals`/`preview-category`. Only `zone_severity == "high"` zones (repeated correction/escalation, not one-off noise) produce a candidate; joins up to 3 signal snippets, capped at 500 chars.
- Wired into `POST /{project}/friction/scan`'s existing response as `suggested_decisions` — no new endpoint, no new persistence.
- Dashboard: Friction Mining's existing results panel (already had a live UI consumer, unlike the orphaned `detect_decisions`) gained a "Suggested decisions from repeated friction" section — the third instance of the review-row pattern (category select, Propose, Remove) already used for docmine's uncaptured claims and goal candidates.
- **Deferred, not built this pass:** the reviewer's second bullet ("above a higher threshold, gate further writes in that area") — friction scans aren't tied to a specific write the way #53's ghost-check is, so there's no clean trigger point yet. Would need friction to be scoped by area first (a bigger, separate change) before a gate on it means anything.

**Status:** ✅ Implemented (`core/friction/miner.py`, `core/friction/router.py`, `UI/animated_tropebook_dashboard/code.html`). Tests: `tests/test_friction.py` (`TestSuggestDecisionFromZone` — 5 tests; 2 new router-level assertions on `suggested_decisions`). Live end-to-end verification: backend smoke test via curl, then a full browser pass in the real dashboard — pasted a transcript with a repeated instruction, scanned, got a high-severity zone and its suggested decision, picked a category, clicked Propose, and confirmed a real decision landed in the project's memory (then removed that test decision from the live `tropelex` project afterward, matching this session's cleanup discipline — the append-only audit_log entry it left behind was deliberately not touched, since removing it would be exactly the kind of history-editing #52 exists to detect). Full suite: 1687 passing (was 1681).

---

### 57. Semantic + Structural Detection Upgrade (Ghost + Contradiction)
**Purpose:** Add embedding-based similarity and lightweight AST/structural signals to `core/ghost/pattern_matcher.py` and `core/contradictions/detector.py`, which currently rely on opposing-keyword pairs and Jaccard overlap.

**Why:** Reviewer's #2 — correctly identified as valuable, but the review frames `core/embeddings.py` as an already-available drop-in. It isn't quite: it's pure storage (`put`/`search`/`delete`), not a generator — but `core/llm.py`'s `embed`/`embed_one` (already used for citation semantic search) turned out to already be the generator, gracefully returning `None` with no key configured. So the real infrastructure gap was smaller than expected; the real risk, discovered by actually shipping this against the live `tropelex` project, was elsewhere entirely — see below.

**Shipped scope:** Contradiction Detection only (not Ghost, not AST/structural signals, not the predicate ontology, not the calibration feedback loop — all explicitly deferred, see below). Even that narrower scope surfaced a real incident worth recording in full.

**What happened:** `hybrid_similarity()` blends keyword Jaccard with embedding cosine similarity and feeds the result into `classify_contradiction`'s existing 0.15/0.4 thresholds — tuned years earlier for pure keyword Jaccard's naturally sparse distribution. General-purpose text embeddings don't share that distribution: two *unrelated* same-domain sentences routinely score 0.4-0.6+ on raw cosine similarity, nowhere near zero. Blending scores with different baselines into one number and reusing the old thresholds let far more pairs reach `detect_direct_contradiction`, which unmasked two latent bugs in that function that a decade of low-keyword-similarity filtering had accidentally hidden: (1) opposing-pair checks used raw substring `in` matching, so "add"/"remove" matched inside "added"/"removed"; (2) `_share_subject`'s "any single shared non-stopword" check passed on one coincidental shared word ("feed") between two otherwise-unrelated, differently-worded decisions. Live-tested against the real `tropelex` project (159 decisions, real `OPENAI_API_KEY`): unresolved contradictions jumped from a sane baseline to **272**, and — because high-severity contradictions auto-escalate their decisions into the Safety Review queue (an existing, intentional cross-connection) — **pending reviews jumped from 8 to 61** on the live, in-use project before the bug was caught.

**Fix, verified against the same live project:**
- `detect_direct_contradiction` now matches whole words/phrases (`\b`-bounded), not raw substrings.
- `_share_subject` requires 2+ shared non-stopword tokens, or — for genuinely short decisions where 2 is unrealistic ("Don't use React" vs "We should use React") — 1 shared word that's at least half of the *shorter* side's remaining vocabulary. Targets exactly the failure mode found: one incidental word buried in an otherwise-unrelated, much longer sentence.
- `classify_contradiction` now takes both the hybrid score (permissive gate 1 — lets embeddings rescue real opposition pairs with low keyword overlap, safe because reaching this gate still requires an independent keyword/date-based signal) and the pure keyword score (strict gate 2 and severity bump — the "implicit" category has no independent signal backing it, so it stays exactly as conservative as it was before embeddings existed, immune to the same-domain-baseline problem).
- Re-verified against `tropelex`: 272 → 87 unresolved, 132 → 13 high-severity decisions. The genuine case this feature exists for (JWT vs. session storage, 0.053 keyword similarity — below the old 0.15 gate entirely, so never even reached opposition-detection) still fires correctly; the "Added X" / "Added Y, removed Z" false positive no longer does.
- **Damage recovery on `tropelex`:** identified 55 decisions matching the escalation's exact signature (`requires_review=True`, `risk_level=="medium"`, no `safety_reviews`, no `escalation_reason` — the persona/market path's own marker, ruling that source out) and re-checked each against the corrected algorithm's high-severity set. 47 were reverted to their pre-scan state (`requires_review=False`, `risk_level="low"`); 8 were genuinely valid and left alone. Pending reviews: 61 → 14 (original baseline was 8; the remaining 6 are newly-found *genuine* contradictions like the real MySQL-vs-Postgres pair, correctly kept). This is a best-effort reconstruction, not a true undo — no audit trail existed for this specific mutation path at the time (contradiction auto-escalation was never wired into #52's audit log), so a small number of edge cases (a decision manually created with `risk_level: medium` + `requires_review: true` and no review yet) could theoretically be misattributed. Disclosed in full rather than silently patched.

**Features:**
- `core/contradictions/detector.py`: `hybrid_similarity`, `_cosine_similarity`, `classify_contradiction`'s dual-similarity signature, `detect_contradictions(decisions, embeddings=None)` — fully backward compatible, identical output when `embeddings` is omitted.
- `core/contradictions/router.py`: `_get_decision_embeddings` — caches vectors per-project via `EmbeddingStore` (`core/embeddings.py`, gained a `.get()` method) so a decision is embedded once, not on every `/contradictions` call; gracefully falls back to keyword-only (`semantic_augmented: false` in the response) with no key or on API failure.
- Dashboard: Contradictions tab shows a `semantic-augmented` / `keyword-only` badge — honest disclosure, matching Compression's `backend` field.
- MCP tool `override_ghost_warning` unaffected; this doesn't touch #53's gate, only the read-side `/contradictions` scan.

**Round 2 — vocabulary expansion + a second latent bug found the same way:** Asked directly whether the opposing-pairs vocabulary covered enough safety-relevant circumvention/concealment language (it didn't — the original list was generic add/remove-style phrasing only). Expanded `_OPPOSING_PAIRS` by 33 entries across two passes: concealment (`hide`/`expose`, `obscure`/`clarify`, `obfuscate`/`clarify`, `cloak`/`reveal`, `mask`/`reveal`, `redact`/`disclose`, `withhold`/`disclose`, `conceal`/`disclose`, `suppress`/`surface`), circumvention (`bypass`/`enforce`, `skip`/`enforce`, `omit`/`include`, `ignore`/`address`, `circumvent`/`enforce`, `evade`/`comply`, `waive`/`require`, `relax`/`tighten`, `weaken`/`strengthen`), authorization (`override`/`respect`, `authorize`/`revoke`, `grant`/`deny`, `elevate`/`restrict`), integrity (`tamper`/`preserve`, `purge`/`retain`, `discard`/`retain`, `spoof`/`verify`, `inject`/`validate`, `inject`/`sanitize`, `throttle`/`saturate`), and a few generic ones (`delete`/`preserve`, `strip`/`preserve`, `prioritize`/`deprioritize`, `escalate`/`deescalate`). Left out `undercount`/`overcount`/`miscount` (both sides are error modes, not opposed *decisions* — doesn't fit the pair structure) and a handful of vaguer suggestions (`switch`, `jump`, `away`, `saturate` on its own) with no clean canonical opposite.

Doing this exposed two more real problems, both caught via a **dry-run against the live `tropelex` corpus before touching the escalating endpoint again** (lesson learned from round 1):
1. The hand-written exclusion set in `_share_subject` had *already* been silently out of sync with `_OPPOSING_PAIRS` before any of this — missing over half its own terms (`include`, `allow`, `must`, `should`, `keep`, `stop`, and more). Fixed by deriving it programmatically (`_opposing_pair_tokens()` → `_OPPOSING_PAIR_TOKENS`, computed from `_OPPOSING_PAIRS` itself) instead of hand-maintaining a duplicate list that can drift again as the list grows.
2. `_detect_temporal` turned out to have an *independent* copy of both bugs already fixed once in `detect_direct_contradiction`/`_share_subject` — raw substring reversal-keyword matching (`"undo"` matched inside `"undocumented"`) and its own separate, unfiltered `len(shared) >= 2` topic check with no exclusion at all. It was the dominant source of remaining noise in the corpus (most false positives were `temporal`, not `direct`), specifically from this project's own decision-logging template ("Added feature: X", "Fixed: Y") — two unrelated decisions sharing only "added"/"feature" was enough to pass. Fixed by switching to `_contains_phrase` for the reversal check and having it reuse `_share_subject` instead of duplicating (worse) logic inline, plus a new `_STRUCTURAL_NOISE_WORDS` exclusion set for exactly this project's own logging boilerplate.

Re-verified against `tropelex` after both fixes: 87 → 34 total unresolved, 13 → 2 high-severity. Both remaining high-severity pairs are defensible: the genuine MySQL-vs-Postgres case, and one borderline-but-topically-real case (two decisions about the same `last30days` engine rework) accepted as a known residual limitation rather than chased further — "topically related but not actually opposed" is a harder problem than keyword/embedding blending alone can fully solve, which is exactly why the reviewer's own suggestion #2 called for calibration from real override data (deferred, see below) before pushing this further.

**Damage recovery on `tropelex` (final reconciliation, two passes):** Round 1 identified 55 decisions matching the escalation's signature (`requires_review=True`, `risk_level=="medium"`, no `safety_reviews`, no `escalation_reason`) and reverted 47 that no longer qualified under the algorithm as it stood then, leaving 8. After round 2's further fixes, re-ran the same reconciliation against the *final* algorithm and reverted 6 more of those 8. **Pending reviews: 8 → 61 (incident) → 14 (round 1) → 8 (round 2, final)** — landed back exactly on the pre-incident baseline. This is still a best-effort reconstruction, not a verified undo (no audit trail existed for this mutation path at the time), disclosed in full rather than presented as clean.

**Deferred, not built this pass:** Ghost Decisions' own semantic upgrade (Preventive Ghost Checks weren't touched), AST/structural signal extraction for diffs, the safety-predicate ontology, and the override-feedback calibration loop into Decision Market. All four are additive on top of this pass, not blocking.

**Round 3 — five more pairs, dry-run first this time:** `dismiss`/`flag`, `destruct`/`preserve`, `drain`/`refill`, `decommission`/`keep`, `sidestep`/`address`. `purge` was already covered by round 2 (not re-added); `overload` and `stall` were considered and left out — both describe a state something ends up in ("the server overloaded"), not an intentional decision verb the way the others are, so they don't fit the opposing-decision-pair shape. Applied the discipline round 2 ended on: dry-ran against the live `tropelex` corpus *before* adding anything to the live escalation path — 34 total / 2 high-severity, identical to pre-addition, so nothing new reached the review queue. No further live reconciliation needed.

**Round 4 — ten more pairs, same dry-run discipline:** `establish`/`dismantle`, `connect`/`isolate`, `silence`/`alert`, `brick`/`restore`, `distort`/`clarify`, `guess`/`verify`, `overwrite`/`preserve`, `forge`/`verify`, `pause`/`resume`, `freeze`/`unfreeze`. `conceal` (round 2), `block` (round 1's `allow`/`block`), `reject` (round 1's `adopt`/`reject`), and `deny` (round 2's `grant`/`deny`) were already covered. Left out `convert`, `construct`, `leave`, `format`, `swap`, `trade`, `sweep` (too generic or high false-positive risk — "format"/"leave" in particular are common words in unrelated contexts); `collide` (describes an outcome, not a decision — same reasoning as `overload`/`stall` in round 3); and `constrain`/`defy`/`wipe`/`"let pass"`/`"turn off"`/`"switch off"`/`"make up"` as redundant with `tighten`/`evade`/`purge`/`sidestep`/`disable`/`spoof` respectively. Dry-run against `tropelex` first: 34 total / 2 high-severity, unchanged — no live reconciliation needed.

**Status:** ✅ Implemented, Contradiction Detection only (`core/contradictions/`, `core/embeddings.py`, `UI/animated_tropebook_dashboard/code.html`). Tests: `tests/test_contradictions.py` — `TestCosineSimilarity`, `TestHybridSimilarity`, `TestDetectContradictionsWithEmbeddings`, `TestGetDecisionEmbeddings` (round 1, 15 tests), `TestConcealmentAndCircumventionPairs`, `TestMoreConcealmentAndCircumventionPairs`, `TestOpposingPairTokensStayInSync`, `TestDetectTemporal` (round 2, 13 tests), `TestThirdConcealmentPass` (round 3, 5 tests), `TestFourthConcealmentPass` (round 4, 10 tests) — plus regression fixes in `tests/test_contradictions.py` and `tests/test_safety_features.py` to mock `core.llm.embed` (without which those tests would have silently made real, billed OpenAI calls on every run — caught before merge). Full suite: 1739 passing (was 1687). Live-verified three times against the real `tropelex` project; landed at the exact pre-incident baseline and stayed there through rounds 3 and 4.

---

### 58. Knowledge Decay Loop Closure
**Purpose:** Make the existing 90-day-half-life decay mechanism actionable instead of just descriptive.

**Why:** Reviewer's #3. Decay itself already exists and is reasonable; nothing currently *acts* on a decision crossing a decay threshold.

**Features (proposed):**
- Auto-schedule a review task when a decision's confidence crosses a threshold while still referenced by active code or recent agent actions.
- "Pinned"/constitutional decisions: slower or zero decay, but require periodic re-attestation instead of just being exempted.
- Decayed decisions get down-weighted in Preventive Ghost Checks and Prefetch, not just labeled stale.
- Decay propagates through the decision/impact graph, so downstream decisions lose authority when their foundation does.

**Status:** Open. Proposed 2026-08-08.

---

### 59. Signed / Hash-Chained Handoffs + Calibration-Based Authority
**Purpose:** Make Agent Handoff Packets (#8) tamper-evident, and let Decision Market calibration (#14) affect an agent's default authority, not just its visible score.

**Why:** Reviewer's #4. Explicitly depends on #52 — "hash-chained into the Provenance Chain" only means something once that chain is a real append-only store rather than a recomputed view.

**Features (proposed):**
- Handoff packets hash-chained into `audit_log` (#52) at creation time; receiving agent must acknowledge critical safety constraints from the packet before writing, non-acknowledgment logged as a friction/ghost signal.
- Systematically overconfident agents (per existing calibration/`overconfidence_index`) get lower default authority or stricter review requirements on high-risk categories — an incentive, not just a leaderboard entry.
- Lightweight disagreement protocol: opposing confidence bets from two agents (or agent + human) force an explicit resolution decision rather than both staying active unresolved.

**Status:** Open. Proposed 2026-08-08.

---

### 60. Drift-Bench Evaluation Harness
**Purpose:** A small, deterministic, public scenario suite (silent objective drift, test-passing reward hacking, unresolved conflicting decisions, handoffs that drop constraints, tool-output injection) run continuously in CI against the preventive gate and ghost detector, measuring detection rate, false-positive rate, time-to-surface, and override rate.

**Why:** Reviewer's #8, and independently already proposed in `docs/cais-summary.md` (verified, line 22: "Empirical Drift-Bench Suite"). Correctly last on both the reviewer's list and mine — it needs a real scenario corpus and CI wiring, not a single implementation pass, and it's most valuable once #53's enforcement layer exists to actually measure.

**Features (proposed):**
- Deterministic scenario corpus covering the five drift/injection categories above.
- CI-integrated: regressions in safety coverage become visible the same way test regressions already are.
- Published metrics — strengthens the "empirical safety infrastructure" claim `SAFETY.md` and `docs/cais-summary.md` already make, with actual numbers behind it.

**Status:** Open. Proposed 2026-08-08. Biggest lift on this list; not low-hanging fruit.

---

### 61. Prevention Report
**Purpose:** A report that answers "what have we prevented so far?" from real historical data, not a live recomputation — the missing counterpart to #52's tamper-evident *record* and #53's *enforcement*.

**Why:** Verified directly against `core/ghost/preventive_router.py` and `core/audit.py`: the enforcement gate (#53) already resolves every ghost-check warning to block/warn/log_only via `_policy_for`, but **only the `override` event gets written to `audit_log`**. A block an agent correctly obeyed, or a warn it heeded, leaves no trace — `ghost_check` never even calls `_save_memory`, so nothing from that endpoint persists at all today. `#SAFETY.md` and `docs/cais-summary.md` claim this infrastructure prevents drift; right now there's no data to back that claim with a number. Same gap on the Contradiction Detection side: `_escalate_to_review` (`core/contradictions/router.py`) mutates `requires_review` in place but never writes an audit event, so escalations are only visible as a live snapshot, not a history.

**Features:**
- `core/prevention_report.py` — `build_prevention_report(audit_log)`, a pure aggregation function (same shape as `core/docmine/combined.py`'s joiner): counts `gate_blocked`/`gate_warned`/`contradiction_escalated`/`override` events, severity breakdown, override rationale list, and a calibration signal (`gate_signal_count / (gate_signal_count + override_count)`, i.e. `blocks_and_warns / (blocks_and_warns + overrides)` — a gate whose warnings mostly get overridden is either mistuned or the policy is too strict for this project, worth surfacing either way).
- Two new audit event types in `ghost_check` (`core/ghost/preventive_router.py`): `gate_blocked` (one event per call covering every blocking warning, `decision_ids` + `severity_counts`, written before the 409 raise) and `gate_warned` (same shape, for policy-resolved-to-"warn" warnings on the 200 path) — both via the existing `append_audit_event`. `ghost_check` previously never called `_save_memory` at all (it was effectively read-only); it now does, but only when there's something to persist — a clean diff with zero warnings still writes nothing.
- One new audit event type in `_escalate_to_review` (`core/contradictions/router.py`): `contradiction_escalated` (`decision_id`, `severity_counts: {"high": 1}` — always high, since only `high_severity_ids` ever reach this loop), written at the same point `requires_review` gets flipped. Persists for free via the existing `_mm.save_project_memory` call the caller already makes when `escalated_count` is truthy.
- `GET /{project}/prevention-report` (`core/ghost/preventive_router.py`) — thin wrapper: loads memory, hands `audit_log` to the pure function, returns the result.
- **Deferred, not built this pass:** the dashboard panel (backend/API only this round); friction zones as a data source (nothing to count until #62 ships persistence); Doc Mining + Ghost combined alerts (#55) as a source (same reason #55 itself deferred Needs Attention integration — no natural trigger point without a diff yet); backfill (same honest limitation #52 already disclosed for its own audit log — only events written after this shipped appear in the report).

**Status:** ✅ Implemented (`core/prevention_report.py`, `core/ghost/preventive_router.py`, `core/contradictions/router.py`). Tests: `tests/test_prevention_report.py` (11 tests on the pure aggregation function), `tests/test_ghost_preventive.py` (`TestPreventionReportEndpoint`, 4 tests; existing `TestGhostCheckGatePolicy` tests extended to assert the new audit events, and updated to mock `_save_memory` now that `ghost_check` can actually persist), `tests/test_contradictions.py` (`test_escalation_writes_contradiction_escalated_audit_events`). Full suite: 1754 passing (was 1739). Live end-to-end verification against the real `tropelex` project: restarted the dashboard server to pick up the new routes, confirmed `GET /prevention-report` returned all-zero on a clean audit log (correctly disclosing the no-backfill limitation), created a temporary test decision, ran a real `ghost-check` against it and got a genuine `medium`-severity/`warn`-policy warning, confirmed the `gate_warned` event landed in the real `audit_log` and the report reflected it (`gate_warned_count: 1`, `total_prevented: 1`), then removed the test decision directly from `memory/tropelex.json` while deliberately leaving its audit trail entry untouched (matching #56's precedent), and confirmed via `GET /integrity/verify` that the audit hash chain was still intact afterward (no `entry_hash_mismatch`/`chain_link_broken` — the 19 pre-existing `timestamp_order_violation` issues are unrelated decision-timestamp warnings, not something this change touched).

---

### 62. Friction Persistence + Generic Review Queue (Keep/Dismiss)
**Purpose:** Persist Friction Mining's zone-level findings (not just the numeric aggregate) with a keep/dismiss review state per entry, and build the review-queue mechanism generically enough that #39's auto-imported external sessions can plug into the same UI later instead of needing a second one.

**Why:** Verified directly against `core/friction/miner.py` and `core/friction/router.py`: this is exactly the gap #56 already documented mid-build — `friction_history` (the persisted, cross-session record) stores only numeric aggregates (`friction_score`, `severity_distribution`, `agent_name`) per scan; the actual `FrictionZone` objects (the text, the signals, the severity) are computed and returned by `/friction/scan` but never written to memory. There's no keep/dismiss state anywhere in the system today. High-risk items need a stronger-than-default dismissal bar — a modal requiring name + reason — before the signal can be discarded, mirroring #53's override pattern (`rationale` + `agent_name` → written to the audit trail) rather than inventing a second accountability mechanism.

**Features:**
- `FrictionZone` entries persisted (not just aggregates) to `memory["friction_zones"]` on every `/friction/scan`, each with a stable `id`, full `signals` (text and all — friction_history's aggregates never stored this), an inline `suggested_decision` (reuses #56's `suggest_decision_from_zone`, computed once per zone rather than twice), and `review_status: "pending" | "kept" | "dismissed"`.
- `_bound_friction_zones` caps stored zones without ever silently dropping a **pending** one — unlike `friction_history`'s flat "most recent 50," only already-reviewed (kept/dismissed) entries count against the 200-entry cap. A pending zone is exactly the not-yet-reviewed data this feature exists to stop losing, so capping it away would defeat the point.
- `GET /{project}/friction/zones` (optional `status` filter, newest first), `POST .../keep` (no rationale needed — keeping is the safe default), `POST .../dismiss` — dismissing a `zone_severity: "high"` zone requires `agent_name` + `reason` (422 without them, same shape as #53's `OverrideRequest`) and writes a `friction_dismissed` audit event; low/medium dismissal is a plain status flip, no modal.
- Dashboard: a Review Queue panel in the Friction Mining tab (status filter, signal snippets inline, Keep/Dismiss buttons) plus a modal that gates high-severity dismissal on name + reason client-side (mirroring the server-side 422) before it ever reaches the API. Auto-refreshes after every scan and on tab switch.
- **Deferred, not built this pass:** kept zones becoming input to a "cycle back into the flow" pass (Prefetch/Ghost signal enrichment) — explicitly out of scope, same "ship a real v1, not a wider thinner one" discipline #53 applied to itself. #39's auto-imported sessions reusing this same queue — the queue is generic enough to support it, but #39 itself is still unbuilt.

**Status:** ✅ Implemented (`core/friction/router.py`, `UI/animated_tropebook_dashboard/code.html`). Tests: `tests/test_friction.py` (`TestBoundFrictionZones` — 3 tests on the pending-never-dropped cap logic; `TestFrictionScanPersistsZones` — 2 tests, including one proving a second scan never overwrites a still-pending zone from a prior scan; `TestFrictionZoneKeepDismiss` — 9 tests on keep/dismiss/list, the 422 gate, and the audit event). Full suite: 1768 passing (was 1754). Live end-to-end verification against the real `tropelex` project, both API and browser: ran a real scan producing a high-severity zone, confirmed it persisted with full signal text via `GET /friction/zones`, confirmed dismiss-without-reason 422s and dismiss-with-reason both succeeds and lands a real `friction_dismissed` entry in `audit_log`, confirmed `/integrity/verify` still shows zero hash-chain issues afterward. Then in the actual dashboard: scanned, watched the zone land in the Review Queue with its signal snippets, clicked Dismiss, filled the modal, confirmed the status badge updated and the "Dismissed" filter correctly surfaced it — no console errors from the new code. Test zone removed from `memory/tropelex.json` afterward; its `friction_dismissed` audit entry deliberately left in place, matching #56's precedent.

---

### 48. Goal-Shaped Language Detection (`detect_goals`)
**Purpose:** Regex-scan free text (a pasted session summary, a transcript) for goal-shaped phrasings — "the goal is to", "user requested", "user wants", "needs to", "would like to", "trying to achieve" — and surface candidates for a human to review before creating a real Goal.

**Why:** Came out of a direct question: is "user wants X" a *trigger*? Not in the `core/triggers/registry.py` sense (that fires on discrete external lifecycle events) — it's a *pattern detector*, exactly the shape of an existing-but-orphaned method: `PatternLearner.detect_decisions()` (`core/learner/learner.py`), which regex-scans for decision-shaped phrasings. That method is fully built and tested but has **zero UI consumer anywhere** in the dashboard — confirmed via repo-wide grep. `detect_goals` is the goal-shaped sibling, built specifically to not repeat that mistake: it shipped with its UI consumer in the same pass.

**Features:**
- `core/goals/detector.py` — a third pure-function module in `core/goals/` (alongside `logic.py` and `drift.py`), structurally identical to `detect_decisions` (same `10 < len(content) < 500` filter, same 5-result cap across combined patterns, same two-tier `"high"`/`"medium"` confidence scheme). Deliberately not added to `core/learner/` — Goals must not gain a dependency on Learner.
- `POST /{project}/goals/detect` (`core/goals/router.py`) — suggests candidates without persisting anything, same "suggest, don't save" shape as `preview-category`.
- Dashboard: a "Scan for goal candidates" panel in the Goals tab — the third instance of the review-row pattern already used twice this session (docmine's uncaptured claims, Needs Attention's untagged decisions): paste text, Scan, review candidates with a category picker (reusing the create-form's safety/`nonsafety:<label>` widget pair), Propose creates a real goal via the normal `POST /goals` path.
- Session-end auto-wiring (`add_session`/`record_session`) explicitly **not** built — two different, non-overlapping "session end" endpoints exist (dashboard-button-driven vs. the MCP `end_session` path an agent actually calls), and auto-wiring into the wrong one would silently reproduce `detect_decisions`' orphaned-feature problem. Deferred as a phase-2 decision pending real usage data on whether `end_session` calls carry substantive `summary` text.

**Status:** ✅ Implemented (`core/goals/detector.py`). Tests: `tests/test_goals.py` (`TestDetectGoals`, `TestGoalDetectRouter`, 17 tests).

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

**Status:** Open. This is the one feature on this list not yet implemented.

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

### 39. Auto-Import Sessions from External Coding Tools
**Purpose:** Automatically pull session/conversation history from the major AI coding tools (Claude Code, Cursor, GitHub Copilot Chat, Windsurf, Cline, Aider, and similar) into Tropelex on a schedule, instead of requiring a manual paste into the friction-scan or session-record forms.

**Why:** The agent-identity work (skills, friction, session tracking, all now taggable per `agent_name`) is only as rich as what actually gets recorded, and today that requires a human to manually capture and tag every session. Raw transcripts are the highest-signal data Tropelex could have (they're the actual record of what an agent did and how the human reacted), and almost nobody currently working with multiple coding agents has a way to compare them side by side on real usage rather than benchmarks. Automating the capture is what would make the per-agent skill/friction breakdown genuinely comprehensive instead of only reflecting whatever the user remembers to log by hand.

**Features (needs feasibility research first; this is not yet scoped):**
- Survey where each target tool actually stores session/transcript data locally (formats and locations are largely undocumented and tool-specific, e.g. flat JSONL transcripts vs. an app's internal SQLite/LevelDB storage vs. plain-text chat history files, and can change without notice between tool versions)
- Determine which tools expose anything stable enough to build against (a documented export, a local file format worth committing to, or neither)
- Design the "which agent produced this" tagging so it maps cleanly onto the existing freeform `agent_name` convention (`core/market/calibration.py`'s pattern, now shared by skills/friction/sessions)
- Work out consent/scope: this reads potentially sensitive local conversation history, so opt-in per tool and a clear picture of what leaves the machine (nothing should, by default) matters as much as the technical import path
- Scheduling/dedup: avoid re-importing the same session on every run

**Status:** Idea: needs feasibility research before it can be scoped as a real feature. Worth prioritizing early since the answer ("which tools are even feasible") determines whether this is buildable at all.

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

**Why:** Tropelex is used inside multi-subagent systems. When one agent's session ends and hands off to a different specialist, generate a role-aware context packet: "here's what a TestEngineer specifically needs to know" vs "here's what a Frontend specialist needs."

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

**Why:** Gamifies retrospective honesty. "Alice's gut calls are 85% accurate; Bob is overconfident on auth decisions." Genuinely novel: not in Continue, Cursor, mem0, or Zep.

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

## UI & Presentation

### 38. Global Horizontal Sub-Navigation Migration
**Purpose:** Standardize all dashboard sections to use the horizontal tab architecture established in Safety & Alignment.
**Why:** The left sidebar is suffering from horizontal text overflow and cognitive overload due to the sheer number of features. 
**Features:**
- Restructure sidebar to only contain top-level taxonomy categories (e.g., Content, Quality & Integrity).
- Move all individual features (e.g., Ghost Decisions, Friction Mining) to horizontal tabs within their parent category views.

---

### 49. Attention Pulse Animation for Open-Work Indicators
**Purpose:** A subtle, consistent visual cue applied to indicators that mean "there's real open work here," so they don't read as just another static number on the page.

**Why:** The Needs Attention badge (#35/#41 era) was easy to miss next to everything else on Overview. First implementation used a conic-gradient "chasing border" (a bright segment traveling around the edge), but that technique sweeps by angle, which distorts badly on wide/short pill shapes — the arc bunches into a jagged blob at the rounded ends instead of tracing evenly, and every target here is a pill or a wide stat tile. Replaced with a `box-shadow`-based soft glow that breathes in intensity on a ~2.2s cycle — no directional sweep, so no shape-dependent geometry to go wrong; renders identically clean on badges and the wider stat tile. Reusable `.attn-chase` CSS class, respects `prefers-reduced-motion`, toggled on/off by JS based on whether the underlying count is actually non-zero — never animates a genuinely clear state.

**Features:**
- Needs Attention badge — pulses when `count > 0`.
- Overview's Pending Reviews HUD tile — **was static dead text ("0"/"CLEAR" hardcoded, same underlying issue as the Pytest Suite counter)**, wired to real data as part of this fix by reusing `/needs-attention`'s already-fetched `pending_review` items instead of a second network call — pulses when count > 0.
- Contradictions unresolved-count badge (Overview Quick Triggers) — pulses when count > 0, red glow color to match its existing red/lime text convention.
- Doc Mining's High-severity finding badge — pulses when `severity_distribution.high > 0`.

**Status:** ✅ Implemented (`UI/animated_tropebook_dashboard/code.html`). Pure frontend — no backend changes, no new tests (this repo has no JS test infra, verified live in-browser instead, same as every other dashboard-only change this session).

---

### 46. Tagline Reconsideration: "The Intention Engine"
**Purpose:** Open question on whether the dashboard tagline should change from "The Rationale Engine" to "The Intention Engine."

**Why:** Raised right after Goals (#41) shipped — "Intention" maps almost exactly onto what a Goal *is* (a stated, prospective aim), the way "Rationale" maps onto what a Decision's `context`/`alignment_considerations` capture (retrospective justification). The two words point at the two different halves of the system, and picking one is a real tradeoff, not a wording nitpick: Decisions are the larger, more mature half; Goals are one session old. "Intention" also carries a mild mindfulness/self-help register in casual usage that "Rationale" doesn't, worth being aware of for a tool that's also doing EU AI Act compliance work. Tracked live as goal `f5efe8968745` in the `tropelex` project.

**Status:** Open, not decided. Current recommendation (2026-08-07): keep "The Rationale Engine" until Goals/drift detection have real usage behind them, not just a working demo — same "earn it before renaming" instinct already applied to the "Safety & Alignment" section name.

---

### 47. General Branding Alignment Pass
**Purpose:** A broader review of whether the dashboard's naming/branding (tagline, section names, iconography) accurately reflects what Tropelex has become, rather than one-off tagline swaps in isolation.

**Why:** The tagline question (#46) and the ongoing project-rename exploration (mirrorlex/spiegelloop/tropelex, still undecided — user already owns `tropelex.com`) are really the same underlying question asked at different scopes: does the current branding match the project's actual nature after several phases of growth (Safety & Alignment, Goals, drift detection)? Better done as one considered pass once the underlying feature set has settled, not piecemeal. Tracked live as goal `5ad7ae94788e` in the `tropelex` project.

**Status:** Open. Proposed 2026-08-07. Deliberately vague/broad — a placeholder to revisit once #41's follow-ons (#42-45) and the rename question have more clarity, not a spec to build against yet.

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
- ✅ Ghost Decisions: Silent Drift Detection
- ✅ Explainable Memory Chat ("Why do we...?")
- ✅ Agent Handoff Packets
- ✅ Memory Debt Score (complement to Health Dashboard)

### Phase 4: Intelligence (Complete)
- ✅ Decision Market / Calibration Score
- ✅ Memory Lens: IDE Inline Annotations
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
- ✅ Friction Mining UI fix: "Scan for Friction" button now works (was missing JS handler)

### Phase 10: Deep Research & Emacs Integration (Complete)
- ✅ Deep Research (last30days engine): multi-source research with LLM synthesis
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
- ✅ Emacs: Magit integration, auto-capturing decisions from git commits
- ✅ Emacs: LSP context, captures include function name/type from eglot/lsp-mode/treesit
- ✅ Emacs: Code context in decision captures (function name, class, type)
- ✅ 17 router `_load_memory` fixes: all routers now use MemoryManager
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
- ✅ Fixed a cross-test rate-limiter state leak (`tests/conftest.py`) that was causing 21 failures in this area when the full suite ran together; see `design.md` §17
- ⚠️ Known gap: implemented inline in `core/tropebook/web/server.py` rather than a dedicated `core/` module (breaks the pattern every prior phase followed)

---

### Phase 13: Agent Surface Audit & Cross-Connections (Complete)
- ✅ Agent Surface Audit (`core/agent_audit/`, feature #37): scans the agent's own harness config (CLAUDE.md/AGENTS.md, .mcp.json, .claude/settings.json, hooks, agent/skill definitions) for secrets, over-broad permissions, hook-injection risk, MCP server risk, and injected instructions. Inspired by AgentShield.
- ✅ Safety & Alignment dashboard consolidation: 6 separate sidebar sections (Safety Dashboard, Alignment, Governance, Provenance, Reviews, Synthetic Data) collapsed into one sidebar entry with 7 in-page tabs (the 6 plus Agent Audit), each lazy-loaded on selection instead of all six loading eagerly together
- ✅ Cross-connect: Friction Mining → Safety score. Recent friction history (capped, last 10 scans) now contributes a bounded penalty to the aggregate safety score, not just the Health Dashboard. Also fixed: `friction_history` was read by `/friction/summary` but nothing had ever written to it. The scan endpoint now persists results.
- ✅ Cross-connect: Contradictions / Doc Mining → Safety Review queue. High-severity contradictions and doc-vs-decision findings auto-escalate their decisions' `requires_review` flag instead of only surfacing in their own tabs.
- ✅ Cross-connect: Personas + Decision Market → Safety Review queue. A decision touching a category that's *both* a known persona weakness *and* has poor market calibration auto-escalates: neither signal alone is enough, since every project has some weak category and some mediocre bet.
- ✅ Cross-connect: Cost Ledger ↔ Decision Market. New `GET /{project}/cost/compounding-risk` surfaces decisions with real rework cost *and* poor calibration in the same category. Previously these lived in unconnected tabs.
- ✅ Cross-connect: PR Bot → Safety & Alignment. PR comments now include a "Safety & Alignment" section for any relevant decision that's high/critical risk or flagged for review. Previously PR Bot only surfaced ghost decisions and health scores.
- ✅ Cross-connect: Federation (renamed Benchmarks) → safety-posture benchmarking. `AnonymizedStats` gained `avg_safety_score` and `risk_level_distribution`, threaded through share/aggregate/compare: anonymized safety posture, not just structural stats like reversal rate.
- ✅ 66 new tests (1408 → 1474 total, all passing together)

---

### Phase 14: Integration Debt, Data Integrity & Search Resilience (Complete)
- ✅ Wired 5 previously-built-but-orphaned endpoints into the dashboard: `handoff/roles`, `agent-skills/briefing`, `cross-pollinate/briefing`, `sessions/weekly-summary` (also fixed a real route-shadowing bug: it was registered after `/sessions/{session_id}` and so was permanently unreachable), and `cost/compounding-risk`.
- ✅ Deleted Research Chains (`core/research_chains.py`): redundant with Deep Research + Feeds, confirmed unused anywhere in the UI.
- ✅ Wired Memory Lens into the VS Code extension (inline hover annotations, `tropelex.scanFileForDecisions` command).
- ✅ Fixed Deep Research not persisting Hybrid/Citation-Grade runs (only `last30days` runs were ever saved) and a related bug where those runs would have rendered as raw unrendered markdown instead of HTML.
- ✅ Fixed a real `knowledge_decay.score_decision` bug: self-comparison used object identity (`is`) instead of `id` equality, silently inflating every decision's confidence score whenever callers passed reconstructed objects (e.g. `DecisionTree` nodes) rather than the original list. This broke Memory Compaction's stale-chain detection universally, not just for test data.
- ✅ Git sync repo-fingerprint safeguard: `sync_repo_to_memory` now fingerprints a repo (origin remote URL, falling back to root commit hash) and blocks a later sync from a different repo into the same project instead of silently mixing histories, with a `force` override. Root cause of an earlier real incident where a project's memory got contaminated with another repo's commits.
- ✅ Renamed Federation → Benchmarks: the old name implied cross-machine networking it never had (confirmed zero networking code). Added genuine cross-install comparison via `GET /benchmarks/export` / `POST /benchmarks/import`: a portable JSON bundle handed between installs as a plain file, no network call.
- ✅ Fixed Account Backup silently importing zero citations on every import, always: it iterated `tropebook.citations` (a dict keyed by ID) as if it were a list, so the `isinstance(citation, dict)` check that followed could never pass. New `Tropebook.import_bundle()` also preserves citation IDs so relationship-graph edges survive the round trip, which the old `add()`-based path could never have restored even once the iteration bug was fixed.
- ✅ Fixed Account Backup export leaking live credentials: its secret-exclusion list only covered 6 of the 17 keys the Settings API treats as credentials, so `BSKY_APP_PASSWORD`, `CT0` (X/Twitter session cookie), and others were written into exported JSON despite the UI's claim that "API keys are excluded." Both lists now come from one shared `SECRET_ENV_KEYS` set.
- ✅ Search fallback waterfall for Auto-Research (`/api/research/auto`): Brave → Exa → Serper → DuckDuckGo, matching the tiering `last30days` already had; previously this endpoint was Brave-or-DuckDuckGo only, with Exa/Serper keys accepted by Settings but never consulted here. Documented in `API_KEYS.md`/Settings/guide, including that Brave dropped its free tier in Feb 2026 (now $5 prepaid minimum, ~$0.003–$0.005/query).
- ✅ Decision Market: added `DELETE /{project}/market/clear` (previously no way to wipe accumulated bet data short of hand-editing memory JSON) and documented `agent_name` naming conventions, including the caveat that Agent Skills tracks proficiency per-project, not per-agent, unlike Decision Market's genuinely per-agent calibration.
- ✅ Removed 4 cross-project-contaminated decisions from a project's memory (verified via git hash cross-reference: they were verbatim Tropelex commits mined into an unrelated project).
- ✅ ~32 new tests across this phase, full suite passing together (1434 total).

---

### Phase 15: Tag-Required Gate, Trigger Registry, Needs Attention & Goal Entity (Complete)
- ✅ `add_decision` requires an explicit `safety_category` (`core/triggers/tag_gate.py`'s `require_tag`) — omitting it now 422s with a suggested category attached, instead of silently auto-classifying and writing an unchosen "general" to disk. `SafetyMetadata.safety_category` default changed from `"general"` to `None` to make omission distinguishable from an explicit choice.
- ✅ New `POST /decisions/preview-category` (suggestion without saving) and `GET /decisions/untagged` (triage queue for decisions captured via `/slack/capture` — Emacs/Slack — which fire with no human present and are deliberately exempt from the gate) plus `PATCH /decisions/{id}/safety-category` to tag them after the fact.
- ✅ Fixed a real bug found while building the above: decisions captured via `/slack/capture` had no `id` field at all (`core/slack/capture.py`), so nothing could ever address one individually. `CapturedDecision` gained an `id` default-factory.
- ✅ `core/triggers/` — an event → check → logged-result registry (`core/triggers/registry.py`), with two real pre-push checks (endpoint-has-a-test, endpoint-has-error-handling) merged as a non-blocking addition into the existing `.git/hooks/pre-push`.
- ✅ Dashboard "Needs Attention" panel (Overview, placed after the activity-stream/pattern-learner and risk-mix/agent-split rows so first-time context stays visible first) — aggregates pending safety reviews and untagged decisions via `GET /needs-attention`, always rendered including its clear state, untagged items fixed inline.
- ✅ Fixed a real dashboard accessibility bug: `<select>` option lists rendered with the browser's light-mode native chrome (near-white background) regardless of the app's dark Tailwind classes, since nothing declared `color-scheme: dark`. Affected every dropdown in the app, not just new ones.
- ✅ Goal Entity & Alignment Layers (#41) — see its entry above.
- ✅ 63 new tests across this phase (test_triggers.py, test_safety_features.py additions, test_goals.py), full suite passing together (1632 total).

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

**Last Updated:** 2026-08-08
**Status:** All features implemented except #19 (Session Replay with AI Analysis), #40 (Injection Sentinel), #42–#47 (Goal Adherence Scoring, Coordination Drift Detection, Goal Re-Anchoring, Session-Shape Baselining, Tagline Reconsideration, General Branding Alignment Pass — all proposed 2026-08-07 off the agent-drift research pass following #41, and mirrored as live Goal records in the `tropelex` project via `GET /api/memory/tropelex/goals`), and #58–#60 (the remaining external-review safety-hardening set: Knowledge Decay Loop Closure, Signed/Hash-Chained Handoffs, Drift-Bench Harness — proposed 2026-08-08, prioritized in the "Safety Infrastructure Hardening" section above) + Deep Research + Emacs Magit/LSP + Dashboard Overhaul + Safety, Alignment & Governance (Phase 12) + Agent Surface Audit, Safety & Alignment tab consolidation, and 6 cross-feature safety connections (#37, Phase 13) + integration-debt cleanup, data-integrity fixes, and search resilience (Phase 14) + tag-required gate, trigger registry, Needs Attention panel, Goal Entity & Alignment Layers (#41, Phase 15), Goal-Shaped Language Detection (#48), Attention Pulse Animation (#49), the Error Handling Audit / Result-type consolidation (#50), the `nonsafety:bug` convention (#51), Real Append-Only Provenance Chain & Security Audit Log (#52), Enforceable Preventive Gates + Override-as-Decision (#53), Required Safety Metadata for High-Risk Decisions (#54), Doc Mining + Ghost Combined-Severity Alert (#55), Friction → Decision Promotion (#56), and Semantic Detection Upgrade for Contradictions (#57, Ghost Decisions deferred). #30 (Rationale Corroboration) removed 2026-07-28; see its entry above.
**Next Review:** 2026-08-15
