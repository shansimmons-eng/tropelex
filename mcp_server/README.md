# Tropelex MCP Server

Exposes Tropelex's decision-memory system as MCP tools, so any MCP-capable
agent (Claude Code, Cursor, Claude Desktop, whatever) can read and write
project memory directly, the same way the OpenCode plugin, VSCode extension,
and Emacs package already do over Tropelex's REST API.

This turns Tropelex from "needs a bespoke integration per editor" into
something any MCP client can talk to natively.

## Why a separate venv

Tropelex's own server runs on the system Python with no venv. This server
lives in its own `mcp_server/.venv` instead of touching that environment:
neither project's dependencies leak into the other, and `mcp_server/.venv`
is gitignored (matches the repo's existing `.venv/` pattern).

## Setup

```bash
cd mcp_server
uv venv .venv                              # or: python3 -m venv .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

## Register with Claude Code

```bash
claude mcp add tropelex -- /path/to/Tropelex/mcp_server/.venv/bin/python /path/to/Tropelex/mcp_server/server.py
```

Requires the main Tropelex server to be running (`python3 -m core.tropebook.web.server`
from the repo root, default `http://localhost:8766`). Point at a different
instance with the `TROPELEX_URL` environment variable.

## Tools

| Tool | Wraps |
|---|---|
| `list_projects` | `GET /api/memory` |
| `get_project_memory` | `GET /api/memory/{project}` |
| `capture_decision` | `POST /api/memory/{project}/decisions` |
| `end_session` | `POST /api/memory/{project}/sessions/record` |
| `get_context_bundle` | `POST /api/memory/{project}/prefetch` |
| `check_contradictions` | `GET /api/memory/{project}/contradictions` |
| `check_diff_for_conflicts` | `POST /api/memory/{project}/ghost-check` |
| `friction_scan` | `POST /api/memory/{project}/friction/scan` |
| `record_skill_outcome` | `POST /api/memory/{project}/agent-skills/record` |
| `get_handoff_packet` | `POST /api/memory/{project}/handoff` |
| `explain_why` | `POST /api/memory/{project}/explain` |

This is a curated subset of Tropelex's 150+ REST endpoints: the ones most
useful for an agent operating mid-session. Add more by following the same
pattern in `server.py`: a thin `@mcp.tool()` wrapper around `_request()`.

`end_session`, `friction_scan`, and `record_skill_outcome` all take an
`agent` argument: pass your own name (e.g. `"Claude"`, `"Cursor"`,
`"Gemini"`) so per-agent skill and persona tracking has real data instead of
everything landing under `"unspecified"`.

## Tests

```bash
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/python -m pytest test_server.py -v
```

Tests monkeypatch `_request` to verify each tool builds the right REST call
(method, path, body); no live server needed.
