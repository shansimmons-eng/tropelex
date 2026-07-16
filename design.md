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
  "decisions": [{"timestamp": "", "decision": "", "context": ""}],
  "session_history": [{"date": "", "summary": ""}],
  "preferences": {"key": "value"},
  "patterns": [{"name": "category:name", "count": 0, "first_seen": "", "last_seen": ""}],
  "tech_stack": ["React", "TypeScript"]
}
```

**Key Methods:**
- `get_context_for_project(name)` → Generates context string for agent injection
- `record_decision(project, decision, context)` → Log a decision
- `inject_preferences(project, prefs)` → Update preferences
- `summarize_session(project, summary)` → Log session end

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

### 10. Research Chains (`core/research_chains.py`)

**Purpose:** Multi-hop knowledge building — search → find gaps → search again → link → synthesize.

**Key Methods:**
- `ResearchChain(goal)` → Create a research investigation
- `add_step(query, findings, gaps)` → Record a research step
- `auto_research(project, goal)` → Automated multi-hop research

### 11. Agent Skills & Prompt Genealogy (`core/agent_skills.py`)

**Purpose:** Track agent proficiency and compression strategy effectiveness.

**AgentSkillGraph:**
- Records session outcomes per category (success/partial/failure)
- Scores proficiency: expert (≥0.9), proficient (≥0.7), competent (≥0.5), learning (≥0.3), novice

**PromptGenealogy:**
- Records compression events with strategy and ratio
- Tracks outcomes (good/rephrased/failed)
- Ranks strategies by effectiveness

### 12. Compression Dictionary (`core/compression/dictionary.py`)

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

### 12. Compression Dictionary (`core/compression/dictionary.py`)

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

### 13. Adapters (`adapters/`)

#### OpenCode Adapter (`opencode.py`)
Primary integration for OpenCode agent.

```python
adapter = TropelexAdapter()
context = adapter.get_context_for_project("my-project")
adapter.record_decision("my-project", "Used X", "Because Y")
adapter.inject_preferences("my-project", {"ui": "mobile-first"})
adapter.summarize_session("my-project", session_summary)
```

#### Tropebook Adapter (`tropebook_adapter.py`)
Tropelex integration with Tropebook research capabilities.

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
│   ├── research_chains.py   # Multi-hop research
│   ├── rag.py               # Memory RAG + Cross-Pollination
│   ├── agent_skills.py      # Agent skills + Prompt genealogy
│   ├── embeddings.py        # Vector embeddings
│   ├── research_pipeline.py # Auto-research pipeline
│   ├── llm.py               # LLM backend abstraction
│   └── tropebook/            # Research knowledge base
│       ├── __init__.py
│       ├── tropebook.py       # Core KB + graph
│       ├── research.py       # Search + scraping
│       ├── research_feeds.py # Scheduled feed monitoring
│       ├── scheduler.py      # FeedScheduler (run/tick/search)
│       ├── deep_research.py  # Import tools
│       ├── cli.py            # CLI
│       └── web/              # Web interface
│           ├── server.py     # FastAPI (80+ endpoints, rate limiting)
│           ├── static/
│           └── templates/
├── adapters/                 # Agent integrations
│   ├── __init__.py
│   └── opencode.py
├── scripts/                  # CLI tools
│   ├── init_project.py
│   ├── git_sync.py
│   └── feed_cli.py           # Feed management CLI
├── core/
│   ├── webhooks/              # Git webhook auto-sync (Phase 1)
│   │   ├── signature.py       # HMAC-SHA256 verification
│   │   ├── idempotency.py     # Duplicate event prevention
│   │   └── router.py          # POST /api/webhooks/git
│   ├── sync/                  # Cross-device export/import (Phase 1)
│   │   ├── exporter.py        # Gzip-compressed memory export
│   │   ├── importer.py        # Import with schema validation
│   │   └── router.py          # GET/POST /api/sync/*
│   ├── plugins/               # Plugin system (Phase 2)
│   │   ├── loader.py          # Manifest discovery + validation
│   │   └── hooks.py           # HookRegistry (before/after hooks)
│   ├── auth/                  # Multi-user auth (Phase 3)
│   │   ├── jwt_service.py     # JWT HS256 generate/validate
│   │   ├── models.py          # User model, Role enum, UserStore
│   │   └── middleware.py       # FastAPI auth dependencies
│   ├── collaboration/         # Real-time updates (Phase 3)
│   │   ├── connection_manager.py  # Room-based WebSocket tracking
│   │   ├── router.py          # WebSocket /ws/{room_id}
│   │   └── broadcast.py       # Memory change notifications
│   └── ...                    # (existing modules)
├── plugins/
│   ├── example/               # Example plugin
│   │   ├── plugin.json
│   │   └── plugin.py          # register(registry) entry point
│   └── ...
├── vscode-tropelex/           # VS Code extension (Phase 2)
│   ├── package.json
│   ├── tsconfig.json
│   └── src/
│       ├── extension.ts
│       ├── memoryTreeProvider.ts
│       └── memoryWebviewPanel.ts
├── UI/                        # Web interfaces
│   ├── animated_tropebook_dashboard/code.html
│   └── prompt-compressor.html
├── memory/                   # Persistent storage (gitignored)
├── plugins/                  # Skill loaders
├── tests/                    # 495 tests
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
