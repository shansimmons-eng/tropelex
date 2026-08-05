---
description: End session and trigger pattern learning
agent: general
subtask: true
---

Summarize what was accomplished in this session, then record it in Tropelex:

**Session Summary:** $ARGUMENTS

Use this bash command to record it (project inferred from the current
directory name; recorded under agent "OpenCode" so per-agent skill/persona
tracking has real data):
!`PROJECT=$(basename "$(pwd)" | tr '[:upper:]' '[:lower:]'); curl -s -X POST "http://localhost:8766/api/memory/$PROJECT/sessions/record" -H "Content-Type: application/json" -d "{\"summary\":\"$ARGUMENTS\",\"session_type\":\"manual\",\"agent_name\":\"OpenCode\"}" && echo "✓ Session recorded for project $PROJECT"`

The system will analyze this summary and learn patterns about:
- UI vs backend work
- Bug fixes vs new features
- Architecture decisions
- Performance/security considerations

Context has been updated for future sessions.
