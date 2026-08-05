---
description: Record a decision in Tropelex memory
argument-hint: <what> | <why>
---

Call `mcp__tropelex__list_projects` first, and match the current repository
directory name against the returned project names case-insensitively:
project names are case-sensitive server-side, so don't guess the directory
name's exact casing. If nothing matches clearly, ask which project to use.

Record this decision in Tropelex using the `mcp__tropelex__capture_decision`
tool for that project.

**Input:** $ARGUMENTS

Split the input on the first `|`: the part before is the `decision` argument,
the part after (if present) is the `context` argument. If there's no `|`, pass
the whole input as `decision` and leave `context` empty. After recording,
confirm briefly and continue with the task at hand.
