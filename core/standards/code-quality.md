<!-- Context: standards/code | Priority: critical | Version: 2.0 | Updated: 2025-01-21 -->
# Code Standards

## Quick Reference

**Core Philosophy**: Modular, Functional, Maintainable
**Golden Rule**: If you can't easily test it, refactor it

**Critical Patterns** (use these):
- ✅ Pure functions (same input = same output, no side effects)
- ✅ Immutability (create new data, don't modify)
- ✅ Composition (build complex from simple)
- ✅ Small functions (< 50 lines)
- ✅ Explicit dependencies (dependency injection)

**Anti-Patterns** (avoid these):
- ❌ Mutation, side effects, deep nesting
- ❌ God modules, global state, large functions

---

## Core Philosophy

**Modular**: Everything is a component - small, focused, reusable
**Functional**: Pure functions, immutability, composition over inheritance
**Maintainable**: Self-documenting, testable, predictable

## Principles

### Modular Design
- Single responsibility per module
- Clear interfaces (explicit inputs/outputs)
- Independent and composable
- < 100 lines per component (ideally < 50)

### Functional Approach
- **Pure functions**: Same input = same output, no side effects
- **Immutability**: Create new data, don't modify existing
- **Composition**: Build complex from simple functions
- **Declarative**: Describe what, not how

### Component Structure
```
component/
├── index.js      # Public interface
├── core.js       # Core logic (pure functions)
├── utils.js      # Helpers
└── tests/        # Tests
```

## Patterns

### Pure Functions
```javascript
// ✅ Pure
const add = (a, b) => a + b;
const formatUser = (user) => ({ ...user, fullName: `${user.firstName} ${user.lastName}` });

// ❌ Impure (side effects)
let total = 0;
const addToTotal = (value) => { total += value; return total; };
```

### Immutability
```javascript
// ✅ Immutable
const addItem = (items, item) => [...items, item];
const updateUser = (user, changes) => ({ ...user, ...changes });

// ❌ Mutable
const addItem = (items, item) => { items.push(item); return items; };
```

### Composition
```javascript
// ✅ Compose small functions
const processUser = pipe(validateUser, enrichUserData, saveUser);
const isValidEmail = (email) => validateEmail(normalizeEmail(email));

// ❌ Deep inheritance
class ExtendedUserManagerWithValidation extends UserManager { }
```

### Declarative
```javascript
// ✅ Declarative
const activeUsers = users.filter(u => u.isActive).map(u => u.name);

// ❌ Imperative
const names = [];
for (let i = 0; i < users.length; i++) {
  if (users[i].isActive) names.push(users[i].name);
}
```

## Naming

- **Files**: lowercase-with-dashes.js
- **Functions**: verbPhrases (getUser, validateEmail)
- **Predicates**: isValid, hasPermission, canAccess
- **Variables**: descriptive (userCount not uc), const by default
- **Constants**: UPPER_SNAKE_CASE

## Error Handling (CRITICAL — enforced on all new code)

**Philosophy**: Errors are data, not control flow. Every function that can fail must communicate failure explicitly. Never silently swallow exceptions.

### Result Type Pattern (Preferred for business logic)
```python
from dataclasses import dataclass
from typing import Generic, TypeVar, Union

T = TypeVar("T")

@dataclass(frozen=True)
class Ok(Generic[T]):
    value: T

@dataclass(frozen=True)
class Err:
    error: str
    code: str = "UNKNOWN"
    details: dict | None = None

Result = Union[Ok, Err]

# ✅ Business logic returns Result, never raises
def analyze_decision(decision: dict, tree: DecisionTree) -> Result:
    if not decision.get("id"):
        return Err(error="Missing decision id", code="VALIDATION_ERROR")
    try:
        chain = tree.get_ancestors(decision["id"])
        return Ok(value={"chain": chain, "depth": len(chain)})
    except KeyError:
        return Err(error=f"Decision {decision['id']} not found", code="NOT_FOUND")
```

### Exception Hierarchy (For infrastructure/IO boundaries)
```python
# ✅ Define domain exceptions — never raise bare Exception/RuntimeError
class TropelexError(Exception):
    """Base for all Tropelex errors."""
    def __init__(self, message: str, code: str = "UNKNOWN", details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}

class MemoryError(TropelexError): ...
class GraphError(TropelexError): ...
class ValidationError(TropelexError): ...
class ResearchError(TropelexError): ...
class ConfigError(TropelexError): ...

# ✅ Raise specific exceptions at IO boundaries
def load_memory(path: Path) -> dict:
    if not path.exists():
        raise MemoryError(f"Memory file not found: {path}", code="NOT_FOUND")
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise MemoryError(f"Corrupt memory file: {path}", code="CORRUPT", details={"line": e.lineno})
```

### FastAPI Router Error Handling
```python
from fastapi import HTTPException

# ✅ Routers translate domain errors to HTTP — business logic never knows about HTTP
@router.get("/api/memory/{project}/ghost-decisions")
async def get_ghost_decisions(project: str):
    result = detect_ghosts(project)
    if isinstance(result, Err):
        if result.code == "NOT_FOUND":
            raise HTTPException(status_code=404, detail=result.error)
        raise HTTPException(status_code=500, detail=result.error)
    return result.value

# ✅ Alternative: exception handler middleware for consistent error responses
@app.exception_handler(TropelexError)
async def tropelex_error_handler(request, exc: TropelexError):
    status_map = {"NOT_FOUND": 404, "VALIDATION_ERROR": 422, "CORRUPT": 500}
    status = status_map.get(exc.code, 500)
    return JSONResponse(status_code=status, content={
        "error": str(exc), "code": exc.code, "details": exc.details
    })
```

### Defensive Programming Rules
```python
# ✅ Guard clauses — fail fast, fail clearly
def process_decision(decision: dict | None) -> Result:
    if decision is None:
        return Err(error="Decision cannot be None", code="VALIDATION_ERROR")
    if not isinstance(decision, dict):
        return Err(error=f"Expected dict, got {type(decision).__name__}", code="TYPE_ERROR")
    if "id" not in decision:
        return Err(error="Decision missing 'id' field", code="VALIDATION_ERROR")
    # ... proceed with confidence

# ✅ Never catch and silently pass
# ❌ except Exception: pass
# ❌ except Exception: return {}
# ❌ try: ... except: ...

# ✅ Always log or transform when catching
try:
    result = await external_api.call()
except ConnectionError as e:
    logger.warning(f"External API unavailable: {e}")
    return Err(error="Service temporarily unavailable", code="SERVICE_UNAVAILABLE")
except TimeoutError as e:
    logger.error(f"External API timeout after {timeout}s: {e}")
    return Err(error="Request timed out", code="TIMEOUT")
```

### Input Validation (At Every Boundary)
```python
from pydantic import BaseModel, Field, field_validator

# ✅ Pydantic models for API/external boundaries
class GhostDecisionRequest(BaseModel):
    project: str = Field(..., min_length=1, max_length=100)
    lookback_days: int = Field(default=30, ge=1, le=365)
    
    @field_validator("project")
    @classmethod
    def alphanumeric_with_hyphens(cls, v: str) -> str:
        if not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError(f"Project name must be alphanumeric (hyphens/underscores ok), got: {v}")
        return v

# ✅ Validate file/data at load time, not use time
def load_decisions(path: Path) -> list[dict]:
    raw = json.loads(path.read_text())
    if not isinstance(raw, list):
        raise ValidationError(f"Expected list, got {type(raw).__name__}")
    for i, item in enumerate(raw):
        if not isinstance(item, dict) or "id" not in item:
            raise ValidationError(f"Decision at index {i} missing required 'id' field")
    return raw
```

### Test Error Cases (Every error path must be tested)
```python
# ✅ Test both success AND failure paths
def test_analyze_decision_missing_id():
    result = analyze_decision({"text": "chose FastAPI"}, mock_tree)
    assert isinstance(result, Err)
    assert result.code == "VALIDATION_ERROR"

def test_analyze_decision_not_found():
    result = analyze_decision({"id": "nonexistent"}, mock_tree)
    assert isinstance(result, Err)
    assert result.code == "NOT_FOUND"

def test_analyze_decision_success():
    result = analyze_decision({"id": "d1"}, mock_tree)
    assert isinstance(result, Ok)
    assert "chain" in result.value
```

### Checklist (enforced on all new code)
- [ ] Every function that can fail returns `Result` or raises a domain exception
- [ ] No bare `except:` or `except Exception:` without logging/transforming
- [ ] No silent failures (`pass`, `return {}`, `return None` without reason)
- [ ] Input validated at every boundary (API, file, external call)
- [ ] Domain exceptions defined, not generic RuntimeError
- [ ] Routers translate domain errors to HTTP status codes
- [ ] Error test cases cover every failure branch
- [ ] Error messages are actionable (include what failed, why, and context)

## Dependency Injection

```javascript
// ✅ Dependencies explicit
function createUserService(database, logger) {
  return {
    createUser: (userData) => {
      logger.info('Creating user');
      return database.insert('users', userData);
    }
  };
}

// ❌ Hidden dependencies
import db from './database.js';
function createUser(userData) { return db.insert('users', userData); }
```

## Anti-Patterns

❌ **Mutation**: Modifying data in place
❌ **Side effects**: console.log, API calls in pure functions
❌ **Deep nesting**: Use early returns instead
❌ **God modules**: Split into focused modules
❌ **Global state**: Pass dependencies explicitly
❌ **Large functions**: Keep < 50 lines

## Best Practices

✅ Pure functions whenever possible
✅ Immutable data structures
✅ Small, focused functions (< 50 lines)
✅ Compose small functions into larger ones
✅ Explicit dependencies (dependency injection)
✅ Validate at boundaries
✅ Self-documenting code
✅ Test in isolation

**Golden Rule**: If you can't easily test it, refactor it.
