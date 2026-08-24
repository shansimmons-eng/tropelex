---
name: tropelex-end-session
description: End the current work session and record a summary in Tropelex for pattern learning and session history. Use when the user asks to end/close/wrap up the session, or wants to record what was accomplished.
---

If an MCP connection to the Tropelex server ("tropelex") is available, call
its `list_projects` tool first, and match the current repository directory
name against the returned project names case-insensitively: project names
are case-sensitive server-side, so don't guess the directory name's exact
casing. If nothing matches clearly, ask which project to use.

Summarize what was accomplished in this session in one line, then call the
`end_session` tool for that project with that summary and `agent` set to
your own name (e.g. "Cursor", "Codex") -- the agent name attributes this
session so per-agent skill and persona tracking has real data instead of
everything landing under "unspecified".

Confirm to the user once it's recorded.

If no MCP connection to Tropelex is configured, fall back to the REST API
directly (project resolved the same case-insensitive way as above; body
built with `jq --arg` so a summary containing a quote doesn't corrupt the
request):

```bash
BODY=$(jq -n --arg s "<summary>" --arg a "<your agent name>" '{summary:$s,session_type:"manual",agent_name:$a}')
curl -s -X POST "http://localhost:8766/api/memory/<resolved_project_name>/sessions/record" \
  -H "Content-Type: application/json" -d "$BODY"
```
