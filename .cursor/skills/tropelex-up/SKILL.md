---
name: tropelex-up
description: Register a new project with Tropelex, setting its description and tech stack. Use when the user asks to set up, register, or initialize Tropelex tracking for the current project.
---

If an MCP connection to the Tropelex server ("tropelex") is available, call
its `list_projects` tool first, and match the current repository directory
name against the returned project names case-insensitively. If a matching
project already exists, tell the user it's already registered and stop --
don't re-create it. (Note: `capture_decision` and `end_session` already
auto-create a project on first use if it doesn't exist yet, just without a
description or tech stack -- this skill is specifically for setting those
up properly instead of leaving them blank.)

If no matching project exists, there's no tool for project creation with
metadata, so use the REST API directly regardless of whether an MCP
connection exists:

```bash
DIRNAME=$(basename "$(pwd)")
BODY=$(jq -n --arg n "$DIRNAME" --arg d "<description>" --argjson t '["<tech>", "<stack>"]' \
  '{project_name:$n,description:$d,tech_stack:$t}')
curl -s -X POST http://localhost:8766/api/memory -H "Content-Type: application/json" -d "$BODY"
```

If the user didn't supply a description or tech stack, infer reasonable
values from the project's actual files (package.json, requirements.txt,
pyproject.toml, etc.) rather than asking them to type something you can
already see.

Confirm to the user once the project is created, and mention the
show-context, record-decision, and end-session skills as what they'll use
from here.
