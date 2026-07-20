---
source: Community patterns + best practices
library: webhook-security
topic: Webhook payload validation
fetched: 2026-07-16T00:00:00Z
official_docs:
  - https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries
---

# Webhook Payload Validation Patterns

## Validation Pipeline (In Order)

```
Request arrives
    │
    ▼
1. Check Content-Type header
    │
    ▼
2. Check signature header exists
    │
    ▼
3. Read RAW body (bytes) — BEFORE any parsing
    │
    ▼
4. Verify HMAC-SHA256 signature ← CRITICAL STEP
    │
    ▼
5. Check event type / action
    │
    ▼
6. Parse JSON payload
    │
    ▼
7. Validate required fields
    │
    ▼
8. Check idempotency (event_id dedup)
    │
    ▼
9. Process event
```

## Content-Type Validation
```python
from fastapi import Request, HTTPException

async def validate_content_type(request: Request):
    content_type = request.headers.get("Content-Type", "")
    if "application/json" not in content_type:
        raise HTTPException(400, f"Expected application/json, got {content_type}")
```

## Raw Body Preservation

**CRITICAL**: Always read the body as raw bytes BEFORE any framework parsing.

### FastAPI
```python
@app.post("/webhook")
async def webhook(request: Request):
    raw_body = await request.body()  # Returns bytes — use this for HMAC
    # Later, if needed:
    # payload = await request.json()  # DON'T use for HMAC!
```

### Flask
```python
@app.route("/webhook", methods=["POST"])
def webhook():
    raw_body = request.get_data()  # Returns bytes — use this for HMAC
    # Later:
    # payload = request.get_json()
```

### Express/Node.js
```javascript
// CRITICAL: Capture raw body BEFORE express.json() parses it
const express = require('express');
const app = express();

// Capture raw body for signature verification
app.use(express.json({
  verify: (req, res, buf) => {
    req.rawBody = buf;  // Store raw buffer
  }
}));

app.post('/webhook', (req, res) => {
  const rawBody = req.rawBody;  // Use this for HMAC
  // req.body is parsed JSON
});
```

### Common Mistake
```python
# WRONG — parsed JSON is NOT the same bytes the provider signed
payload = await request.json()  # ❌ DON'T use for HMAC
body_bytes = json.dumps(payload).encode()  # ❌ Key order may differ!

# CORRECT — raw bytes as received
raw_body = await request.body()  # ✅ Exactly what provider signed
```

## Event Type Validation

### GitHub
```python
async def handle_github_webhook(request: Request):
    event_type = request.headers.get("X-GitHub-Event")

    match event_type:
        case "push":
            return await handle_push(request)
        case "ping":
            return {"msg": "pong"}
        case "pull_request":
            return await handle_pr(request)
        case "issues":
            return await handle_issue(request)
        case _:
            logger.info(f"Ignoring GitHub event: {event_type}")
            return {"status": "ignored"}
```

### GitLab
```python
async def handle_gitlab_webhook(request: Request):
    event_type = request.headers.get("X-Gitlab-Event")

    match event_type:
        case "Push Hook":
            return await handle_push(request)
        case "Merge Request Hook":
            return await handle_mr(request)
        case "Tag Push Hook":
            return await handle_tag(request)
        case _:
            logger.info(f"Ignoring GitLab event: {event_type}")
            return {"status": "ignored"}
```

## Required Field Validation

### Use Pydantic for Structured Validation
```python
from pydantic import BaseModel, Field
from typing import Optional, List

class CommitAuthor(BaseModel):
    name: str
    email: str
    username: Optional[str] = None

class Commit(BaseModel):
    id: str = Field(..., min_length=40, max_length=40)  # SHA-1 or SHA-256
    message: str
    timestamp: Optional[str] = None
    url: Optional[str] = None
    author: Optional[CommitAuthor] = None
    added: List[str] = Field(default_factory=list)
    modified: List[str] = Field(default_factory=list)
    removed: List[str] = Field(default_factory=list)

class Repository(BaseModel):
    id: int
    name: str
    full_name: Optional[str] = None
    clone_url: Optional[str] = None
    ssh_url: Optional[str] = None
    default_branch: Optional[str] = None

class PushPayload(BaseModel):
    ref: str
    before: str
    after: str
    repository: Repository
    commits: List[Commit] = Field(default_factory=list)
    head_commit: Optional[Commit] = None
    forced: bool = False
    created: bool = False
    deleted: bool = False

# Usage:
try:
    payload = PushPayload.model_validate(raw_json)
except ValidationError as e:
    raise HTTPException(400, detail=f"Invalid payload: {e}")
```

## Branch Name Sanitization

```python
def sanitize_branch_name(ref: str) -> str:
    """Extract and sanitize branch name from ref."""
    if ref.startswith("refs/heads/"):
        branch = ref[len("refs/heads/"):]
    elif ref.startswith("refs/tags/"):
        branch = ref[len("refs/tags/"):]
    else:
        branch = ref

    # Validate no path traversal
    if ".." in branch or branch.startswith("-"):
        raise ValueError(f"Invalid branch name: {branch}")

    return branch
```

## Complete Validation Function

```python
from fastapi import Request, HTTPException
import hmac, hashlib, json, os

async def validate_webhook_request(request: Request) -> tuple[str, dict]:
    """
    Validate incoming webhook request.
    Returns (event_type, payload).
    Raises HTTPException on validation failure.
    """
    # 1. Content-Type
    content_type = request.headers.get("Content-Type", "")
    if "application/json" not in content_type:
        raise HTTPException(400, "Invalid Content-Type")

    # 2. Detect provider
    is_github = "X-Hub-Signature-256" in request.headers
    is_gitlab = "X-Gitlab-Event" in request.headers

    if not (is_github or is_gitlab):
        raise HTTPException(400, "Unknown webhook provider")

    # 3. Raw body (MUST be before any parsing)
    raw_body = await request.body()
    if not raw_body:
        raise HTTPException(400, "Empty body")

    # 4. Signature verification
    if is_github:
        await verify_github_signature(raw_body, request)
        event_type = request.headers.get("X-GitHub-Event", "unknown")
    else:
        await verify_gitlab_signature(raw_body, request)
        event_type = request.headers.get("X-Gitlab-Event", "unknown")

    # 5. Parse JSON
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"Invalid JSON: {e}")

    # 6. Basic field validation
    if not isinstance(payload, dict):
        raise HTTPException(400, "Payload must be a JSON object")

    if "ref" not in payload:
        raise HTTPException(400, "Missing 'ref' field in push event")

    return event_type, payload
```

## Rate Limiting

```python
from collections import defaultdict
import time

class RateLimiter:
    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = window_seconds
        self.requests = defaultdict(list)

    def is_allowed(self, client_id: str) -> bool:
        now = time.time()
        cutoff = now - self.window

        # Clean old entries
        self.requests[client_id] = [
            t for t in self.requests[client_id] if t > cutoff
        ]

        if len(self.requests[client_id]) >= self.max_requests:
            return False

        self.requests[client_id].append(now)
        return True

rate_limiter = RateLimiter(max_requests=100, window_seconds=60)

@app.post("/webhook")
async def webhook(request: Request):
    client_ip = request.client.host
    if not rate_limiter.is_allowed(client_ip):
        raise HTTPException(429, "Rate limit exceeded")
    # ... rest of handler
```

## Common Validation Pitfalls

1. **Proxy/header modification** — load balancers may strip or add headers
2. **Encoding issues** — always use UTF-8
3. **JSON key ordering** — never re-serialize and compare; always use raw bytes
4. **Middleware parsing** — ensure framework doesn't consume body before your handler
5. **Large payloads** — set reasonable body size limits (GitHub: 25MB)
6. **Unicode** — webhook payloads can contain unicode characters
7. **Empty commits** — GitLab: new branch with no commits → empty commits array
