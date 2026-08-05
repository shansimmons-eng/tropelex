---
description: End session and trigger pattern learning
argument-hint: <summary>
---

Call `mcp__tropelex__list_projects` first, and match the current repository
directory name against the returned project names case-insensitively:
project names are case-sensitive server-side, so don't guess the directory
name's exact casing. If nothing matches clearly, ask which project to use.

Summarize what was accomplished in this session in one line (use $ARGUMENTS
if provided, otherwise write your own summary from the conversation), then
call the `mcp__tropelex__end_session` tool for that project with that summary
and `agent: "Claude"`: the agent name attributes this session so per-agent
skill and persona tracking has real data instead of everything landing under
"unspecified".

Confirm to the user once it's recorded.
