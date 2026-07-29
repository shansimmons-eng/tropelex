# Tropelex Design

**Persistent memory and learning system for AI agents and human collaborators.**

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                            Tropelex                                  │
├──────────────────────────────────────────────────────────────────────┤
│  Adapters          Core                         Storage              │
│  ┌─────────┐     ┌──────────┐                ┌──────────────┐       │
│  │ OpenCode│     │ Memory   │                │  memory/     │       │
│  │ Tropebook│    │ Manager  │                │  *.json       │       │
│  └─────────┘     │          │                └──────────────┘       │
│                  │ Context  │                ┌──────────────┐       │
│                  │ Compress │                │  Tropebook/  │       │
│                  │          │                │  citations   │       │
│                  │ Learner  │                │  graph       │       │
│                  ├──────────┤                └──────────────┘       │
│                  │ Git      │                ┌──────────────┐       │
│                  │ Decision │                │  replays/    │       │
│                  │ ADR      │                │  chains/     │       │
│                  │ Decay    │                │  skills/     │       │
│                  │ RAG      │                │  genealogy/  │       │
│                  │ Chains   │                └──────────────┘       │
│                  │ Skills   │                                       │
│                  ├──────────┤                                       │
│                  │ Webhooks │  ← POST /api/webhooks/git             │
│                  │ Sync     │  ← GET/POST /api/sync/*               │
│                  │ Plugins  │  ← HookRegistry + manifest loader     │
│                  │ Auth     │  ← JWT HS256 + RBAC middleware        │
│                  │ Collab   │  ← WebSocket /ws/{room_id}            │
│                  └──────────┘                                       │
└──────────────────────────────────────────────────────────────────────┘
```

## Core Components

### 1. Memory Manager (`core/memory/manager.py`)

**Purpose:** Stores project knowledge as JSON files, tracks decisions, preferences, and session history.

**Data Model:**
```json
{
  "project_name": "string",
  "created": "ISO timestamp",
  "last_updated": "ISO timestamp",
  "description": "string",
  "decisions": [{"timestamp": "", "decision": "", "context": "", "confidence": {"score": 0.8}}],
  "session_history": [{"date": "", "summary": ""}],
  "preferences": {"key": "value"},
  "patterns": [{"name": "category:name", "count": 0, "first_seen": "", "last_seen": ""}],
  "tech_stack": ["React", "TypeScript"],
  "friction_history": [{"timestamp": "", "score": 0.3, "signal_count": 5}]
}
```

**Key Methods:**
- `get_context_for_project(name)` → Generates context string for agent injection
- `record_decision(project, decision, context)` → Log a decision
- `inject_preferences(project, prefs)` → Update preferences
- `summarize_session(project, summary)` → Log session end
- `_modify_project_memory(project, mutate_fn)` → Atomic read-modify-write with file locking

**Security Features:**
- File locking via `fcntl.flock` for concurrent write protection
- Atomic memory operations to prevent race conditions

### 2. Context Compressor (`core/context-compressor/compressor.py`)

**Purpose:** Trims prompts on the fly while preserving signal.

**Strategies:**
1. Remove redundant whitespace/formatting
2. Truncate long code blocks to signatures
3. Collapse repeated patterns
4. Prioritize recent over historical
5. Dictionary-based compression (stop words, phrase remaps)

**Key Methods:**
- `compress(content, priority)` → Returns `CompressionResult`
- `extract_signatures(code)` → Keep type signatures, drop body
- `summarize_long_text(text)` → Keep first/last sentences

### 3. Pattern Learner (`core/learner/learner.py`)

**Purpose:** Analyzes sessions for patterns, suggests next steps.

**Key Methods:**
- `analyze_session(project, summary)` → Returns pattern updates
- `suggest_next_steps(project)` → Suggests likely next work

### 4. Git Integration (`core/git_integration.py`)

**Purpose:** Auto-extract decisions, rationale, and tech stack changes from git history.

**Key Methods:**
- `get_recent_commits(repo_path, limit)` → Recent commits with metadata
- `extract_deep_decisions(repo_path, commits)` → Deep analysis with diffs, rationale, dependency changes
- `sync_repo_to_memory(repo_path, project, memory_manager)` → Sync git data to memory
- `get_deep_repo_summary(repo_path)` → Work categories, structural changes, reverts
- `detect_tech_stack_changes(repo_path, previous)` → Detect added/removed technologies

**Analysis Features:**
- Commit body parsing for rationale extraction
- File classification (ui, backend, testing, devops, database, config)
- Dependency file diff parsing (requirements.txt, package.json, pyproject.toml)
- Revert chain detection
- Structural change detection (new modules, migrations, tests)

### 5. Decision Tree (`core/decision_tree.py`)

**Purpose:** Builds a graph of decisions with relationships to track evolution and rationale.

**Relationship Types:**
- `supersedes` — A replaces/overrides B
- `caused_by` — A happened because of B
- `related_to` — A and B are thematically similar
- `reverts` — A reverts B
- `depends_on` — A requires B to be valid
- `evolves` — A is a refinement of B

**Key Methods:**
- `DecisionTree.from_decisions(decisions)` → Auto-detects relationships via keyword overlap
- `get_timeline()` → Sorted decisions with relationship info
- `get_chains()` → Sequences where A caused B caused C
- `get_ancestors(decision_id)` → Walk backwards through rationale chain
- `get_descendants(decision_id)` → Walk forwards to see what followed

### 6. Knowledge Decay (`core/knowledge_decay.py`)

**Purpose:** Time-based reliability scoring. Decisions lose confidence over age, gain it from references.

**Scoring Formula:**
```
score = (base_decay + reference_boost) * contradiction_penalty
```
- Base decay: exponential with configurable half-life (default 90 days)
- Reference boost: logarithmic, caps at 2x (from re-references)
- Contraction penalty: each contradiction halves confidence

**Tiers:** high (≥0.8), medium (≥0.5), low (≥0.2), stale (<0.2)

### 7. Living ADRs (`core/adr_generator.py`)

**Purpose:** Auto-generates Architecture Decision Records from project memory.

**Formats:**
- **Nygard** — Michael Nygard's original format (Status/Context/Decision)
- **MADR** — Markdown Any Decision Records (with metadata table)
- **Tropelex** — Enhanced format with decision tree lineage, confidence scores

### 8. Session Replay (`core/session_replay.py`)

**Purpose:** Tracks structured diffs of memory changes per session.

**Key Methods:**
- `record_session()` → Saves before/after snapshots + structured diff
- `get_sessions()` → List recent sessions
- `rollback_session()` → Restore memory to before a session
- `get_weekly_summary()` → What changed this week

### 9. Memory RAG & Cross-Pollination (`core/rag.py`)

**Purpose:** Semantic retrieval from memory + surface solutions from similar projects.

**Key Classes:**
- `MemoryRAG` → Retrieves relevant decisions, sessions, captures by keyword matching
- `CrossPollinator` → Finds transferable knowledge from projects with overlapping tech stacks

### 10. Agent Skills & Prompt Genealogy (`core/agent_skills.py`)

**Purpose:** Track agent proficiency and compression strategy effectiveness.

**AgentSkillGraph:**
- Records session outcomes per category (success/partial/failure)
- Scores proficiency: expert (≥0.9), proficient (≥0.7), competent (≥0.5), learning (≥0.3), novice

**PromptGenealogy:**
- Records compression events with strategy and ratio
- Tracks outcomes (good/rephrased/failed)
- Ranks strategies by effectiveness

### 12. Tropebook (`core/tropebook/`)

**Purpose:** Research knowledge base for storing links, summaries, and relationships.

**Components:**

#### Tropebook Core (`ropebook.py`)
```python
class Citation:
    title: str
    url: str
    summary: str
    tags: List[str]
    entities: List[str]
    relationships: List[str]
    source_type: SourceType  # brave_search, google_deep_research, manual, scraped, imported

class KnowledgeGraph:
    nodes: Dict[str, dict]
    edges: List[Dict]  # from, to, relationship, weight
```

**Storage Files:**
- `citations.json` - All citations
- `graph.json` - Knowledge graph edges
- `index.json` - Fast lookup indexes (by_url, by_tag, by_entity, by_source)

#### Research Tool (`research.py`)
- **BraveSearch** - Brave API with free DuckDuckGo fallback
- **WebScraper** - HTML content extraction
- **ResearchTool** - High-level research orchestration

#### Deep Research Importer (`deep_research.py`)
Parses and imports:
- Google Deep Research outputs
- NotebookLM exports
- Markdown research documents

#### Web Interface (`web/server.py`)
FastAPI server with:
- REST API (`/api/citations`, `/api/search`, `/api/research`, etc.)
- Jinja2 templates
- Vanilla JS frontend
- Dark theme UI

**Run:** `python -m core.tropebook.web.server` → `http://localhost:8766`

#### CLI (`cli.py`)
```bash
python -m core.tropebook.cli add "Title" "url" "summary"
python -m core.tropebook.cli search "query"
python -m core.tropebook.cli import file.json
python -m core.tropebook.cli stats
python -m core.tropebook.cli link url1 url2 relationship
```

### 18. Compression Dictionary (`core/compression/dictionary.py`)

**Stop Words:** 100+ common words (the, a, and, or, etc.)

**Phrase Remaps:** 40+ verbose → compact mappings
- "i would like to" → "i want"
- "could you please" → "please"
- "for the purpose of" → "to"

**Meta Commands:** Inline compression directives
- `//!` - stop word strip
- `>>` - compress whitespace
- `??` - dedupe
- `@@` - truncate_to
- `<<<` - keep recent
- `>>>` - keep all

**Compact Patterns:** Regex-based filler word removal (just, actually, basically, etc.)

### 19. Safety & Alignment Framework (`core/tropebook/web/server.py`)

**Purpose:** Risk classification, review workflow, alignment/governance scoring, and tamper-evidence for the decision graph — see [`SAFETY.md`](SAFETY.md) for the broader framing.

**Components:**
- **Safety Metadata** — `risk_level`, `reversibility`, `affected_systems`, `safety_category`, `requires_review` attached to any decision at creation
- **Safety Dashboard** — aggregated risk stats, trend time-series, system exposure (`/safety-stats`, `/safety-dashboard`, `/safety-trend`)
- **Decision Impact** — dependency graph + risk propagation, per-decision and system-wide (`/decision-impact`)
- **Safety Review Workflow** — pending queue, approve/reject, reviewer accountability (`/reviews/*`, `/decisions/{id}/review|approve|reject`)
- **Alignment & Governance** — 5-category alignment scoring, organizational-values check, drift detection, corrigibility tracking, EU AI Act / NIST / ISO 42001 compliance reports (`/alignment/*`, `/governance/*`, `/compliance/report`)
- **Fairness, Accountability, Robustness, Transparency** — bias audit, reviewer accountability, single-point-of-failure detection, human-readable reports (`/fairness/audit`, `/accountability/report`, `/robustness/test`, `/transparency/report`)
- **Provenance & Integrity** — cryptographic hash chain of decision history, hash/timestamp verification, tamper detection, immutable security audit log (`/provenance/chain`, `/integrity/verify`, `/tamper-detection`, `/security/audit-log`)
- **Decision Versioning** — version snapshots and rollback (`/decisions/{id}/version|versions|rollback/{v}`)
- **Synthetic Data Policy** — EU AI Act Art. 10 & 50 "nutritional label" for synthetic datasets: fidelity, privacy (ε/δ), bias audit, adversarial testing, blocking-gate compliance check (`/synthetic-data-policies*`)

**Architecture note:** unlike every other feature in this file, this one has no dedicated `core/<name>/` module — it's implemented inline in `web/server.py` (~3,200 lines). Every other feature here self-mounts a router from its own subpackage; this is the one exception and a candidate for extraction into `core/safety/` + `core/governance/` to match the rest of the codebase.

**Tests:** `tests/test_safety_features.py`, `tests/test_alignment_governance.py`, `tests/test_synthetic_data_policy.py`, `tests/test_far_cais_sff.py`

### 13. Adapters (`adapters/`)

#### OpenCode Adapter (`opencode.py`)
Primary integration for OpenCode agent.

```python
adapter = TropelexAdapter()
context = adapter.get_context_for_project("my-project")  # Uses handoff packets
adapter.record_decision("my-project", "Used X", "Because Y")
adapter.inject_preferences("my-project", {"ui": "mobile-first"})
adapter.summarize_session("my-project", session_summary)  # Also runs friction mining
```

**Features:**
- Role-aware context bundles via `build_handoff_packet()`
- Cross-project knowledge briefing via `get_cross_project_briefing()`
- Automatic friction mining on session end
- Importlib fix for hyphenated module names

#### Tropebook Adapter (`tropebook_adapter.py`)
Tropelex integration with Tropebook research capabilities.

### 14. Background Scheduler (`core/scheduler.py`)

**Purpose:** Automatic periodic tasks with error recovery.

**Tasks:**
- Research feeds: hourly
- Ghost decision scans: every 6 hours
- Stale decision checks: every 12 hours
- Slack alerts on feed errors

**Integration:** Runs as asyncio task in FastAPI lifespan.

### 15. Deep Research (`core/last30days/`)

**Purpose:** Multi-source research engine that searches Reddit, X, YouTube, GitHub, HackerNews, Polymarket, and web grounding in parallel, then synthesizes findings into a narrative brief with inline source citations.

**Architecture:**
- The engine (`last30days.py`) runs as a subprocess with 60+ source modules in `lib/`
- The synthesis driver (`synthesize_run.py`) runs the pipeline once in-process, then calls an OpenAI-compatible LLM to write the research brief following a strict "voice contract" (bold-lead paragraphs, `[source]` tags, KEY PATTERNS list)
- The runner (`runner.py`) wraps both as subprocesses, bridges `BRAVE_SEARCH_API_KEY` → `BRAVE_API_KEY`, and returns HTML output
- Feeds can use `research_provider: "deep_research"` to route through the engine instead of BraveSearch

**LLM Provider Priority:** OpenAI → xAI → OpenRouter (auto-detected from env vars)

**Source Availability:**
| Source | Key Required | Notes |
|---|---|---|
| HackerNews | No | Algolia API (free) |
| GitHub | No | Public API (free, rate-limited) |
| Polymarket | No | Gamma API (free) |
| YouTube | No | yt-dlp (free, must be installed) |
| Reddit | Optional | Without key: keyless RSS (limited). With ScrapeCreators: full access |
| X/Twitter | Optional | xAI API key, or browser cookies (AUTH_TOKEN + CT0) |
| Bluesky | Yes | BSKY_HANDLE + BSKY_APP_PASSWORD |
| TikTok/Instagram/Threads | Yes | SCRAPECREATORS_API_KEY |
| Web grounding | Optional | BRAVE_API_KEY, EXA_API_KEY, SERPER_API_KEY, or PARALLEL_API_KEY |

**Key Methods:**
- `runner.run_query(query, emit="html")` → HTML report via synthesis driver
- `runner.run_query_and_extract_citations(query)` → HTML + citation URL list
- `POST /api/last30days/query` → ad-hoc deep research endpoint

### 16. Emacs Integration (`emacs/tropelex-capture.el`)

**Purpose:** Capture decisions and friction signals directly from Emacs.

**Components:**
- `tropelex-capture-decision` — interactive command, auto-detects file/project/mode context
- `tropelex-capture-region` — capture selected code as decision context
- `tropelex-friction-scan` — scan buffer for friction signals
- `tropelex--track-save` — `after-save-hook` that detects rapid save patterns (5+ in 5 seconds)
- `tropelex--compilation-finished` — `compilation-finish-functions` hook that auto-scans compilation output for friction

**Project Detection:** projectile → `vc-root-dir` → directory name fallback

**Dependencies:** None — uses only built-in `json.el` and `url.el` (synchronous HTTP to localhost)

### 17. Security Features

**SSRF Protection** (`core/tropebook/research.py`):
- URL scheme validation (http/https only)
- Private IP blocking (RFC 1918, loopback, link-local)
- Bounded scrape depth to prevent cascading requests

**File Locking** (`core/embeddings.py`, `core/federation/router.py`, `core/tropebook/alert_router.py`):
- `fcntl.flock` for concurrent write protection
- Atomic memory writes via `_modify_project_memory()`

**Path Traversal Protection** (`core/webhooks/router.py`):
- Regex sanitization of repo names
- Resolved path validation under base directory

**Fixed — cross-test state leak:** `_rate_limits` in `web/server.py` (the rate limiter's in-memory, per-IP request log) is module-level and was never reset between tests. FastAPI's `TestClient` reports its host as `"testclient"`, which the middleware does *not* exempt (only `127.0.0.1`/`::1` are), so every test file's requests accumulated in the same dict entry within the 60s window. Once the cumulative count crossed `RATE_LIMIT_MAX` (120), later-running files — `test_security.py`, `test_synthetic_data_policy.py` — started getting 429s on unrelated requests. Fixed with an autouse `_reset_rate_limits` fixture in `tests/conftest.py` that clears `_rate_limits` before/after every test. All 1408 tests pass together as of this fix.

## Data Flow

```
User/Agent Input
      │
      ▼
┌─────────────────┐
│  Tropelex       │
│  Adapter        │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│                    Core Components                      │
│  ┌──────────┐  ┌────────────────┐  ┌────────────────┐  │
│  │ Memory   │  │ Context        │  │ Git            │  │
│  │ Manager  │  │ Compressor     │  │ Integration    │  │
│  └────┬─────┘  └───────┬────────┘  └───────┬────────┘  │
│       │                │                    │           │
│       ▼                ▼                    ▼           │
│  ┌──────────┐  ┌────────────────┐  ┌────────────────┐  │
│  │ Learner  │  │ Compression    │  │ Decision Tree  │  │
│  │          │  │ Dictionary     │  │ ADR Generator  │  │
│  └────┬─────┘  └────────────────┘  │ Knowledge Decay│  │
│       │                            │ Session Replay │  │
│       ▼                            │ RAG + CrossPol │  │
│  ┌──────────┐                      │ Agent Skills   │  │
│  │ Patterns │                      └────────────────┘  │
│  └──────────┘                                          │
└─────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│                    Storage                              │
│  memory/*.json  │  tropebook/  │  replays/  │  chains/  │
│  skills/  │  genealogy/  │  embeddings/                 │
└─────────────────────────────────────────────────────────┘
```

## Integration Patterns

### For AI Agents
1. Add `~/Tropelex/` to agent context
2. Initialize adapter at session start
3. Record decisions during work
4. Summarize at session end
5. Inject context on new sessions

### For Humans
1. Use web UI for browsing/searching citations
2. Use CLI for quick operations
3. Import research from Deep Research exports
4. Build knowledge graphs over time

## Configuration

### Environment Variables
- `BRAVE_API_KEY` - Optional Brave Search API key (falls back to DuckDuckGo)

### Project Memory Location
Default: `~/Tropelex/memory/`

### Tropebook Storage Location
Default: `~/Tropelex/memory/tropebook/`

## File Structure

```
Tropelex/
├── core/
│   ├── memory/              # Project knowledge storage
│   │   └── manager.py
│   ├── context-compressor/  # Prompt compression
│   │   └── compressor.py
│   ├── compression/         # Dictionary-based compression
│   │   └── dictionary.py
│   ├── learner/             # Pattern tracking
│   │   └── learner.py
│   ├── git_integration.py   # Git-aware memory
│   ├── decision_tree.py     # Decision graph
│   ├── adr_generator.py     # Living ADRs
│   ├── session_replay.py    # Session diffs + rollback
│   ├── knowledge_decay.py   # Confidence scoring
│   ├── rag.py               # Memory RAG + Cross-Pollination
│   ├── agent_skills.py      # Agent skills + Prompt genealogy
│   ├── embeddings.py        # Vector embeddings
│   ├── research_pipeline.py # Auto-research pipeline
│   ├── llm.py               # LLM backend abstraction
│   ├── friction/            # Friction mining
│   │   ├── miner.py         # Signal detection, scoring, zones
│   │   └── router.py        # Friction scan API
│   ├── last30days/          # Deep research engine
│   │   ├── last30days.py    # Multi-source research engine
│   │   ├── synthesize_run.py # Pipeline + LLM synthesis + HTML render
│   │   ├── runner.py        # Subprocess wrapper
│   │   └── lib/             # 60+ source modules, rendering, planning
│   └── tropebook/            # Research knowledge base
│       ├── __init__.py
│       ├── tropebook.py       # Core KB + graph
│       ├── research.py       # Search + scraping
│       ├── research_feeds.py # Scheduled feed monitoring
│       ├── scheduler.py      # FeedScheduler (run/tick/search)
│       ├── deep_research.py  # Import tools
│       ├── feed_intelligence.py # Feed trend detection
│       ├── cli.py            # CLI
│       └── web/              # Web interface
│           ├── server.py     # FastAPI (80+ endpoints, rate limiting)
│           ├── static/
│           └── templates/
├── emacs/                   # Emacs integration
│   └── tropelex-capture.el  # Decision capture, friction scanning
├── adapters/                 # Agent integrations
│   ├── __init__.py
│   └── opencode.py
├── scripts/                  # CLI tools
│   ├── init_project.py
│   ├── git_sync.py
│   └── feed_cli.py           # Feed management CLI
├── UI/                        # Web interfaces
│   ├── animated_tropebook_dashboard/code.html
│   └── prompt-compressor.html
├── memory/                   # Persistent storage (gitignored)
├── tests/                    # 1408 tests, all passing
├── requirements.txt
├── README.md
├── AGENTS.md                 # Agent guidance
├── design.md                 # This file
└── wishlist.md               # Future feature roadmap
```


## Anti-Patterns

### Don't Skip Updates Because:
- "This session was small" — small sessions still teach patterns
- "I'll remember it" — you won't, but Tropelex will
- "It's too much overhead" — one function call at session end is not overhead

## Future Considerations

See `wishlist.md` for detailed roadmap including:
- Versioned Memory Snapshots
- Memory Health Dashboard
- Knowledge Graph Visualization
- Cross-Project Learning Automation
- Decision Impact Analysis
- Research Feed Intelligence
- Collaborative Memory
- Memory Backup & Restore
- Research Feed Alerts
- Memory Search API (semantic)
- Knowledge Decay Prevention
- Memory Analytics
- Prompt Effectiveness Tracking
- Session Replay with AI Analysis

### Quick Wins (Implemented)
- [x] **Webhook-based git hooks** — POST /api/webhooks/git with HMAC-SHA256 verification, idempotency, GitHub/GitLab support
- [x] **Sync across devices** — GET/POST /api/sync/* for gzip-compressed memory export/import with schema validation
- [x] **Plugin system** — HookRegistry with before/after hooks, manifest-based discovery, example plugin
- [x] **VS Code extension** — TypeScript extension with TreeView, Webview panel, and commands
- [x] **Multi-user support** — JWT auth (HS256), User model with RBAC roles, FastAPI auth middleware
- [x] **Real-time collaboration** — WebSocket /ws/{room_id} with room-based broadcasting and heartbeat
- [x] **Background scheduler** — Automatic periodic tasks (feeds, ghost scans, stale checks)
- [x] **SSRF protection** — URL scheme validation, private IP blocking in web scraper
- [x] **File locking** — fcntl.flock on embeddings, federation, alert storage
- [x] **Atomic memory writes** — Race condition prevention in MemoryManager

## UI
### Pallette

Accents
-#a580fa
-#8098fa
-#80d5fa
-#98fa80

Background
-#010515
-#ffffff
