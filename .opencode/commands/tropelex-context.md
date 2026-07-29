---
description: Show Tropelex context and project memory
agent: general
subtask: true
---

# Tropelex Context

Run these commands to see project memory:

**View project summary:**
```
curl http://localhost:8766/api/memory/tropelex
```

**View full context:**
```
curl http://localhost:8766/api/memory/tropelex/context
```

**View recent decisions:**
```
curl http://localhost:8766/api/memory/tropelex/decisions
```

**View insights:**
```
curl http://localhost:8766/api/memory/tropelex/insights
```