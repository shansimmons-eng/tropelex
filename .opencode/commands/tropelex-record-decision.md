---
description: Record a decision in Tropelex memory
agent: general
subtask: true
---

Record this decision in the Tropelex memory system:

**Decision:** $ARGUMENTS

**Context:** Based on our recent discussion

Use this bash command to record it (project resolved case-insensitively
against real projects, falling back to the raw directory name for a new
one -- project names are case-sensitive server-side, so force-lowercasing
an existing mixed-case project would silently fork a phantom duplicate
instead of updating it; the JSON body is built with `jq --arg` rather
than raw string interpolation so a decision containing a quote character
doesn't corrupt the request -- requires `jq` on PATH):
!`DIRNAME=$(basename "$(pwd)"); PROJECT=$(curl -s "http://localhost:8766/api/memory" | python3 -c "import sys,json; d='$DIRNAME'.lower(); names=[p['name'] for p in json.load(sys.stdin).get('projects',[])]; print(next((n for n in names if n.lower()==d), '$DIRNAME'))" 2>/dev/null || echo "$DIRNAME"); BODY=$(jq -n --arg d "$ARGUMENTS" --arg c "From OpenCode session" '{decision:$d,context:$c}'); curl -s -X POST "http://localhost:8766/api/memory/$PROJECT/decisions" -H "Content-Type: application/json" -d "$BODY" && echo "✓ Decision recorded for project $PROJECT"`

After recording, continue with the task at hand.
