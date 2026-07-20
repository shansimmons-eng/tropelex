# Task Context: Phase 8 — Distribution & Narrative

Session ID: 2026-07-18-phase8-distribution
Created: 2026-07-18T00:00:00Z
Status: in_progress

## Current Request
Implement Phase 8 of the Tropelex wishlist: 2 features that deliver insights where developers actually work (PR comments) and tell the story of a project to non-technical audiences (narrative mode).

## Context Files (Standards to Follow)
- /home/retroporter/.config/opencode/context/core/standards/code-quality.md (MANDATORY)
- /home/retroporter/.config/opencode/context/core/standards/test-coverage.md

## Reference Files (Source Material to Look At)
- core/ghost/preventive.py — Pre-write ghost checking (reused for PR diff analysis)
- core/ghost/pattern_matcher.py — Decision-diff matching (reused for PR context)
- core/decision_tree.py — Decision relationships (ancestors/descendants for context injection)
- core/knowledge_decay.py — Confidence scoring (used for decision relevance weighting)
- core/impact/analysis.py — Impact scoring (used for priority ordering in PR comments)
- core/memory/manager.py — Memory storage (loads project memory)
- core/tropebook/web/server.py — Router mounting point
- core/standards/code-quality.md — Error handling checklist

## External Docs Fetched
(none — all dependencies are internal)

## Components

### 1. PR Bot Delivery Surface
**Files:** core/prbot/comment_builder.py, core/prbot/router.py
**Reuse:** ghost/preventive.py (check_diff_for_warnings), ghost/pattern_matcher.py (extract_keywords, match_decision_to_diff), decision_tree.py (get_ancestors/get_descendants), knowledge_decay.py (score_decision), impact/analysis.py (compute_impact_scores)
**API:** POST /api/memory/{project}/pr-comment — {diff: str, pr_title: str, pr_body: str} → PR comment text
**Error handling:** Result type; PRBotError, ValidationError
**Key:** Analyzes a PR diff against active decisions, builds a formatted comment with relevant decisions, ghost warnings, and context. This is a distribution channel — gets insights in front of developers at the moment of review.
**Output:** PRComment with: body (markdown), decisions_mentioned, ghost_warnings, relevance_score

### 2. Narrative Mode (Non-Technical Audience)
**Files:** core/narrative/story_builder.py, core/narrative/router.py
**Reuse:** decision_tree.py (timeline, chains), knowledge_decay.py (confidence tiers), impact/analysis.py (reversals, impact), memory/manager.py (load)
**API:** POST /api/memory/{project}/narrative — {audience: "investor"|"new_hire"|"pm"} → prose narrative
**Error handling:** Result type; NarrativeError, ValidationError
**Key:** Turns the decision graph + git history into prose: what was tried, what failed, why the current architecture looks the way it does. Multiple audience presets.
**Output:** NarrativeReport with: title, sections[], summary, audience, word_count

## Constraints
- All code follows code-quality.md: pure functions, <50 lines, composition, dependency injection
- Result type for business logic, domain exceptions at IO boundaries
- No silent failures, no bare except, every error path tested
- Pydantic validation at every API boundary
- Each feature in its own directory under core/
- Routers mounted in server.py
- Tests follow test-coverage.md: AAA pattern, >90% on business logic, >100% on public APIs
- Reuse existing functions
- Linux only, Python 3.12+, no Windows paths

## Exit Criteria
- [ ] All 2 features implemented with REST API endpoints
- [ ] All routers mounted in server.py
- [ ] All error handling follows code-quality.md
- [ ] Tests pass for all new code
- [ ] Existing 998 tests still pass
- [ ] UI updated with navigation entries
- [ ] Wishlist.md updated
