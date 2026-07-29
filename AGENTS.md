# AGENTS.md for Tropelex

**⚠️ LINUX ONLY PROJECT - NO WINDOWS PATHS OR COMMANDS ⚠️**

This is a Linux-native project. All paths must use forward slashes (`/`). 
All commands must run in WSL (`cd ~/tropelex-test` or `cd ~/Tropelex`).
Never use Windows paths (e.g., `\\wsl$`, `C:\`, `\` separators).
Never use Windows commands or Git Bash. Use native Linux terminals only.

---

## Tropelex Integration

**CRITICAL:** At session start, immediately run `/tropelex-show-context` to load accumulated project memory.

Tropelex is a persistent memory system that stores:
- Architectural decisions and rationale
- Session summaries and learned patterns  
- Tech stack choices and preferences

**Commands:**
- `/tropelex-context` - View project memory summary
- `/tropelex-show-context` - Load project memory (run first!)
- `/tropelex-record-decision <what> | <why>` - Save decisions
- `/tropelex-up <description> | <tech-stack>` - Update/create project
- `/tropelex-end-session <summary>` - End session + learn patterns

**Workflow:**
1. Start session → run `/tropelex-context`
2. Work on tasks → use `/tropelex-record-decision` for key choices
3. Update project → `/tropelex-up description | tech-stack`
4. End session → run `/tropelex-end-session` to trigger learning

---

## Tropelex Overview

Tropelex accumulates knowledge across sessions so agents don't start from scratch. See [`SAFETY.md`](SAFETY.md) for how the same mechanisms double as safety/audit infrastructure (drift detection, contradiction surfacing, agent handoff, forensic time-travel).

## Core Components

### Memory Manager (`core/memory/manager.py`)
- Stores project knowledge as JSON files in `memory/`
- Tracks decisions, preferences, session history
- `get_context_for_project(name)` → generates context string for agent injection

### Context Compressor (`core/context-compressor/compressor.py`)
- Trims prompts while preserving signal
- `compress(content, priority)` → returns compressed content
- `extract_signatures(code)` → keeps type signatures, drops body
- `summarize_long_text(text)` → keeps first/last sentences

### Pattern Learner (`core/learner/learner.py`)
- Analyzes sessions for patterns
- `analyze_session(project, summary)` → returns pattern updates
- `suggest_next_steps(project)` → suggests likely next work

### Git Integration (`core/git_integration.py`)
- Auto-extracts decisions from conventional commits
- Deep analysis: parses diffs, detects rationale, dependency changes, revert chains
- `sync_repo_to_memory(repo_path, project, mm)` → syncs git history to memory
- `get_deep_repo_summary(repo_path)` → work categories, structural changes

### Decision Tree (`core/decision_tree.py`)
- Builds graph of decisions with relationships (supersedes, caused_by, related_to, reverts)
- `DecisionTree.from_decisions(decisions)` → auto-detects relationships
- `get_timeline()`, `get_chains()`, `get_ancestors()`, `get_descendants()`

### Knowledge Decay (`core/knowledge_decay.py`)
- Time-based confidence scoring for decisions
- Exponential decay with reference boosts and contradiction penalties
- `score_decisions(decisions)` → each decision gets score + tier
- `get_stale_decisions(decisions)` → finds decisions needing review

### Living ADRs (`core/adr_generator.py`)
- Auto-generates Architecture Decision Records from memory
- Three formats: Nygard, MADR, Tropelex (enhanced with decision tree context)
- `generate_adrs_for_project(memory, format)` → list of ADR markdown files

### Session Replay (`core/session_replay.py`)
- Snapshots memory state per session, computes structured diffs
- `record_session()` → saves before/after snapshots + changes
- `rollback_session()` → restores memory to before a session
- `get_weekly_summary()` → what changed this week

### RAG & Cross-Pollination (`core/rag.py`)
- `MemoryRAG.retrieve(project, query)` → semantic retrieval from memory
- `CrossPollinator.find_transferable_knowledge(project)` → solutions from similar projects
- `CrossPollinator.suggest_approaches(project, problem)` → cross-project approaches

### Research Chains (`core/research_chains.py`)
- Multi-hop knowledge building: search → find gaps → search again → link
- `ResearchChainManager.auto_research(project, goal)` → automated chain
- Stores chains with steps, findings, links, synthesis

### Agent Skills & Prompt Genealogy (`core/agent_skills.py`)
- `AgentSkillGraph` → tracks proficiency per category (ui, backend, testing, etc.)
- `PromptGenealogy` → tracks which compression strategies produce best outcomes
- Both learn from session outcomes over time

### OpenCode Adapter (`adapters/opencode.py`)
- Primary integration point for OpenCode agent
- `generate_session_prompt(project_name)` → creates Tropelex context block

### Safety & Alignment Framework (`core/tropebook/web/server.py`)
- Safety metadata (risk_level, reversibility, affected_systems, safety_category) attachable to any decision
- Safety Dashboard, Review Workflow, Alignment/Governance scoring, Provenance/Integrity chain, Synthetic Data Policy compliance gates
- See [`SAFETY.md`](SAFETY.md) for the full framing and [`design.md`](design.md) §19 for the API surface
- **Note for agents touching this area:** unlike every other `core/` feature, this one is implemented inline in `web/server.py` rather than its own module — don't assume `core/safety/` exists

## Usage

At start of session:
```python
from adapters.opencode import TropelexAdapter
adapter = TropelexAdapter()
context = adapter.get_context_for_project("sovereign-mirror")
# Inject context into system prompt
```

During session:
```python
adapter.record_decision("sovereign-mirror", "Used Application Passwords", "WP auth needed X-API-Key fallback")
adapter.inject_preferences("sovereign-mirror", {"ui": "mobile-first", "verbose": True})
```

At end of session:
```python
adapter.summarize_session("sovereign-mirror", session_summary_text)
```

## Project Memory Files

Located in `memory/*.json` — one per project. Structure:
```json
{
  "project_name": "sovereign-mirror",
  "created": "2026-05-18T...",
  "last_updated": "...",
  "description": "",
  "decisions": [{"timestamp": "...", "decision": "...", "context": "..."}],
  "session_history": [],
  "preferences": {"ui": "mobile-first"},
  "patterns": [{"name": "category:ui", "count": 5, "first_seen": "...", "last_seen": "..."}],
  "tech_stack": ["React", "Three.js", "TypeScript"]
}
```

## Anti-Rationalization

Do not skip Tropelex updates because:
- "This session was small" — small sessions still teach patterns
- "I'll remember it" — you won't, but Tropelex will
- "It's too much overhead" — one function call at session end is not overhead

## Testing Mandate

**Every new feature, bug fix, or API endpoint MUST have tests before it is considered done.**

Rules:
1. **New endpoint** → add tests in `tests/` using `TestClient` + `monkeypatch` (see `tests/test_compaction.py` for pattern)
2. **New model field** → add roundtrip, validation, and default tests
3. **Bug fix** → add a regression test that fails without the fix
4. **New file/module** → create a corresponding `tests/test_<module>.py`
5. **No feature is complete until `pytest tests/ -x -q` passes with the new tests included**

Exception: last30days engine tests must be mocked (use `@pytest.mark.last30days` marker) to avoid consuming API tokens. Run `pytest -m last30days` explicitly when needed.

Do not skip tests because:
- "It's just a small change" — small changes break things too
- "I'll add tests later" — you won't
- "The existing tests cover it" — they don't cover the new code
- "It's hard to test" — mock the hard parts, test the logic

## Tropebook (`core/tropebook/`)

Research knowledge base for storing links, summaries, and relationships.

### Components
- `ropebook.py` - Core knowledge base with graph storage
- `research.py` - Web search (Brave API or DuckDuckGo fallback) + scraper
- `deep_research.py` - Google Deep Research / NotebookLM import parser
- `cli.py` - Command-line interface
- `adapters/tropebook_adapter.py` - Tropelex integration

### Usage
```python
from core.tropebook import Tropebook, create_researcher, create_importer

# Knowledge base
tb = Tropebook()
cid = tb.add("Python Docs", "https://docs.python.org", "Official docs")
related = tb.search("tutorials")
tb.link(cid1, cid2, "related_to")

# Research tool (free - uses DuckDuckGo if no Brave API key)
researcher = create_researcher()  # or create_researcher(api_key="...")
results = researcher.research("machine learning transformers")

# Import from Google Deep Research / NotebookLM
importer = create_importer(tb)
count = importer.import_file("research_export.json")
```

### Storage
- `memory/tropebook/citations.json` - All citations
- `memory/tropebook/graph.json` - Knowledge graph edges
- `memory/tropebook/index.json` - Fast lookup indexes

### Web Interface
Run the web server:
```bash
python -m core.tropebook.web.server
# Opens at http://localhost:8766
```

## Deep Research (`core/last30days/`)

Multi-source research engine that searches Reddit, X, YouTube, GitHub, HackerNews, Polymarket, and web grounding in parallel, then synthesizes findings into a narrative brief.

### Components
- `last30days.py` — The main research engine (60+ source modules in `lib/`)
- `synthesize_run.py` — Pipeline + LLM synthesis + HTML render in one pass
- `runner.py` — Subprocess wrapper (bridges BRAVE_SEARCH_API_KEY → BRAVE_API_KEY)

### Usage

**Ad-hoc research via API:**
```bash
curl -X POST http://localhost:8766/api/last30days/query \
  -H 'Content-Type: application/json' \
  -d '{"query":"LLM agent architectures","emit":"html"}'
```

**As a feed provider:**
```bash
# Create a deep research feed
curl -X POST http://localhost:8766/api/research-feeds \
  -H 'Content-Type: application/json' \
  -d '{"name":"AI Trends","query":"local LLM agents","interval":"weekly","research_provider":"deep_research"}'
```

**Via the UI:** Navigate to Deep Research section or select "Deep Research" as provider when creating a feed.

### Latency
Deep research takes 1–3 minutes per query (multi-source parallel search + LLM synthesis). This is expected. The UI shows a loading state during the request.

### Key Configuration
See `API_KEYS.md` for source keys. The engine degrades gracefully — missing sources are skipped. Free sources (HackerNews, GitHub, Polymarket, YouTube) work without any keys.

## Emacs Integration (`emacs/tropelex-capture.el`)

Capture decisions, friction signals, and git commits directly from Emacs.

### Setup
```elisp
(add-to-list 'load-path "~/Tropelex/emacs")
(require 'tropelex-capture)
(tropelex-capture-mode 1)
```

### Commands
- `C-c t c` — Capture a decision (auto-detects file, project, mode, code context)
- `C-c t r` — Capture region as decision context
- `C-c t f` — Scan buffer for friction signals
- `C-c t g` — Capture current HEAD commit as a decision
- `C-c t s` — Check server status
- `C-c t p` — Set project name

### Automatic Capture
- **Compilation errors** → auto-scan for friction when compilation fails
- **Rapid saves** → 5+ saves in 5 seconds triggers a friction signal
- **Git commits via Magit** → auto-capture decisions from commit messages (50+ chars)

### Code Context (LSP / treesit / which-function)
- Captures include current function name and type when available
- Uses eglot or lsp-mode for symbol info, falls back to treesit/which-function
- Set `tropelex-include-code-context` to nil to disable

### Project Detection
Auto-detects from: projectile → vc-root-dir → directory name fallback.

## Integration with OpenCode

Tropelex should auto-load when this directory is in context. Check for `~/Tropelex/` and use it to:
1. Generate session context
2. Record key decisions
3. Update patterns

If `~/Tropelex/` is not found, fall back to in-memory session state.