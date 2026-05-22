---
description: Record a decision in Tropelex memory
agent: general
subtask: true
---

Record this decision in the Tropelex memory system:

**Decision:** $ARGUMENTS

**Context:** Based on our recent discussion

Use this bash command to record it:
!`curl -s -X POST http://localhost:8766/api/memory/!$(basename $(pwd))/decisions -H "Content-Type: application/json" -d "{\"decision\":\"$ARGUMENTS\",\"context\":\"From OpenCode session\"}" && echo "✓ Decision recorded in Tropelex"`

After recording, continue with the task at hand.
