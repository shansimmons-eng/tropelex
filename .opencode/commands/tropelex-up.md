---
description: Update Tropelex project memory
agent: general
subtask: true
---

# Tropelex Project Update

To update your project memory, run in terminal:

```bash
curl -s -X POST http://localhost:8766/api/memory -H "Content-Type: application/json" -d '{"project_name":"tropelex-test","description":"YOUR DESCRIPTION","tech_stack":["YOUR","TECH"]}'
```

**QuickStart Commands:**
- `/tropelex-show-context` — Load accumulated knowledge
- `/tropelex-record-decision` — Save a decision
- `/tropelex-end-session` — End session + learn patterns