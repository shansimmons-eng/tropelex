# Tropelex Design

**Persistent memory and learning system for AI agents and human collaborators.**

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                         Tropelex                             │
├─────────────────────────────────────────────────────────────┤
│  Adapters          Core                    Storage           │
│  ┌─────────┐     ┌──────────┐           ┌──────────────┐     │
│  │ OpenCode│     │ Memory   │           │  memory/     │     │
│  │ Tropebook│    │ Manager  │           │  *.json       │     │
│  └─────────┘     │          │           └──────────────┘     │
│                  │ Context  │           ┌──────────────┐     │
│                  │ Compress │           │  Tropebook/  │     │
│                  │          │           │  citations   │     │
│                  │ Learner  │           │  graph       │     │
│                  └──────────┘           └──────────────┘     │
└─────────────────────────────────────────────────────────────┘
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

### 4. Tropebook (`core/tropebook/`)

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

**Run:** `python -m core.tropebook.web.server` → `http://localhost:8765`

#### CLI (`cli.py`)
```bash
python -m core.tropebook.cli add "Title" "url" "summary"
python -m core.tropebook.cli search "query"
python -m core.tropebook.cli import file.json
python -m core.tropebook.cli stats
python -m core.tropebook.cli link url1 url2 relationship
```

### 5. Compression Dictionary (`core/compression/dictionary.py`)

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

### 6. Adapters (`adapters/`)

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
┌─────────────────────────────────────┐
│         Core Components             │
│  ┌──────────┐  ┌────────────────┐  │
│  │ Memory   │  │ Context        │  │
│  │ Manager  │  │ Compressor     │  │
│  └────┬─────┘  └───────┬────────┘  │
│       │                │            │
│       ▼                ▼            │
│  ┌──────────┐  ┌────────────────┐  │
│  │ Learner  │  │ Compression    │  │
│  │          │  │ Dictionary     │  │
│  └──────────┘  └────────────────┘  │
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│         Storage                     │
│  memory/*.json                      │
│  memory/tropebook/*.json            │
└─────────────────────────────────────┘
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
│   └── tropebook/            # Research knowledge base
│       ├── __init__.py
│       ├── ropebook.py       # Core KB + graph
│       ├── research.py       # Search + scraping
│       ├── deep_research.py  # Import tools
│       ├── cli.py            # CLI
│       ├── web/              # Web interface
│       │   ├── server.py
│       │   ├── static/
│       │   └── templates/
│       └── adapters/
│           └── tropebook_adapter.py
├── adapters/                 # Agent integrations
│   ├── __init__.py
│   └── opencode.py
├── memory/                   # Persistent storage
├── plugins/                  # Skill loaders
├── requirements.txt
├── README.md
├── AGENTS.md                # Agent guidance
└── design.md               # This file
```

## Anti-Patterns

### Don't Skip Updates Because:
- "This session was small" — small sessions still teach patterns
- "I'll remember it" — you won't, but Tropelex will
- "It's too much overhead" — one function call at session end is not overhead

## Future Considerations

- [ ] Vector embeddings for semantic search
- [ ] TUI interface (blessed/textual)
- [ ] VS Code extension
- [ ] Multi-user support
- [ ] Sync across devices
- [ ] Plugin system for custom integrations