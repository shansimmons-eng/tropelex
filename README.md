# Tropelex

**Persistent memory and learning system for AI agents.**

Tropelex accumulates knowledge across projects — decisions, patterns, preferences, research — so sessions don't start from scratch. It grows smarter with use.

The same mechanisms that make an agent's memory useful also make its behavior auditable: an immutable decision history an agent must cross-reference before acting, drift detection that catches code silently diverging from stated intent, and multi-agent handoff that carries rationale across agent boundaries instead of losing it. See [`SAFETY.md`](SAFETY.md) for how these properties apply to agent safety and alignment work.

---

## What it does

| Component | Purpose |
|---|---|
| **Memory Manager** | Stores project knowledge as JSON — decisions, preferences, session history |
| **Pattern Learner** | Analyzes sessions to detect recurring themes and suggest next steps |
| **Context Compressor** | Strips filler from prompts using AI (OpenAI) or dictionary-based rules — also reduces the surface area untrusted payloads have to carry injected instructions ([SAFETY.md](SAFETY.md#prompt-injection--payload-defense)) |
| **Tropebook** | Research knowledge base — store, search, link citations with a graph |
| **Agent Pipeline** | 3-stage prompt prep: compress → context check → structure |
| **Prompt Hijacker** | One-click AI compression for any prompt before sending to an AI |
| **Git Integration** | Auto-extract decisions, rationale, and tech stack changes from commits |
| **Decision Trees** | Graph of decision evolution — tracks what caused what, reverts, relationships |
| **Living ADRs** | Auto-generate Architecture Decision Records from memory data |
| **Session Replay** | Structured memory diffs per session — what changed, rollback support |
| **Knowledge Decay** | Time-based confidence scoring — decisions lose reliability over age, preventing stale policy from silently retaining full authority ([SAFETY.md](SAFETY.md#guardrail-ossification-prevention)) |
| **Research Chains** | Multi-hop knowledge building — search → find gaps → search again → link |
| **Memory RAG** | Semantic retrieval from project memory at query time |
| **Cross-Pollination** | Surface solutions from similar projects with matching tech stacks |
| **Agent Skills** | Track what the agent has become proficient at per project |
| **Prompt Genealogy** | Track which compression strategies produce the best outcomes |
| **Research Feeds** | Scheduled monitoring with auto-ingest to citations |
| **Deep Research** | Two research engines side by side: multi-source scan via last30days (Reddit, X, YouTube, GitHub, HN, Polymarket + LLM synthesis) and citation-grade web research via web-researcher-mcp — plus a hybrid mode that runs both and has the LLM merge/dedupe them into one report |
| **Ghost Decisions** | Silent objective-drift detection — code contradicts decisions without anyone saying so ([SAFETY.md](SAFETY.md#silent-objective-drift-detection)) |
| **Explainable Memory** | Conversational "why do we...?" with full causal chain |
| **Agent Handoff Packets** | Role-aware context bundles for multi-agent workflows — a working inter-agent coordination protocol ([SAFETY.md](SAFETY.md#inter-agent-coordination-protocol)) |
| **Decision Market** | Confidence bets, calibration tracking, leaderboard — a live calibration and honest-signaling mechanism among cooperating agents ([SAFETY.md](SAFETY.md#calibration--honest-signaling-mechanism)) |
| **Memory Lens** | IDE inline annotations — GitLens but for decisions |
| **Slack Capture** | Bidirectional Slack integration for decision logging |
| **Time-Travel Debugger** | Memory snapshots as of any past date — forensic state auditing ([SAFETY.md](SAFETY.md#forensic-state-auditing)) |
| **Contradiction Detection** | Actively scan for unresolved conflicting decisions — surfaces conflicting objectives before they cause harm ([SAFETY.md](SAFETY.md#conflicting-objective-surfacing)) |
| **Doc Mining** | Scans every markdown file in the repo for drift against recorded decisions, contradictions between docs, and decision-shaped claims never captured in the decision graph — reuses the Contradiction Detection engine rather than a separate one |
| **Digital Twin Personas** | Synthesize readable persona summaries from agent proficiency |
| **Federated Benchmarking** | Opt-in, privacy-preserving cross-install statistics |
| **Memory Compaction** | Epoch summarization to prevent unbounded memory growth |
| **Friction Mining** | Implicit signal detection from conversation transcripts — a lightweight human-in-the-loop alignment elicitation channel ([SAFETY.md](SAFETY.md#human-in-the-loop-alignment-elicitation)) |
| **Preventive Ghost Checks** | Pre-write hook that checks diff against active decisions — a pre-action policy compliance gate ([SAFETY.md](SAFETY.md#pre-action-policy-compliance-gate)) |
| **Rationale Corroboration** | Fact-check decision rationale against the live web |
| **PR Bot** | Deliver ghost decisions, contradictions as PR comments |
| **Narrative Mode** | Readable prose summaries for non-technical audiences |
| **Cost Ledger** | Per-decision token cost tracking and ROI scoring |
| **Predictive Prefetch** | Budget-aware context assembly prioritized by impact score |
| **Background Scheduler** | Automatic periodic tasks — feeds, ghost scans, stale checks |
| **Emacs Integration** | Capture decisions and friction signals directly from Emacs — compilation errors, rapid saves, manual decisions |
| **Safety Metadata** | Risk classification, reversibility tracking, affected systems, safety categories for every decision |
| **Safety Dashboard** | Risk trend analysis, system exposure monitoring, safety score calculation |
| **Decision Impact Analysis** | Dependency graphs, risk propagation, critical system identification |
| **Safety Review Workflow** | Approval/rejection workflow with reviewer tracking and mitigation suggestions |
| **Alignment Evaluation** | Scoring across interpretability, safety, fairness, robustness, governance |
| **Governance Compliance** | Policy compliance checking against EU AI Act, NIST, ISO 42001 frameworks |
| **Interpretability Reports** | Human-readable explanations of decision rationale and factors |
| **Fairness Audit** | Bias detection across decision categories and affected systems |
| **Accountability Tracking** | Reviewer accountability, decision chains, gap identification |
| **Robustness Testing** | Single points of failure, irreversible risks, concentration risk analysis |
| **Provenance Chain** | Cryptographic hash chain of decision history for tamper detection |
| **Integrity Verification** | Hash chain validation, timestamp ordering, structure verification |
| **Security Audit Log** | Immutable chronological log of all security-relevant events |
| **Decision Versioning** | Version history, rollback support, change tracking |
| **Automated Safety Checks** | Pre-decision safety analysis with risk scoring and recommendations |
| **Synthetic Data Policy** | EU AI Act Articles 10 & 50 compliant "nutritional label" for synthetic datasets — fidelity, privacy, bias audits, blocking gates |

---

## Safety & Alignment Documentation

Tropelex doubles as empirical safety infrastructure for autonomous agents. For the alignment reframing of its features, threat models, and grant-specific technical summaries, see:

- [SAFETY.md](./SAFETY.md) — mapping developer features to AI safety & control terminology.
- [CAIS Grant Technical Summary](./docs/cais-summary.md) — objective drift and reward hacking prevention.
- [FAR AI Grant Technical Summary](./docs/far-ai-summary.md) — cooperative multi-agent coordination and calibration.
- [SFF Grant Technical Summary](./docs/sff-summary.md) — independent developer, open-source safety infrastructure.

---

## Requirements

- Python 3.10+
- `uv` (recommended) or `pip`
- OpenAI API key (for AI compression — optional, dictionary fallback available)
- Brave Search API key (optional — falls back to DuckDuckGo free)
- xAI API key (optional — enables X/Twitter search + LLM planner for Deep Research)
- ScrapeCreators API key (optional — unlocks Reddit without rate limits, TikTok, Instagram, Threads, Pinterest)

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
Configure compression behavior, session limits, and API keys. Keys entered here are written directly to your `.env` file. Includes a **Deep Research Sources** panel for configuring xAI, ScrapeCreators, Bluesky, and other keys that expand deep research coverage.

### Deep Research
Two independent research engines, laid out side by side so neither buries the other, plus a hybrid mode:

- **Multi-Source Scan** — last30days engine. Searches Reddit, X, YouTube, GitHub, HackerNews, Polymarket, and web grounding in parallel, then synthesizes findings into a narrative brief with source citations and key patterns. 1–3 minutes, synchronous.
- **Citation-Grade Web Research** — [web-researcher-mcp](https://github.com/zoharbabin/web-researcher-mcp) (spoken to directly over MCP's stdio protocol, no extra Python dependency). Runs a small loop of search → LLM-refined follow-up query → search again, and imports every real, verifiable source URL straight into the Tropebook citation library. Requires the `web-researcher-mcp` binary on `PATH`.
- **Hybrid** — runs both engines concurrently on the same query, then asks the project's LLM backend to deduplicate and merge them into a single report. Degrades gracefully if one engine fails: the other's results (and any citations it found) are still returned and imported.

Configure sources for the multi-source scan in Settings → Deep Research Sources. Citation-grade research prefers `BRAVE_SEARCH_API_KEY` when set (falls back to the free DuckDuckGo provider otherwise, which rate-limits more aggressively under repeated use).

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
| POST | `/api/research-feeds` | Create a new feed (accepts `research_provider`: `web_search` or `deep_research`) |
| GET | `/api/research-feeds/stats` | Get feed statistics |
| POST | `/api/research-feeds/tick` | Run all due feeds (rate limited) |
| GET | `/api/research-feeds/{id}` | Get feed details |
| PUT | `/api/research-feeds/{id}` | Update a feed |
| DELETE | `/api/research-feeds/{id}` | Delete a feed |
| POST | `/api/research-feeds/{id}/run` | Run a feed now |
| GET | `/api/research-feeds/{id}/runs` | Get run history |
| GET | `/api/research-feeds/{id}/markdown` | Get feed output as markdown |
| GET | `/api/research-feeds/{id}/intelligence` | Get feed trend detection and anomaly report |
| GET | `/api/research-feeds/{id}/citations` | Get feed citations |

### Deep Research (last30days)

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/last30days/query` | Run a deep research query — returns HTML output + citations (1–3 min) |

### Deep Research (web-researcher-mcp)

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/memory/{project}/deep-research/web-research` | Citation-grade multi-step web research; imports results into the Tropebook |
| POST | `/api/memory/{project}/deep-research/hybrid` | Runs last30days + web-researcher-mcp concurrently, LLM-merges the results |

### Safety & Alignment

| Method | Endpoint | Description |
|---|---|---|
| **Safety Metadata** | | |
| POST | `/api/memory/{project}/decisions` | Add decision with optional `safety_metadata` (risk_level, reversibility, affected_systems, safety_category, requires_review) |
| GET | `/api/memory/{project}/safety-stats` | Aggregated safety statistics (risk distribution, safety score) |
| GET | `/api/memory/{project}/safety-dashboard` | Comprehensive safety metrics with trends and system exposure |
| GET | `/api/memory/{project}/safety-trend` | Time-series risk data for charting |
| **Decision Impact** | | |
| GET | `/api/memory/{project}/decision-impact` | System-wide impact analysis with dependency graph and risk propagation |
| GET | `/api/memory/{project}/decision-impact/{id}` | Per-decision impact with related decisions and dependency chain |
| **Safety Review Workflow** | | |
| GET | `/api/memory/{project}/reviews/pending` | Decisions requiring review (sorted by risk) |
| GET | `/api/memory/{project}/reviews/history` | Review history with optional status filter |
| GET | `/api/memory/{project}/reviews/stats` | Approval rates, reviewer activity, avg review time |
| POST | `/api/memory/{project}/decisions/{id}/review` | Submit safety review (reviewer, status, comments, mitigation) |
| POST | `/api/memory/{project}/decisions/{id}/approve` | Quick-approve a decision |
| POST | `/api/memory/{project}/decisions/{id}/reject` | Quick-reject a decision |
| **Alignment & Governance** | | |
| GET | `/api/memory/{project}/alignment/evaluate` | Project-wide alignment scoring across 5 categories |
| POST | `/api/memory/{project}/decisions/{id}/alignment` | Per-decision alignment evaluation with custom criteria |
| GET | `/api/memory/{project}/alignment/values` | Check decisions against organizational values |
| GET | `/api/memory/{project}/alignment/drift` | Detect alignment drift over time |
| GET | `/api/memory/{project}/safety-envelope` | Monitor safety boundaries and thresholds |
| GET | `/api/memory/{project}/corrigibility` | Track ability to correct/override decisions |
| GET | `/api/memory/{project}/governance/policies` | Governance policy definitions |
| GET | `/api/memory/{project}/governance/compliance` | Governance compliance checking |
| GET | `/api/memory/{project}/interpretability/{id}` | Human-readable interpretability report |
| **Fairness, Accountability, Robustness** | | |
| GET | `/api/memory/{project}/fairness/audit` | Bias detection across categories and systems |
| GET | `/api/memory/{project}/accountability/report` | Reviewer accountability and decision chains |
| GET | `/api/memory/{project}/robustness/test` | Single points of failure, irreversible risks |
| GET | `/api/memory/{project}/transparency/report` | Human-readable decision summaries |
| **Provenance, Integrity, Security** | | |
| GET | `/api/memory/{project}/provenance/chain` | Cryptographic hash chain of decisions |
| GET | `/api/memory/{project}/integrity/verify` | Verify hash chain and timestamp ordering |
| GET | `/api/memory/{project}/tamper-detection` | Detect duplicate IDs, timestamp anomalies |
| GET | `/api/memory/{project}/security/audit-log` | Immutable chronological security event log |
| **Compliance & Versioning** | | |
| GET | `/api/memory/{project}/compliance/report` | EU AI Act, NIST, ISO 42001 compliance reports |
| POST | `/api/memory/{project}/decisions/{id}/version` | Create version snapshot |
| GET | `/api/memory/{project}/decisions/{id}/versions` | Get version history |
| POST | `/api/memory/{project}/decisions/{id}/rollback/{v}` | Rollback to previous version |
| GET | `/api/memory/{project}/stakeholder-impact` | System/stakeholder impact matrix |
| GET | `/api/memory/{project}/risk-heatmap` | Risk distribution for visualization |
| POST | `/api/memory/{project}/safety-check` | Pre-decision safety analysis |
| **Synthetic Data Policy** | | |
| POST | `/api/memory/{project}/synthetic-data-policies` | Register a synthetic dataset with full metadata |
| GET | `/api/memory/{project}/synthetic-data-policies` | List all registered synthetic datasets |
| GET | `/api/memory/{project}/synthetic-data-policies/{id}` | Get full policy details |
| PUT | `/api/memory/{project}/synthetic-data-policies/{id}` | Update a policy |
| DELETE | `/api/memory/{project}/synthetic-data-policies/{id}` | Delete a policy |
| GET | `/api/memory/{project}/synthetic-data-policies/{id}/compliance` | Run compliance check with blocking gates |
| GET | `/api/memory/{project}/synthetic-data/summary` | Aggregate statistics across all policies |

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

## Emacs Integration

The `emacs/tropelex-capture.el` package captures decisions, friction signals, and git commits directly from Emacs. Zero external dependencies — uses only built-in `json.el` and `url.el`.

### Setup

```elisp
(add-to-list 'load-path "~/Tropelex/emacs")
(require 'tropelex-capture)
(tropelex-capture-mode 1)  ; global mode — enables all hooks
```

### Commands

| Keybinding | Command | Description |
|---|---|---|
| `C-c t c` | `tropelex-capture-decision` | Capture a decision with auto-detected context (file, project, mode, code context) |
| `C-c t r` | `tropelex-capture-region` | Capture selected region as decision context (code snippet, log output) |
| `C-c t f` | `tropelex-friction-scan` | Scan current buffer for friction signals |
| `C-c t g` | `tropelex-capture-commit` | Capture current HEAD commit as a decision |
| `C-c t s` | `tropelex-status` | Check server connectivity and current project |
| `C-c t p` | `tropelex-set-project` | Override project name for the session |

### Automatic Capture (when mode is on)

- **Compilation errors** → when compilation exits abnormally, the output is auto-scanned for friction. If the friction score exceeds 30%, you get a minibuffer alert.
- **Rapid saves** → 5+ file saves within 5 seconds triggers a friction signal ("rapid iteration detected"). Catches when you're thrashing.
- **Git commits via Magit** → after every magit commit, the message (50+ chars) is auto-captured as a Tropelex decision with diffstat context.

### Code Context (LSP / treesit / which-function)

Captures automatically include the current function name and type when available:
- Uses **eglot** or **lsp-mode** for symbol info (hover)
- Falls back to **treesit** (Emacs 29+) for syntax tree traversal
- Falls back to **which-function-mode** as last resort
- Set `tropelex-include-code-context` to `nil` to disable

### Project Detection

Auto-detects from: projectile → `vc-root-dir` → directory name fallback. Override with `C-c t p`.

---

## OpenCode Integration

Slash commands and a startup hook for using Tropelex from inside [OpenCode](https://opencode.ai). Defined in [`.opencode/`](.opencode/) — the plugin itself is [`plugins/tropelex.js`](plugins/tropelex.js).

**Setup required** — OpenCode only loads plugins it's told about:

```bash
cp plugins/tropelex.js ~/.config/opencode/plugins/tropelex.js
```

Then add `"tropelex"` to the `"plugin"` array in `~/.config/opencode/opencode.json` (and `opencode.jsonc`, if present). Restart OpenCode. If commands aren't showing in the command palette, this step is almost always why.

| Command | What it does |
|---|---|
| `/tropelex-record-decision` | Record a decision — `/tropelex-record-decision Using PostgreSQL for database` |
| `/tropelex-end-session` | Summarize the session and trigger pattern learning |
| `/tropelex-show-context` | Print accumulated context for the current project |
| `/tropelex-context` | Run raw queries against project memory, insights, and recent decisions |
| `/tropelex-up` | Create/update a project's memory record |

Project name auto-detects from the workspace folder name or git remote; override with `TROPELEX_PROJECT`. The startup hook also compresses prompts over a configurable length and injects project context automatically — see `plugins/tropelex.js`'s header for all env vars (`TROPELEX_URL`, `TROPELEX_COMPRESS_MIN`, `TROPELEX_INJECT_CONTEXT`).

## CLI Reference

A local command-line interface for the Tropebook citation library (`core/tropebook/cli.py`, installed as the `tropelex` command). Operates directly on local storage — doesn't require the server running.

| Command | What it does |
|---|---|
| `tropelex add <title> <url> [summary]` | Add a citation |
| `tropelex search <query>` | Search the knowledge base |
| `tropelex list [tag]` | List all citations, or filter by tag |
| `tropelex import <file>` | Import citations from a JSON or markdown file |
| `tropelex stats` | Show knowledge base stats |
| `tropelex link <url1> <url2> <rel>` | Add a relationship between two citations |

```bash
tropelex add "Python Docs" "https://docs.python.org" "Official Python docs"
tropelex search "machine learning"
```

If `tropelex` isn't on `PATH`: `python -m core.tropebook.cli <command>`.

## MCP Server

Everything the dashboard, VSCode extension, and Emacs package do over Tropelex's REST API is also available as MCP tools, so any MCP-capable agent — Claude Code, Cursor, Claude Desktop — can read and write project memory directly, without a bespoke per-editor integration.

Lives in [`mcp_server/`](mcp_server/), in its own venv kept separate from Tropelex's own system-Python server.

### Setup

```bash
cd mcp_server
uv venv .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

### Register with Claude Code

A project-scoped `.mcp.json` is committed at the repo root — anyone who clones Tropelex and opens it in Claude Code gets the `tropelex` MCP server automatically (it shells out to `mcp_server/run.sh`, which resolves its own venv relative to the repo, so no absolute paths are baked in). No manual registration needed.

To register it in a different Claude Code project, or for another MCP client:

```bash
claude mcp add tropelex -- /path/to/Tropelex/mcp_server/.venv/bin/python /path/to/Tropelex/mcp_server/server.py
```

Requires the main Tropelex server running (`python3 -m core.tropebook.web.server`). Point at a non-default instance with `TROPELEX_URL`.

### Tools

`list_projects`, `get_project_memory`, `capture_decision`, `end_session`, `get_context_bundle` (predictive prefetch), `check_contradictions`, `check_diff_for_conflicts` (pre-write guard), `friction_scan`, `get_handoff_packet`, `explain_why`. Full detail in [`mcp_server/README.md`](mcp_server/README.md).

## Terminal UI

A Textual-based terminal dashboard for anyone who lives in tmux rather than an editor — project list, decision table, contradiction count, capture decisions without leaving the terminal. Lives in [`tui/`](tui/), own venv, same setup pattern as the MCP server. See [`tui/README.md`](tui/README.md) for keybindings and setup.

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
│   ├── friction/            # Friction mining — implicit signal detection
│   │   ├── miner.py         # Signal detection, scoring, zone grouping
│   │   └── router.py        # POST /api/memory/{project}/friction/scan
│   ├── last30days/          # Deep research engine (last30days integration)
│   │   ├── last30days.py    # Multi-source research engine (60+ source modules)
│   │   ├── synthesize_run.py # Pipeline + LLM synthesis + HTML render in one pass
│   │   ├── runner.py        # Subprocess wrapper for the engine
│   │   └── lib/             # Engine internals (sources, rendering, planning)
│   └── tropebook/           # Research knowledge base
│       ├── tropebook.py     # Core KB + graph
│       ├── research.py      # Web search (Brave/DuckDuckGo)
│       ├── research_feeds.py # Scheduled feed monitoring
│       ├── scheduler.py     # FeedScheduler (run/tick/search)
│       ├── deep_research.py # Google Deep Research importer
│       ├── feed_intelligence.py # Feed trend detection
│       ├── cli.py           # CLI
│       └── web/
│           └── server.py    # FastAPI server (80+ endpoints, rate limiting)
├── emacs/                   # Emacs integration
│   └── tropelex-capture.el  # Decision capture, friction scanning, rapid-save tracking
├── adapters/
│   └── opencode.py          # OpenCode integration
├── scripts/
│   ├── init_project.py      # Project scaffolding
│   ├── git_sync.py          # CLI for git sync
│   └── feed_cli.py          # Feed management CLI
├── UI/
│   ├── animated_tropebook_dashboard/code.html  # Main dashboard (8 tabs + Deep Research)
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

**v3.2.0** — Dashboard overhaul + Emacs Magit/LSP integration + 17 router fixes + section persistence.

### Core Features
- Memory, compression, pattern learning, research KB all working
- Web UI with 8 sections: Tropebook, Memory, Patterns, Prompt Lab, **Insights**, **Git**, **Deep Research**, Settings
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
- **Research Feeds**: scheduled monitoring with auto-ingest to citations (web_search + deep_research providers)
- **Deep Research**: multi-source research via the last30days engine — Reddit, X, YouTube, GitHub, HN, Polymarket + LLM synthesis into narrative briefs
- **Emacs Integration**: capture decisions, friction signals, and git commits from Emacs — with Magit hooks, LSP context, compilation auto-scan, rapid-save tracking
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
- **Friction Mining**: implicit signal detection from conversation transcripts (fixed UI button, auto-scan from Emacs)
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
- **1408 tests passing** (up from 262)
- 7 previously untested subsystems now have full coverage (3,093 lines)
- AI compression via OpenAI (`gpt-4o-mini`)
- CORS locked to localhost
- In-memory rate limiting (no external dependencies)
