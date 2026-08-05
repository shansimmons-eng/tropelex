---
description: Show Tropelex context for this project
---

Call `mcp__tropelex__list_projects` first, and match the current repository
directory name against the returned project names case-insensitively:
project names are case-sensitive server-side, so don't guess the directory
name's exact casing. If nothing matches clearly, ask which project to use.

Then call `mcp__tropelex__get_project_memory` for that project and summarize
what it returns for the user: past decisions and their rationale, session
summaries, learned patterns, and preferences, so this session starts with
the accumulated context instead of from scratch.
