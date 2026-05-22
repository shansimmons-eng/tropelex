---
description: Show Tropelex context for this project
agent: general
subtask: true
---

Here is the accumulated knowledge from Tropelex for this project:

!`curl -s http://localhost:8766/api/memory/!$(basename $(pwd))/context | python3 -c "import sys, json; data = json.load(sys.stdin); print(data.get('context', 'No context available'))" 2>/dev/null || echo "Tropelex server not reachable"`

This context includes:
- Past decisions and their rationale
- Session summaries
- Learned patterns
- Tech stack choices
- User preferences

This context is automatically injected into new sessions to maintain continuity.
