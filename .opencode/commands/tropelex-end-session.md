---
description: End session and trigger pattern learning
agent: general
subtask: true
---

Summarize what was accomplished in this session, then record it in Tropelex:

**Session Summary:** $ARGUMENTS

Use this bash command to record it (project resolved case-insensitively
against real projects, falling back to the raw directory name for a new
one -- project names are case-sensitive server-side, so force-lowercasing
an existing mixed-case project would silently fork a phantom duplicate
instead of updating it; recorded under agent "OpenCode" so per-agent
skill/persona tracking has real data; the JSON body is built with `jq
--arg` rather than raw string interpolation so a summary containing a
quote character doesn't corrupt the request -- requires `jq` on PATH):
!`DIRNAME=$(basename "$(pwd)"); PROJECT=$(curl -s "http://localhost:8766/api/memory" | python3 -c "import sys,json; d='$DIRNAME'.lower(); names=[p['name'] for p in json.load(sys.stdin).get('projects',[])]; print(next((n for n in names if n.lower()==d), '$DIRNAME'))" 2>/dev/null || echo "$DIRNAME"); BODY=$(jq -n --arg s "$ARGUMENTS" --arg a "OpenCode" '{summary:$s,session_type:"manual",agent_name:$a}'); curl -s -X POST "http://localhost:8766/api/memory/$PROJECT/sessions/record" -H "Content-Type: application/json" -d "$BODY" && echo "✓ Session recorded for project $PROJECT"`

The system will analyze this summary and learn patterns about:
- UI vs backend work
- Bug fixes vs new features
- Architecture decisions
- Performance/security considerations

Context has been updated for future sessions.
