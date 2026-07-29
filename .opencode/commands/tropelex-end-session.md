---
description: End session and trigger pattern learning
agent: general
subtask: true
---

Summarize what was accomplished in this session, then record it in Tropelex:

**Session Summary:** $ARGUMENTS

Use this bash command to record and trigger pattern learning:
!`curl -s -X POST http://localhost:8766/api/memory/tropelex/sessions -H "Content-Type: application/json" -d "{\"summary\":\"$ARGUMENTS\"}" && echo "✓ Session recorded - patterns learned"`

The system will analyze this summary and learn patterns about:
- UI vs backend work
- Bug fixes vs new features
- Architecture decisions
- Performance/security considerations

Context has been updated for future sessions.
