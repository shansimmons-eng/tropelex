---
name: tropelex-record-decision
description: Record a decision (what was decided and why) into Tropelex's persistent project memory. Use when the user asks to save, log, capture, or record a decision, or after making a significant architectural or design choice worth remembering.
---

If an MCP connection to the Tropelex server ("tropelex") is available, call
its `list_projects` tool first, and match the current repository directory
name against the returned project names case-insensitively: project names
are case-sensitive server-side, so don't guess the directory name's exact
casing. If nothing matches clearly, ask which project to use.

Record the decision using the `capture_decision` tool for that project,
with `decision` (what was decided) and `context` (why, optional but
recommended). `safety_category` is required by the tool; if you omit it the
call is rejected with a suggested category attached -- read it and either
accept (retry with it) or override with a better-fitting one. After
recording, confirm briefly and continue with the task at hand.

If no MCP connection to Tropelex is configured, fall back to the REST API
directly (project resolved the same case-insensitive way as above; body
built with `jq --arg` so a decision containing a quote doesn't corrupt the
request):

```bash
BODY=$(jq -n --arg d "<decision>" --arg c "<context>" '{decision:$d,context:$c}')
curl -s -X POST "http://localhost:8766/api/memory/<resolved_project_name>/decisions" \
  -H "Content-Type: application/json" -d "$BODY"
```
