---
description: Show Tropelex context and project memory
agent: general
subtask: true
---

# Tropelex Context

Run these commands to see project memory:

**View project summary:**
```
curl http://localhost:8766/api/memory/$(basename $(pwd))
```

**View full context:**
```
curl http://localhost:8766/api/memory/$(basename $(pwd))/context
```

**View recent decisions:**
```
curl http://localhost:8766/api/memory/$(basename $(pwd))/decisions
```

**View insights:**
```
curl http://localhost:8766/api/memory/$(basename $(pwd))/insights
```