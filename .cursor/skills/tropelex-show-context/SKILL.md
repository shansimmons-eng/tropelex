---
name: tropelex-show-context
description: Show Tropelex's accumulated context (decisions, sessions, patterns, preferences) for the current project. Use when starting work on a project tracked by Tropelex, or when the user asks to load/show project context or memory.
---

If an MCP connection to the Tropelex server ("tropelex") is available, call
its `list_projects` tool first, and match the current repository directory
name against the returned project names case-insensitively: project names
are case-sensitive server-side, so don't guess the directory name's exact
casing. If nothing matches clearly, ask which project to use.

Then call the `get_project_memory` tool for that project and summarize what
it returns for the user: past decisions and their rationale, session
summaries, learned patterns, and preferences, so this session starts with
the accumulated context instead of from scratch.

If no MCP connection to Tropelex is configured, fall back to the REST API
directly:

```bash
curl -s "http://localhost:8766/api/memory" | python3 -c "
import sys, json
d = 'CURRENT_DIRECTORY_BASENAME'.lower()
names = [p['name'] for p in json.load(sys.stdin).get('projects', [])]
print(next((n for n in names if n.lower() == d), 'CURRENT_DIRECTORY_BASENAME'))
"
curl -s "http://localhost:8766/api/memory/<resolved_project_name>/context"
```
