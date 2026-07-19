# Tropelex

**Persistent memory and learning system for AI agents.**

Tropelex accumulates knowledge across projects — decisions, patterns, preferences, research — so sessions don't start from scratch. It grows smarter with use.

---

## What it does

| Component | Purpose |
|---|---|
| **Memory Manager** | Stores project knowledge as JSON — decisions, preferences, session history |
| **Pattern Learner** | Analyzes sessions to detect recurring themes and suggest next steps |
| **Context Compressor** | Strips filler from prompts using AI (OpenAI) or dictionary-based rules |
| **Tropebook** | Research knowledge base — store, search, link citations with a graph |
| **Agent Pipeline** | 3-stage prompt prep: compress → context check → structure |
| **Prompt Hijacker** | One-click AI compression for any prompt before sending to an AI |
| **Git Integration** | Auto-extract decisions, rationale, and tech stack changes from commits |
| **Decision Trees** | Graph of decision evolution — tracks what caused what, reverts, relationships |
| **Living ADRs** | Auto-generate Architecture Decision Records from memory data |
| **Session Replay** | Structured memory diffs per session — what changed, rollback support |
| **Knowledge Decay** | Time-based confidence scoring — decisions lose reliability over age |
| **Research Chains** | Multi-hop knowledge building — search → find gaps → search again → link |
| **Memory RAG** | Semantic retrieval from project memory at query time |
| **Cross-Pollination** | Surface solutions from similar projects with matching tech stacks |
| **Agent Skills** | Track what the agent has become proficient at per project |
| **Prompt Genealogy** | Track which compression strategies produce the best outcomes |
| **Research Feeds** | Scheduled monitoring with auto-ingest to citations |
| **Ghost Decisions** | Silent drift detection — code contradicts decisions without anyone saying so |
| **Explainable Memory** | Conversational "why do we...?" with full causal chain |
| **Agent Handoff Packets** | Role-aware context bundles for multi-agent workflows |
| **Decision Market** | Confidence bets, calibration tracking, leaderboard |
| **Memory Lens** | IDE inline annotations — GitLens but for decisions |
| **Slack Capture** | Bidirectional Slack integration for decision logging |
| **Time-Travel Debugger** | Memory snapshots as of any past date |
| **Contradiction Detection** | Actively scan for unresolved conflicting decisions |
| **Digital Twin Personas** | Synthesize readable persona summaries from agent proficiency |
| **Federated Benchmarking** | Opt-in, privacy-preserving cross-install statistics |
| **Memory Compaction** | Epoch summarization to prevent unbounded memory growth |
| **Friction Mining** | Implicit signal detection from conversation transcripts |
| **Preventive Ghost Checks** | Pre-write hook that checks diff against active decisions |
| **Rationale Corroboration** | Fact-check decision rationale against the live web |
| **PR Bot** | Deliver ghost decisions, contradictions as PR comments |
| **Narrative Mode** | Readable prose summaries for non-technical audiences |
| **Cost Ledger** | Per-decision token cost tracking and ROI scoring |
| **Predictive Prefetch** | Budget-aware context assembly prioritized by impact score |
| **Background Scheduler** | Automatic periodic tasks — feeds, ghost scans, stale checks |

---

## Requirements

- Python 3.10+
- `uv` (recommended) or `pip`
- OpenAI API key (for AI compression — optional, dictionary fallback available)
- Brave Search API key (optional — falls back to DuckDuckGo free)

---

## Installation

```bash
git clone https://github.com/yourusername/tropelex.git
cd tropelex

# With uv (recommended)
uv venv
uv pip install -r requirements.txt

# Or with pip
pip install -r requirements.txt
```

---

## Quick Start

### 1. Set your API key

Create a `.env` file in the project root:

```bash
OPENAI_API_KEY=sk-your-key-here
BRAVE_SEARCH_API_KEY=your-brave-key-here   # optional
```

Or set via environment:

```bash
export OPENAI_API_KEY=sk-your-key-here
```

### 2. Start the server

```bash
# With uv
uv run python -m core.tropebook.web.server

# Or with python
python -m core.tropebook.web.server
```

### 3. Open the UI

Visit **http://localhost:8766** in your browser.

### 4. (Optional) Use the Prompt Hijacker

Visit **http://localhost:8766/hijacker** — paste any verbose prompt and get it AI-compressed in one click.

---

## Web Interface

The dashboard has seven sections:

### Tropebook
Add, search, and manage research citations. Each citation can have tags, entities, and relationships to other citations.

- **Add Citation** — manually add a URL with title, summary, tags
- **Import** — import JSON from Google Deep Research / NotebookLM export
- **Search** — full-text search across titles and summaries
- **Sync** — refresh all data from the server

### Memory
Project-based persistent memory. Each project stores:
- Decisions (key choices made during development)
- Session history (what was worked on and when)
- Tech stack
- Preferences

### Patterns
Automatically detected patterns from session history. Shows what categories of work (UI, backend, bug fixes, etc.) appear most frequently, with AI-generated suggestions for next steps.

### Prompt Lab
3-stage prompt preprocessor:
1. **Compression** — AI strips filler, fixes typos, makes prompts imperative
2. **Context Check** — flags vague or missing context
3. **Structure** — formats output as TASK / CONSTRAINTS / CONTEXT

The final output is ready to paste into any AI assistant.

### Insights
Decision intelligence and knowledge analysis:
- **Decision Confidence** — time-based reliability scoring (decays with age, boosted by references)
- **Agent Proficiency** — tracks what the agent is good at per category (ui, backend, testing, etc.)
- **Decision Timeline** — every decision with source, confidence, rationale, and relationship tags
- **Decision Chains** — visualizes causal chains (A caused B caused C)
- **ADR Generation** — one-click Architecture Decision Records in Nygard, MADR, or Tropelex format
- **Session Replay** — structured memory diffs, rollback support
- **Cross-Project Knowledge** — finds transferable solutions from similar projects

### Git
Repository integration and deep analysis:
- **Summary** — tech stack detection, work category frequency, recent commits
- **Sync** — extract decisions from conventional commits
- **Deep Sync** — parse diffs, detect rationale, dependency changes, revert chains, structural patterns

### Settings
Configure compression behavior, session limits, and API keys. Keys entered here are written directly to your `.env` file.

---

## API

The server exposes a REST API at `http://localhost:8766/api/`:

### Core

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/health` | Server status |
| GET | `/api/citations` | List all citations |
| POST | `/api/citations` | Add a citation |
| PATCH | `/api/citations/{id}` | Update a citation |
| DELETE | `/api/citations/{id}` | Delete a citation |
| DELETE | `/api/citations/clear` | Delete all citations |
| GET | `/api/search?q=query` | Search citations |
| POST | `/api/compress` | AI-compress a prompt |
| GET | `/api/memory` | List projects |
| GET | `/api/memory/{project}` | Get project memory |
| POST | `/api/memory` | Create a project |
| PATCH | `/api/memory/{project}` | Update project description/stack/prefs |
| GET | `/api/patterns` | Get learned patterns + suggestions |
| POST | `/api/import` | Import citations from JSON |
| GET | `/api/export` | Export all data as JSON |
| POST | `/api/settings/apikey` | Save an API key to `.env` |

### Git Integration

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/git/summary` | Basic repo summary |
| GET | `/api/git/deep-summary` | Deep analysis with categories, reverts, rationale |
| POST | `/api/git/sync` | Sync conventional commits to memory |
| POST | `/api/git/sync-deep` | Deep sync with diff parsing and dependency detection |

### Decision Trees & ADRs

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/memory/{project}/decision-tree` | Full decision tree with relationships |
| GET | `/api/memory/{project}/decision-tree/timeline` | Timeline with confidence scores |
| GET | `/api/memory/{project}/decision-tree/chains` | Decision chains (A caused B caused C) |
| GET | `/api/memory/{project}/decision-tree/{id}` | Single decision with ancestors/descendants |
| GET | `/api/memory/{project}/adrs` | Generate ADRs (nygard/madr/tropelex format) |
| GET | `/api/memory/{project}/adrs/bundle` | Download all ADRs as single markdown |

### Session Replay

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/memory/{project}/sessions` | List recent sessions |
| GET | `/api/memory/{project}/sessions/{id}` | Full session detail with snapshots |
| GET | `/api/memory/{project}/sessions/{id}/changes` | Just the changes for a session |
| POST | `/api/memory/{project}/sessions/record` | Record current state as snapshot |
| POST | `/api/memory/{project}/sessions/{id}/rollback` | Rollback memory to before a session |
| GET | `/api/memory/{project}/sessions/weekly-summary` | What changed this week |

### Knowledge Decay & Confidence

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/memory/{project}/confidence` | Confidence summary (avg, tiers, stale count) |
| GET | `/api/memory/{project}/stale` | Stale decisions (low confidence or old) |
| GET | `/api/memory/{project}/decisions/scored` | All decisions with confidence scores |
| POST | `/api/memory/{project}/decay/apply` | Apply confidence scores to memory |

### RAG & Cross-Pollination

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/memory/{project}/rag` | Retrieve relevant memory snippets |
| POST | `/api/memory/{project}/rag/context` | Retrieve as formatted context string |
| GET | `/api/memory/{project}/cross-pollinate` | Find transferable knowledge from similar projects |
| GET | `/api/memory/{project}/cross-pollinate/briefing` | Cross-project knowledge briefing |
| POST | `/api/memory/{project}/suggest-approaches` | Suggest approaches for a problem |

### Research Chains

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/memory/{project}/research-chains` | List research chains |
| POST | `/api/memory/{project}/research-chains` | Create a new chain |
| GET | `/api/memory/{project}/research-chains/{id}` | Get full chain |
| POST | `/api/memory/{project}/research-chains/{id}/step` | Add a step |
| POST | `/api/memory/{project}/research-chains/{id}/complete` | Complete with synthesis |

### Agent Skills & Prompt Genealogy

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/memory/{project}/agent-skills` | Agent skill scores |
| POST | `/api/memory/{project}/agent-skills/record` | Record session outcome |
| GET | `/api/memory/{project}/agent-skills/briefing` | Proficiency briefing |
| GET | `/api/memory/{project}/prompt-genealogy` | Compression strategy stats |
| POST | `/api/memory/{project}/prompt-genealogy/record` | Record a compression |
| POST | `/api/memory/{project}/prompt-genealogy/outcome` | Record compression outcome |
| GET | `/api/memory/{project}/prompt-genealogy/rankings` | Strategy rankings |

### Research Feeds

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/research-feeds` | List all feeds |
| POST | `/api/research-feeds` | Create a new feed |
| GET | `/api/research-feeds/{id}` | Get feed details |
| PATCH | `/api/research-feeds/{id}` | Update a feed |
| DELETE | `/api/research-feeds/{id}` | Delete a feed |
| POST | `/api/research-feeds/{id}/run` | Run a feed now |
| GET | `/api/research-feeds/{id}/runs` | Get run history |
| GET | `/api/research-feeds/{id}/markdown` | Get feed output as markdown |
| DELETE | `/api/research-feeds/{id}/markdown` | Delete feed markdown |
| GET | `/api/research-feeds/stats` | Get feed statistics |
| POST | `/api/run` | Run all due feeds (rate limited) |
| POST | `/api/tick` | Check scheduler tick (rate limited) |

---

## Python API

### Memory

```python
from core.memory.manager import MemoryManager

mm = MemoryManager()
mm.add_decision("my-project", "Used FastAPI", "REST API needed async support")
mm.set_preference("my-project", "ui", "mobile-first")
context = mm.get_context_for_project("my-project")
print(context)  # Inject into agent system prompt
```

### Tropebook

```python
from core.tropebook import Tropebook

tb = Tropebook()
cid = tb.add("Python Docs", "https://docs.python.org", summary="Official Python docs", tags=["python"])
results = tb.search("async")
tb.link(cid1, cid2, "related_to")
tb.export_json()
```

### Compression

```python
from core.compression.dictionary import compress

# Level 1 = phrase remaps only
# Level 2 = + filler word removal
# Level 3 = + aggressive stop word strip
compressed = compress("could you please help me with implementing a function", level=2)
# -> "help implementing function"
```

### Pattern Learner

```python
from core.learner.learner import PatternLearner
from core.memory.manager import MemoryManager

mm = MemoryManager()
learner = PatternLearner(mm)
analysis = learner.analyze_session("my-project", "Fixed CSS bug in mobile layout")
learner.update_project_from_session("my-project", analysis)
suggestions = learner.suggest_next_steps("my-project")
```

### Git Integration

```python
from core.git_integration import sync_repo_to_memory, get_deep_repo_summary
from core.memory.manager import MemoryManager

mm = MemoryManager()

# Deep summary with work categories, rationale, dependency changes
summary = get_deep_repo_summary("/path/to/repo")

# Sync to memory (decisions, tech stack, patterns)
import asyncio
result = asyncio.run(sync_repo_to_memory("/path/to/repo", "my-project", mm))
```

### Decision Trees

```python
from core.decision_tree import DecisionTree

tree = DecisionTree.from_decisions(decisions)
timeline = tree.get_timeline()          # sorted with relationships
chains = tree.get_chains()              # A caused B caused C
ancestors = tree.get_ancestors(did)     # what led to this decision
```

### Knowledge Decay

```python
from core.knowledge_decay import score_decisions, get_confidence_summary

scored = score_decisions(decisions)     # each decision gets a confidence score
summary = get_confidence_summary(memory) # avg, tiers, stale count
```

### Cross-Pollination

```python
from core.rag import CrossPollinator

cp = CrossPollinator(memory_manager)
transfers = cp.find_transferable_knowledge("my-project", "how to handle auth")
approaches = cp.suggest_approaches("my-project", "caching strategy")
```

### OpenCode Adapter

```python
from adapters.opencode import TropelexAdapter

adapter = TropelexAdapter()
context = adapter.generate_session_prompt("my-project")
# Inject `context` into your OpenCode session system prompt

adapter.record_decision("my-project", "Switched to uv", "Faster than pip")
adapter.summarize_session("my-project", "Built the compression pipeline and UI")
```

---

## Project Structure

```
Tropelex/
├── core/
│   ├── memory/              # Project knowledge storage
│   │   └── manager.py       # MemoryManager
│   ├── compression/         # Prompt compression
│   │   └── dictionary.py    # Stop words, phrase remaps, meta commands
│   ├── context-compressor/  # Compressor class (wraps compression/)
│   │   └── compressor.py
│   ├── learner/             # Pattern detection
│   │   └── learner.py       # PatternLearner
│   ├── git_integration.py   # Git-aware memory (commit parsing, diff analysis)
│   ├── decision_tree.py     # Decision graph with relationships
│   ├── adr_generator.py     # Living ADR generation (Nygard/MADR/Tropelex)
│   ├── session_replay.py    # Session diffs, rollback, weekly summaries
│   ├── knowledge_decay.py   # Confidence scoring, staleness detection
│   ├── research_chains.py   # Multi-hop research chains
│   ├── rag.py               # Memory RAG + Cross-Pollination
│   ├── agent_skills.py      # Agent skill graph + Prompt genealogy
│   ├── embeddings.py        # Vector embeddings for semantic search
│   ├── research_pipeline.py # Auto-research, staleness, dedup
│   ├── llm.py               # LLM backend (OpenAI/Ollama)
│   └── tropebook/           # Research knowledge base
│       ├── tropebook.py     # Core KB + graph
│       ├── research.py      # Web search (Brave/DuckDuckGo)
│       ├── research_feeds.py # Scheduled feed monitoring
│       ├── scheduler.py     # FeedScheduler (run/tick/search)
│       ├── deep_research.py # Google Deep Research importer
│       ├── cli.py           # CLI
│       └── web/
│           └── server.py    # FastAPI server (80+ endpoints, rate limiting)
├── adapters/
│   └── opencode.py          # OpenCode integration
├── scripts/
│   ├── init_project.py      # Project scaffolding
│   ├── git_sync.py          # CLI for git sync
│   └── feed_cli.py          # Feed management CLI
├── UI/
│   ├── animated_tropebook_dashboard/code.html  # Main dashboard (7 tabs)
│   └── prompt-compressor.html                  # Standalone compressor tool
├── memory/                  # Runtime storage (gitignored)
│   ├── tropebook/           # Citation/graph storage
│   ├── replays/             # Session replay snapshots
│   ├── research_chains/     # Research chain storage
│   ├── agent_skills/        # Agent skill data
│   └── prompt_genealogy/    # Compression outcome tracking
├── .env                     # API keys (gitignored)
├── requirements.txt
├── AGENTS.md                # Instructions for AI agents
├── README.md
├── design.md                # Architecture documentation
└── wishlist.md              # Future feature roadmap
```

---

## Storage

All data lives in `memory/` (gitignored):

```
memory/
├── <project-name>.json         # One file per project (decisions, patterns, prefs)
├── tropebook/
│   ├── citations.json          # All research citations
│   ├── graph.json              # Knowledge graph (nodes + edges)
│   ├── index.json              # Fast lookup index
│   ├── research_feeds.json     # Feed definitions
│   ├── feed_runs.json          # Feed run history
│   └── feeds/                  # Per-feed markdown output
│       └── <feed-id>.md
├── replays/<project>/
│   ├── index.json              # Session index
│   └── <session-id>.json       # Full session snapshots + diffs
├── research_chains/<project>/
│   ├── index.json              # Chain index
│   └── <chain-id>.json         # Research chain with steps + findings
├── agent_skills/
│   └── <project>.json          # Skill scores per category
├── prompt_genealogy/
│   └── <project>.json          # Compression strategy outcomes
└── embeddings/
    └── citations.json          # Vector embeddings for semantic search
```

---

## Moving to Linux

This project is Linux-native. No Windows paths are hardcoded. To migrate:

1. Clone or copy the project to your Linux home
2. Create `.env` with your API keys
3. `uv venv && uv pip install -r requirements.txt`
4. `uv run python -m core.tropebook.web.server`

---

## Status

**v3.0.0** — Full feature set + comprehensive test suite + security hardening.

### Core Features
- Memory, compression, pattern learning, research KB all working
- Web UI with 7 tabs: Tropebook, Memory, Patterns, Prompt Lab, **Insights**, **Git**, Settings
- Git-aware memory: auto-extract decisions from commits with deep diff analysis
- Decision trees: graph of decision evolution with causal chains
- Living ADRs: auto-generate Architecture Decision Records (Nygard/MADR/Tropelex formats)
- Session replay: structured memory diffs, rollback support, weekly summaries
- Knowledge decay: time-based confidence scoring with tier classification
- Research chains: multi-hop knowledge building across search results
- Memory RAG: semantic retrieval from project memory at query time
- Cross-pollination: surface solutions from similar projects
- Agent skills: track proficiency per work category
- Prompt genealogy: learn which compression strategies produce best outcomes
- **Research Feeds**: scheduled monitoring with auto-ingest to citations
- **Ghost Decisions**: silent drift detection — code contradicts decisions
- **Explainable Memory**: conversational "why do we...?" with causal chains
- **Agent Handoff Packets**: role-aware context bundles for multi-agent workflows
- **Decision Market**: confidence bets, calibration tracking, leaderboard
- **Memory Lens**: IDE inline annotations — GitLens but for decisions
- **Slack Capture**: bidirectional Slack integration for decision logging
- **Time-Travel Debugger**: memory snapshots as of any past date
- **Contradiction Detection**: actively scan for unresolved conflicting decisions
- **Digital Twin Personas**: synthesize readable persona summaries from agent proficiency
- **Federated Benchmarking**: opt-in, privacy-preserving cross-install statistics
- **Memory Compaction**: epoch summarization to prevent unbounded memory growth
- **Friction Mining**: implicit signal detection from conversation transcripts
- **Preventive Ghost Checks**: pre-write hook that checks diff against active decisions
- **Rationale Corroboration**: fact-check decision rationale against the live web
- **PR Bot**: deliver ghost decisions, contradictions as PR comments
- **Narrative Mode**: readable prose summaries for non-technical audiences
- **Cost Ledger**: per-decision token cost tracking and ROI scoring
- **Predictive Prefetch**: budget-aware context assembly prioritized by impact score
- **Background Scheduler**: automatic periodic tasks — feeds, ghost scans, stale checks

### Security & Reliability
- **Rate limiting**: 30 req/min global + 5 feed runs/min on sensitive endpoints
- **Input sanitization**: All query parameters trimmed and length-limited
- **Error handling**: Try/except on all endpoints, research_feeds.py, feed_cli.py, scheduler.py
- **Debug endpoint hardened**: API key previews removed, only boolean presence flags
- **Path traversal protection**: Feed IDs validated against special characters
- **XSS protection**: `escapeHtml()` on all user-facing data in UI
- **SSRF protection**: URL scheme validation, private IP blocking in web scraper
- **File locking**: `fcntl.flock` on embeddings, federation, alert storage
- **Atomic memory writes**: Race condition prevention in MemoryManager
- **Background scheduler**: Automatic periodic tasks with error recovery

### Quality Metrics
- **1246 tests passing** (up from 262)
- 7 previously untested subsystems now have full coverage (3,093 lines)
- AI compression via OpenAI (`gpt-4o-mini`)
- CORS locked to localhost
- In-memory rate limiting (no external dependencies)
