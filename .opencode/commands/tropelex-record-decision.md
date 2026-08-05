---
description: Record a decision in Tropelex memory
agent: general
subtask: true
---

Record this decision in the Tropelex memory system:

**Decision:** $ARGUMENTS

**Context:** Based on our recent discussion

Use this bash command to record it (project inferred from the current directory name):
!`PROJECT=$(basename "$(pwd)" | tr '[:upper:]' '[:lower:]'); curl -s -X POST "http://localhost:8766/api/memory/$PROJECT/decisions" -H "Content-Type: application/json" -d "{\"decision\":\"$ARGUMENTS\",\"context\":\"From OpenCode session\"}" && echo "✓ Decision recorded for project $PROJECT"`

After recording, continue with the task at hand.
