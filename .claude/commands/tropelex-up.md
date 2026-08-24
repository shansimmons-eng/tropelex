---
description: Register a new project with Tropelex (description + tech stack)
argument-hint: <description> | <tech,stack,items>
---

Call `mcp__tropelex__list_projects` first, and match the current repository
directory name against the returned project names case-insensitively:
project names are case-sensitive server-side, so don't guess the directory
name's exact casing.

If a matching project already exists, tell the user it's already registered
and stop — don't re-create it. (Note: `capture_decision` and `end_session`
already auto-create a project on first use if it doesn't exist yet, just
without a description or tech stack. This command is specifically for
setting those up properly instead of leaving them blank.)

If no matching project exists: there's no MCP tool for project creation
with metadata, so use the REST API directly.

**Input:** $ARGUMENTS

Split on the first `|`: the part before is `description`, the part after
(if present) is a comma-separated `tech_stack` list. If there's no `|`,
treat the whole input as `description` and leave `tech_stack` empty. If
$ARGUMENTS is empty, infer a reasonable description and tech stack from the
project's actual files (package.json, requirements.txt, pyproject.toml,
etc.) rather than asking the user to type something you can already see.

Run (project name is the current directory's basename; body built with `jq
--arg` so a description containing a quote doesn't corrupt the request —
requires `jq` on PATH):

```bash
DIRNAME=$(basename "$(pwd)")
BODY=$(jq -n --arg n "$DIRNAME" --arg d "DESCRIPTION_HERE" --argjson t '["TECH","STACK"]' \
  '{project_name:$n,description:$d,tech_stack:$t}')
curl -s -X POST http://localhost:8766/api/memory -H "Content-Type: application/json" -d "$BODY"
```

Substitute the real description/tech_stack values before running it. Confirm
to the user once the project is created, and mention `/tropelex-show-context`,
`/tropelex-record-decision`, and `/tropelex-end-session` as the commands
they'll use from here.
