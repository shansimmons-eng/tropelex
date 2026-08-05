# Tropelex TUI

A terminal dashboard for Tropelex, for anyone who lives in tmux rather than
an editor. Browse projects, read decision history, and capture new decisions
without leaving the terminal, over the same REST API the web dashboard,
VSCode extension, and Emacs package all share.

## Setup

```bash
cd tui
uv venv .venv                              # or: python3 -m venv .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

Requires the main Tropelex server running (`python3 -m core.tropebook.web.server`
from the repo root, default `http://localhost:8766`). Point at a different
instance with the `TROPELEX_URL` environment variable.

## Run

```bash
.venv/bin/python app.py
```

## Keybindings

| Key | Action |
|---|---|
| ↑ / ↓ | Move between projects (sidebar) or decisions (table) |
| Enter | Select a project |
| `a` | Capture a new decision (opens a modal: decision text + optional context) |
| `r` | Refresh the current view |
| `q` | Quit |

## What it shows

- **Sidebar**: every project, loaded from `GET /api/memory`.
- **Decision table**: the selected project's decisions, most recent first, with confidence tier.
- **Status bar**: decision count and unresolved contradiction count for the selected project.

This is a first pass, not a port of the full web dashboard; it covers the
core terminal-first loop (browse, capture) rather than all 40+ features.
`client.py` is a thin wrapper around the REST API; extending it with more
views (contradictions, friction, health) follows the same pattern as
`select_project()` in `app.py`.
