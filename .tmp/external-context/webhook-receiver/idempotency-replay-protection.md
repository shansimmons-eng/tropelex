---
source: Community patterns + official docs
library: webhook-security
topic: Idempotency and replay protection
fetched: 2026-07-16T00:00:00Z
official_docs:
  - https://docs.gitlab.com/user/project/integrations/webhooks/
  - https://hookray.com/blog/webhook-retry-strategies-2026
---

# Idempotency & Replay Protection Patterns

## Why This Matters

Webhook providers guarantee **at-least-once** delivery. Your endpoint WILL receive duplicates.
Without idempotency, duplicates cause: duplicate charges, duplicate emails, duplicate git syncs.

## Idempotency Key Strategy

### Extract Provider Event ID
Each provider sends a unique delivery ID:

| Provider | Header/Field | Example |
|----------|-------------|---------|
| GitHub | `X-GitHub-Delivery` header | `"abc123"` |
| GitLab (19.0+) | `webhook-id` header (Standard Webhooks) | `"f5e5f430-f57b-4e6e-9fac-d9128cd7232f"` |
| GitLab (legacy) | `X-Gitlab-Webhook-UUID` header | `"02affd2d-2cba-4033-917d-ec22d5dc4b38"` |
| GitLab (legacy) | `Idempotency-Key` header (17.4+) | same as webhook-id |
| Stripe | `event.id` in payload | `"evt_1234"` |

### Idempotency Table Pattern
```sql
CREATE TABLE processed_webhook_events (
    event_id     TEXT PRIMARY KEY,
    provider     TEXT NOT NULL,
    event_type   TEXT NOT NULL,
    received_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ,
    status       TEXT NOT NULL DEFAULT 'pending',  -- pending/processing/completed/failed
    payload      JSONB,
    result       JSONB
);

-- TTL cleanup (keep 30 days)
CREATE INDEX idx_events_received ON processed_webhook_events(received_at);
```

### Handler Pattern (Atomic Dedup)
```python
import asyncpg
from datetime import datetime

async def handle_webhook(request: Request):
    # 1. Verify signature first
    body = await verify_signature(request)

    # 2. Extract event ID
    event_id = request.headers.get("X-GitHub-Delivery")  # GitHub
    # OR event_id = request.headers.get("webhook-id")     # GitLab

    # 3. Atomic insert — unique constraint prevents duplicates
    async with db.acquire() as conn:
        try:
            await conn.execute("""
                INSERT INTO processed_webhook_events (event_id, provider, event_type, payload, status)
                VALUES ($1, $2, $3, $4, 'processing')
            """, event_id, provider, event_type, json.dumps(body))
        except asyncpg.UniqueViolationError:
            # Duplicate! Already processed or being processed
            return {"status": "duplicate", "event_id": event_id}

    # 4. Return 200 IMMEDIATELY — process async
    # Don't do heavy work in the webhook handler!
    return {"status": "accepted"}

    # 5. Heavy processing happens async:
    # - Push to message queue
    # - Background worker picks up
    # - Updates status to 'completed' or 'failed'
```

### Build Your Own Event ID (When Provider Doesn't Provide One)
```python
import hashlib

def build_event_id(provider: str, event_type: str, payload: dict) -> str:
    """Create deterministic ID from stable payload fields."""
    stable_fields = f"{provider}:{event_type}:{payload.get('repository', {}).get('id', '')}:{payload.get('after', payload.get('head_commit', {}).get('id', ''))}"
    return hashlib.sha256(stable_fields.encode()).hexdigest()[:32]
```

## Replay Attack Protection

### What Is a Replay Attack?
An attacker captures a legitimate webhook request and resubmits it later.
Even with HMAC verification, the signature is still valid (shared secret hasn't changed).

### Protection: Timestamp Validation
Both GitHub and GitLab include timestamps for freshness checking.

#### GitHub
GitHub doesn't include a timestamp header directly, but you can implement:
```python
import time

MAX_WEBHOOK_AGE_SECONDS = 300  # 5 minutes

async def verify_github_with_timestamp(request: Request):
    # Verify HMAC signature
    await verify_github_signature(request)

    # Optional: reject if processing too old
    # (GitHub doesn't send timestamp, so use receipt time)
    # For stronger replay protection, combine with event_id dedup
```

#### GitLab (Standard Webhooks — Signing Token)
GitLab sends `webhook-timestamp` for built-in replay protection:
```python
import time

MAX_AGE_SECONDS = 300  # 5 minutes

def check_timestamp(timestamp_header: str) -> bool:
    """Reject webhooks older than MAX_AGE_SECONDS."""
    try:
        webhook_time = int(timestamp_header)
        current_time = int(time.time())
        age = abs(current_time - webhook_time)
        return age <= MAX_AGE_SECONDS
    except (ValueError, TypeError):
        return False
```

### Protection: Nonce-Based Dedup (Redis)
For providers without timestamps, store seen nonces:
```python
import redis
import time

redis_client = redis.Redis()
NONCE_TTL = 3600  # 1 hour

def check_and_store_nonce(event_id: str) -> bool:
    """Returns True if this is a NEW event (not a replay)."""
    # SET NX = set if not exists, returns True if key was new
    return redis_client.set(
        f"webhook:nonce:{event_id}",
        "1",
        nx=True,
        ex=NONCE_TTL
    )
```

## Complete Production Handler

```python
from fastapi import FastAPI, Request, HTTPException
import hmac, hashlib, json, time

app = FastAPI()

@app.post("/webhook/github")
async def github_webhook(request: Request):
    # === Step 1: Signature Verification ===
    signature_header = request.headers.get("X-Hub-Signature-256")
    raw_body = await request.body()

    if not signature_header:
        raise HTTPException(403, "Missing signature")

    sig_value = signature_header.removeprefix("sha256=")
    expected = hmac.new(
        os.environ["WEBHOOK_SECRET"].encode(),
        raw_body,
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(sig_value, expected):
        raise HTTPException(403, "Invalid signature")

    # === Step 2: Parse Event Type ===
    event_type = request.headers.get("X-GitHub-Event")
    event_id = request.headers.get("X-GitHub-Delivery")

    # Handle ping
    if event_type == "ping":
        return {"msg": "pong"}

    # === Step 3: Idempotency Check ===
    if not event_id:
        raise HTTPException(400, "Missing event ID")

    is_new = await check_and_store_nonce(event_id)
    if not is_new:
        return {"status": "duplicate"}

    # === Step 4: Enqueue for Async Processing ===
    payload = json.loads(raw_body)
    await message_queue.publish("github-events", {
        "event_id": event_id,
        "event_type": event_type,
        "payload": payload,
        "received_at": int(time.time())
    })

    # === Step 5: Return 200 Fast ===
    return {"status": "accepted"}
```

## Key Rules

1. **Return 200 immediately** — don't do heavy work in the webhook handler
2. **Verify signature FIRST** — before any other processing
3. **Use atomic dedup** — unique constraint on event_id, handle UniqueViolationError
4. **Store events for TTL** — 7-30 days, then cleanup
5. **Save processing result** — so duplicate requests get consistent response
6. **Timestamps for freshness** — reject webhooks older than 5 minutes
7. **Queue heavy work** — message queue + background workers
