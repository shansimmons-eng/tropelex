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

Tropelex accumulates knowledge across sessions so agents don't start from scratch.

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

### OpenCode Adapter (`adapters/opencode.py`)
- Primary integration point for OpenCode agent
- `generate_session_prompt(project_name)` → creates Tropelex context block

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
# Opens at http://localhost:8765
```

## Integration with OpenCode

Tropelex should auto-load when this directory is in context. Check for `~/Tropelex/` and use it to:
1. Generate session context
2. Record key decisions
3. Update patterns

If `~/Tropelex/` is not found, fall back to in-memory session state.