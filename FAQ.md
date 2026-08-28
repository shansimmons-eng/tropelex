# Tropelex Technical & Governance FAQ

Welcome to the **Tropelex Technical & Governance FAQ**. This guide helps developers, architects, and teams new to AI-assisted coding understand how Tropelex captures rationale, optimizes token consumption, enforces safety governance, and accelerates AI pair programming.

---

## Table of Contents

### Fundamentals & Architecture
- [What is Tropelex and what problem does it solve?](#what-is-tropelex-and-what-problem-does-it-solve)
- [Where is governance data ingested and stored?](#where-is-governance-data-ingested-and-stored)
- [What do I do if I am not seeing any results for the active page?](#what-do-i-do-if-i-am-not-seeing-any-results-for-the-active-page)
- [What is the best way to consistently record decisions and activity?](#what-is-the-best-way-to-consistently-record-decisions-and-activity)

### AI Performance & Token Optimization
- [How can I improve my general AI coding workflows?](#how-can-i-improve-my-general-ai-coding-workflows)
- [What makes the AI's job easier and potentially reduces token consumption?](#what-makes-the-ais-job-easier-and-potentially-reduces-token-consumption)
- [What is context compression and how does it work?](#what-is-context-compression-and-how-does-it-work)
- [How does Tropelex prevent AI hallucinations and contradictions?](#how-does-tropelex-prevent-ai-hallucinations-and-contradictions)

### Governance, Safety & Synthetic Data
- [What is synthetic data?](#what-is-synthetic-data)
- [Why should I provide synthetic data details?](#why-should-i-provide-synthetic-data-details)
- [What is the EU AI Act compliance checker in the Synthetic Data Policy?](#what-is-the-eu-ai-act-compliance-checker-in-the-synthetic-data-policy)
- [How does the Pre-Write Safety Guard evaluate proposed diffs?](#how-does-the-pre-write-safety-guard-evaluate-proposed-diffs)

### Decisions, Memory & Rationale
- [What is an Architecture Decision Record (ADR)?](#what-is-an-architecture-decision-record-adr)
- [What is the difference between a static ADR and a Living ADR?](#what-is-the-difference-between-a-static-adr-and-a-living-adr)
- [What are Ghost Decisions and why do they matter?](#what-are-ghost-decisions-and-why-do-they-matter)
- [What is the Knowledge Graph and how are decisions connected?](#what-is-the-knowledge-graph-and-how-are-decisions-connected)
- [How does Tropelex track developer friction and frustration signals?](#how-does-tropelex-track-developer-friction-and-frustration-signals)

### Agent Workflows & Collaboration
- [What is an Agent Handoff Packet and when should I use it?](#what-is-an-agent-handoff-packet-and-when-should-i-use-it)
- [Can Tropelex share rationale and knowledge across different projects?](#can-tropelex-share-rationale-and-knowledge-across-different-projects)
- [How do I integrate Tropelex with Emacs or VSCode?](#how-do-i-integrate-tropelex-with-emacs-or-vscode)
- [How do I rollback memory or time-travel to a previous session?](#how-do-i-rollback-memory-or-time-travel-to-a-previous-session)
- [How do I run the automated Pytest suite to verify system health?](#how-do-i-run-the-automated-pytest-suite-to-verify-system-health)

---

## Frequently Asked Questions

---

### <a id="what-is-tropelex-and-what-problem-does-it-solve"></a>What is Tropelex and what problem does it solve?

Tropelex is a persistent memory and rationale engine designed for AI coding agents. It solves the "stateless AI" problem where agents lose architectural context between chat sessions and repeatedly make conflicting decisions.

<details>
<summary>🔍 <b>Expand full answer</b></summary>
<br>

Without Tropelex, every new session requires re-explaining architectural choices, tech stack preferences, and safety boundaries. Tropelex acts as a long-term memory layer that automatically injects relevant project decisions, learned coding patterns, and rationale graphs directly into the AI prompt context, keeping human developers and AI agents perfectly aligned over months of active development.
</details>

---

### <a id="where-is-governance-data-ingested-and-stored"></a>Where is governance data ingested and stored?

All governance data, safety evaluation metadata, architectural decisions, and session histories are ingested directly from your workspace and stored in local JSON files inside the `memory/` directory.

<details>
<summary>🔍 <b>Expand full answer</b></summary>
<br>

Tropelex operates on a 100% local-first architecture:
* **Project Decisions & Governance:** Saved per project in `memory/<project-name>.json`.
* **Research & Citations:** Managed in `memory/tropebook/citations.json` and `graph.json`.
* **Session Diff Snapshots:** Stored in `memory/snapshots/` for time-travel and rollback.

No governance metrics or project code files are ever transmitted to third-party cloud servers or external databases.
</details>

---

### <a id="what-do-i-do-if-i-am-not-seeing-any-results-for-the-active-page"></a>What do I do if I am not seeing any results for the active page?

If a section displays empty metrics or zero decisions, ensure a project is selected in the top-bar dropdown (`#global-project-select`) and click the **Refresh** button on the section panel.

<details>
<summary>🔍 <b>Expand full answer</b></summary>
<br>

Follow these quick diagnostic steps:
1. **Check Global Project Selection:** Look at the top-right header dropdown. If it displays `No project`, click to select your active project (e.g., `tropelex`).
2. **Run Diagnostic Self-Test:** Navigate to **Getting Started** (`Help Hub`) and click **Re-test All Systems** to verify FastAPI backend connection and Pytest status.
3. **Verify File Memory:** Confirm that `memory/<project-name>.json` exists in your workspace root. If empty, run `/tropelex-show-context` or record a starter decision.
</details>

---

### <a id="what-is-the-best-way-to-consistently-record-decisions-and-activity"></a>What is the best way to consistently record decisions and activity?

The most consistent method is using Tropelex slash commands during agent prompts, capturing directly from Emacs (`C-c t c`), or committing code with conventional Git commit messages.

<details>
<summary>🔍 <b>Expand full answer</b></summary>
<br>

Here are the 3 recommended capture channels:
* **Slash Command (In Chat):** `/tropelex-record-decision <what> | <why>` (e.g., `/tropelex-record-decision Used Application Passwords | WP auth needed X-API-Key fallback`).
* **Emacs Integration:** Press `C-c t c` inside any code buffer to automatically capture the active function signature, project name, and decision context.
* **Conventional Commits:** Commit code with descriptive conventional messages (e.g., `feat: implement Redis cache strategy for session tokens`). Tropelex automatically extracts decisions and rationale directly from git diffs.
</details>

---

### <a id="how-can-i-improve-my-general-ai-coding-workflows"></a>How can I improve my general AI coding workflows?

Improving AI coding relies on **Context Precision** over prompt length: provide high-signal architectural constraints, clear boundary conditions, and authoritative file snippets while omitting irrelevant code.

<details>
<summary>🔍 <b>Expand full answer</b></summary>
<br>

Top practices for maximizing AI coding performance:
1. **Load Context First:** Always begin sessions by injecting past architectural decisions (`/tropelex-show-context`) so the AI does not re-invent patterns.
2. **Enforce Single Responsibilities:** Break large monolithic requests into modular sub-tasks with verifiable acceptance criteria.
3. **Use Code Signatures:** Pass type definitions, interface contracts, and function signatures rather than dumping 2,000 lines of implementation logic.
4. **Demand Automated Verification:** Instruct the AI to run unit tests (`pytest`) or linters (`ruff`) to verify changes before declaring a task complete.
</details>

---

### <a id="what-makes-the-ais-job-easier-and-potentially-reduces-token-consumption"></a>What makes the AI's job easier and potentially reduces token consumption?

Using Tropelex's **Context Compressor** and **Prompt Lab** reduces prompt size by up to 80% by stripping boilerplate while preserving critical type signatures, active decisions, and code interfaces.

<details>
<summary>🔍 <b>Expand full answer</b></summary>
<br>

Key strategies for drastic token reduction:
* **Signature Extraction:** Tropelex's `ContextCompressor` keeps class definitions, function parameters, and docstrings while dropping function bodies.
* **Prefetching:** The **Context Prefetch** engine (`Explainability & Discovery`) analyzes your task and outputs only the exact minimal context bundle needed.
* **Anti-Rationalization:** Recording decisions once prevents the AI from engaging in long, expensive reasoning loops to rediscover why a library or pattern was chosen.
</details>

---

### <a id="what-is-context-compression-and-how-does-it-work"></a>What is context compression and how does it work?

Context compression (`core/context-compressor/compressor.py`) is an automated pipeline that trims long code files and session transcripts while preserving high-signal type signatures and core logic.

<details>
<summary>🔍 <b>Expand full answer</b></summary>
<br>

The compressor uses three strategies:
1. **`extract_signatures(code)`**: Replaces function and method bodies with `...` while maintaining exact parameters, return types, and class hierarchies.
2. **Priority Trimming:** Keeps top-level decisions and active constraints while condensing past log history.
3. **Summarization:** Keeps opening requirements and final outcomes while collapsing middle conversation loops.
</details>

---

### <a id="how-does-tropelex-prevent-ai-hallucinations-and-contradictions"></a>How does Tropelex prevent AI hallucinations and contradictions?

Tropelex features a **Contradiction Detector** (`Quality & Integrity`) that performs pairwise evaluation of active decisions to surface conflicting claims before code is written.

<details>
<summary>🔍 <b>Expand full answer</b></summary>
<br>

For example, if one decision states `"Use Postgres for primary database"` and a new prompt attempts to `"Use MySQL for primary database"`, Tropelex immediately flags a high-priority contradiction. The AI agent is forced to resolve or supersede the conflict before proceeding, preventing architectural hallucinations.
</details>

---

### <a id="what-is-synthetic-data"></a>What is synthetic data?

Synthetic data refers to artificially generated datasets—created via LLMs, algorithmic text synthesis, diffusion models, or CTGAN—used to train, fine-tune, or benchmark AI models without relying on sensitive real-world user data.

<details>
<summary>🔍 <b>Expand full answer</b></summary>
<br>

In modern AI engineering, synthetic data allows teams to generate massive, privacy-preserving edge-case testing sets and alignment benchmarks. However, because synthetic data lacks human unpredictability, unmonitored synthetic datasets can introduce bias, hallucinated edge cases, and compliance risks under emerging AI regulations.
</details>

---

### <a id="why-should-i-provide-synthetic-data-details"></a>Why should I provide synthetic data details?

Providing synthetic data details prevents the catastrophic **"Synthetic Mirror" risk**—an AI feedback loop where models train on AI-generated data, leading to severe mode collapse, rationale drift, and degraded reasoning over time.

<details>
<summary>🔍 <b>Expand full answer</b></summary>
<br>

Registering synthetic datasets in Tropelex enforces compliance with **EU AI Act Articles 10 & 50** by standardizing "nutritional labels" for every dataset:
1. **Synthetic-to-Real Ratio:** Ensures adequate grounding against real-world sample data.
2. **Provenance & Authorization:** Tracks Data Protection Officer (DPO) approvals and lawful seed data.
3. **Operational Constraints:** Demarcates prohibited use-cases and risk tiers before data enters model fine-tuning loops.
</details>

---

### <a id="what-is-the-eu-ai-act-compliance-checker-in-the-synthetic-data-policy"></a>What is the EU AI Act compliance checker in the Synthetic Data Policy?

The compliance checker evaluates registered synthetic datasets against EU AI Act risk tiers (Minimal Risk, Specific Transparency, High Risk, Systemic Risk) to ensure proper labeling and data governance.

<details>
<summary>🔍 <b>Expand full answer</b></summary>
<br>

Under EU AI Act Articles 10 & 50:
- Synthetic text and media must be marked with Machine-Readable Provenance.
- High-risk training sets require audited seed data lineage and lawful basis documentation.
- Tropelex automatically flags datasets missing DPO authorization or synthetic-to-real ratio bounds as **Non-Compliant**.
</details>

---

### <a id="how-does-the-pre-write-safety-guard-evaluate-proposed-diffs"></a>How does the Pre-Write Safety Guard evaluate proposed diffs?

The Pre-Write Safety Guard (`Quality & Integrity`) lets you paste a proposed code diff or function change *before* applying it to test if it violates active decisions or security rules.

<details>
<summary>🔍 <b>Expand full answer</b></summary>
<br>

When you click **Check for Ghosts / Pre-Write Check**, Tropelex parses the AST and diff signature, comparing it against the project decision graph. If the proposed code introduces an unrecorded architecture change or breaks a safety constraint, Tropelex issues a warning report with recommended mitigations.
</details>

---

### <a id="what-is-an-architecture-decision-record-adr"></a>What is an Architecture Decision Record (ADR)?

An **ADR (Architecture Decision Record)** is a short text document that captures an important architectural choice made in a project, along with its context, rationale, and consequences.

<details>
<summary>🔍 <b>Expand full answer</b></summary>
<br>

Tropelex introduces **Living ADRs** (`core/adr_generator.py`), which automatically compile your recorded project decisions into standardized industry formats:
- **Nygard Format:** Concise Title, Context, Decision, and Status.
- **MADR (Markdown Architectural Decision Records):** Standardized rationale, options considered, and pros/cons.
- **Tropelex Enhanced:** Enriched with live decision tree relationships (supersedes, caused_by, reverts) and real-time confidence scores.
</details>

---

### <a id="what-is-the-difference-between-a-static-adr-and-a-living-adr"></a>What is the difference between a static ADR and a Living ADR?

Traditional ADRs are static Markdown files written manually that quickly become outdated. A **Living ADR** in Tropelex is dynamically generated from real-time project memory, automatically updating confidence scores and lineage graph connections.

<details>
<summary>🔍 <b>Expand full answer</b></summary>
<br>

Unlike static files:
- Living ADRs track **Downstream Impact** (which subsequent decisions were caused by this choice).
- Living ADRs incorporate **Time-Based Knowledge Decay** scores.
- Living ADRs automatically update when a decision is superseded or reverted in Git.
</details>

---

### <a id="what-are-ghost-decisions-and-why-do-they-matter"></a>What are Ghost Decisions and why do they matter?

Ghost decisions occur when developers or AI agents write new code features or change architectures without logging the underlying rationale in project memory.

<details>
<summary>🔍 <b>Expand full answer</b></summary>
<br>

Ghost decisions create "silent drift," where future AI agents misunderstand the codebase structure and unintentionally break or revert unrecorded choices. Tropelex's **Ghost Decision Scanner** (`Quality & Integrity`) scans your repository diffs against active memory to surface uncaptured decisions before technical debt accumulates.
</details>

---

### <a id="what-is-the-knowledge-graph-and-how-are-decisions-connected"></a>What is the Knowledge Graph and how are decisions connected?

The Knowledge Graph (`Content` -> `Knowledge Graph`) is a D3.js visualization powered by `DecisionTree` (`core/decision_tree.py`) that auto-detects relationships between architectural choices.

<details>
<summary>🔍 <b>Expand full answer</b></summary>
<br>

The graph automatically links decisions using 4 key relationship types:
1. `supersedes`: A newer decision replaces an older strategy.
2. `caused_by`: A decision was required due to a previous technical choice.
3. `related_to`: Shared component or tag context.
4. `reverts`: Undoes a previous decision.
</details>

---

### <a id="how-does-tropelex-track-developer-friction-and-frustration-signals"></a>How does Tropelex track developer friction and frustration signals?

Friction Mining (`Quality & Integrity`) scans session transcripts and editor behavior for implicit frustration signals (such as rapid repeated file saves, failed compilation loops, or repeated prompts).

<details>
<summary>🔍 <b>Expand full answer</b></summary>
<br>

When 5+ rapid saves occur in 5 seconds or a build command fails twice, Tropelex flags a **Friction Zone**. This alerts team leads and AI agents to clarify underspecified requirements before developer fatigue sets in.
</details>

---

### <a id="what-is-an-agent-handoff-packet-and-when-should-i-use-it"></a>What is an Agent Handoff Packet and when should I use it?

An Agent Handoff Packet (`Team & Collaboration` -> `Agent Handoff`) is a role-tailored context bundle designed to transfer work from one specialized agent role to another (e.g., from `Architect` to `CoderAgent` or `TestEngineer`).

<details>
<summary>🔍 <b>Expand full answer</b></summary>
<br>

Instead of dumping raw context, the packet builder (`core/handoff/packet_builder.py`) filters decisions and requirements to match the receiving agent's role profile:
- **`CoderAgent`**: Receives function signatures, active API tasks, and structural guidelines.
- **`TestEngineer`**: Receives boundary conditions, failure cases, and assertion targets.
- **`DevOpsSpecialist`**: Receives deployment constraints, environment variables, and safety envelope limits.
</details>

---

### <a id="can-tropelex-share-rationale-and-knowledge-across-different-projects"></a>Can Tropelex share rationale and knowledge across different projects?

Yes. Tropelex includes a **Cross-Pollination Engine** (`core/rag.py`) that searches across multiple project memories to suggest proven architectural solutions and patterns from other repositories.

<details>
<summary>🔍 <b>Expand full answer</b></summary>
<br>

If you encounter a problem in project B (e.g., `"implement JWT auth with refresh tokens"`), Tropelex's semantic RAG engine checks project A's decision ledger and suggests identical, verified solutions that succeeded in past sessions.
</details>

---

### <a id="how-do-i-integrate-tropelex-with-emacs-or-vscode"></a>How do I integrate Tropelex with Emacs or VSCode?

Tropelex includes native integrations for Emacs (`emacs/tropelex-capture.el`) and VSCode extensions.

<details>
<summary>🔍 <b>Expand full answer</b></summary>
<br>

In Emacs:
- `C-c t c`: Capture active buffer / function as a decision.
- `C-c t r`: Capture selected region as decision context.
- `C-c t f`: Scan buffer for friction signals.
- `C-c t g`: Capture current git HEAD commit as a decision.
</details>

---

### <a id="how-do-i-rollback-memory-or-time-travel-to-a-previous-session"></a>How do I rollback memory or time-travel to a previous session?

Session Replay (`core/session_replay.py`) snapshots memory state at the start and end of every session, allowing you to view structured diffs or rollback project memory.

<details>
<summary>🔍 <b>Expand full answer</b></summary>
<br>

If an experimental session introduced unwanted or incorrect decisions into project memory:
1. Navigate to **Memory Lifecycle** -> **Session Replay**.
2. Click **diff** to inspect exact memory changes made during that session.
3. Click **Rollback** (`rollback_session()`) to restore project memory to the exact state before that session began.
</details>

---

### <a id="how-do-i-run-the-automated-pytest-suite-to-verify-system-health"></a>How do I run the automated Pytest suite to verify system health?

Per the Tropelex testing mandate, run `pytest` directly in your Linux/WSL terminal:

```bash
pytest tests/ -x -q
```

<details>
<summary>🔍 <b>Expand full answer</b></summary>
<br>

All 2,672 unit tests must pass before declaring features or bug fixes complete. Note: Last30Days engine tests consume external API tokens and are excluded by default; to run them explicitly, run `pytest -m last30days`.
</details>

---

## Need Further Help?
Launch the interactive web dashboard at `http://localhost:8766` and click **Getting Started** for live diagnostic self-tests and one-click CLI command copiers.
