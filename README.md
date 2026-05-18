# Tropelex

**Persistent memory and learning system for AI agents and human collaborators.**

Tropelex accumulates knowledge across projects — patterns, decisions, preferences — so you don't re-explain things twice. It evolves with use.

## Features

### Memory Manager
Stores project knowledge as JSON files, tracking decisions, preferences, and session history.

### Context Compressor
Trims prompts on the fly while preserving signal. Includes stop word dictionaries, phrase rephrasing, and meta language for real-time compression control.

### Pattern Learner
Analyzes sessions for patterns and suggests likely next work based on history.

### Tropebook (Research Knowledge Base)
Store, search, and manage research citations with relationships. Includes web search and import from Google Deep Research / NotebookLM.

## Installation

```bash
git clone https://github.com/retroporter/tropelex.git
cd tropelex
pip install -r requirements.txt
```

## Quick Start

### Tropebook (Research Tool)

```python
from core.tropebook import Tropebook, create_researcher, create_importer

# Knowledge base
tb = Tropebook()
cid = tb.add("Python Docs", "https://docs.python.org", "Official Python docs")
results = tb.search("tutorials")
tb.link(cid1, cid2, "related_to")

# Web research (free - uses DuckDuckGo if no Brave API key)
researcher = create_researcher()  # or create_researcher(api_key="...")
results = researcher.research("machine learning transformers")

# Import from Google Deep Research / NotebookLM
importer = create_importer(tb)
count = importer.import_file("research_export.json")
```

### Web Interface

```bash
python -m core.tropebook.web.server
# Opens at http://localhost:8765
```

### CLI

```bash
python -m core.tropebook.cli add "Title" "https://url.com" "Summary"
python -m core.tropebook.cli search "query"
python -m core.tropebook.cli import file.json
python -m core.tropebook.cli stats
```

### Context Compression

```python
from core.compression import compress, STOP_WORDS, PHRASE_REMAPS

# Basic compression (level 1=light, 3=aggressive)
compressed = compress("please could you help me with this task")

# Stop words and phrase remaps are customizable
print(STOP_WORDS)      # 100+ common words
print(PHRASE_REMAPS)   # 40+ verbose->compact mappings
```

## Project Structure

```
Tropelex/
├── core/
│   ├── memory/              # Project knowledge storage
│   ├── context-compressor/  # Prompt compression + dictionary
│   ├── compression/         # Stop words, phrase remaps, meta language
│   ├── learner/             # Pattern tracking
│   └── tropebook/            # Research knowledge base
│       ├── ropebook.py       # Core knowledge base + graph
│       ├── research.py        # Web search + scraping
│       ├── deep_research.py   # Google Deep Research importer
│       ├── web/               # FastAPI web interface
│       └── cli.py             # Command-line interface
├── adapters/                 # Agent integrations
├── memory/                   # Persistent storage
└── requirements.txt
```

## Configuration

### Brave Search API (optional)
Set `BRAVE_API_KEY` environment variable for Brave Search. Falls back to DuckDuckGo (free) if not set.

### Storage
Data is stored in `memory/` directory:
- `memory/tropebook/citations.json` - All citations
- `memory/tropebook/graph.json` - Knowledge graph edges
- `memory/tropebook/index.json` - Fast lookup indexes

## Status

Alpha — core components built, web interface and CLI ready.

---

*"The Namer names well."* — Built by the one who calls things into being.