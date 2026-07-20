---
source: Community patterns + provider docs
library: webhook-reliability
topic: Retry strategies for webhook delivery
fetched: 2026-07-16T00:00:00Z
official_docs:
  - https://hookray.com/blog/webhook-retry-strategies-2026
  - https://www.webhookvault.com/blog/webhook-retry-strategies
---

# Webhook Retry Strategies

## Provider Retry Behavior (Sender Side)

When YOUR system SENDS webhooks, understand these defaults:

| Provider | Max Retries | Duration | Strategy |
|----------|------------|----------|----------|
| Stripe | 17 attempts | 3 days | Exponential backoff |
| GitHub | 3-5 attempts | ~10 hours | Exponential backoff |
| GitLab | varies | configurable | Exponential backoff |
| Shopify | 19 attempts | 48 hours | Exponential backoff |

## Exponential Backoff with Jitter

### The Thundering Herd Problem
When many webhooks fail simultaneously (e.g., server restart), pure exponential backoff causes ALL retries to hit at the same time → cascading failure.

### Solution: Jitter
```typescript
interface RetryConfig {
  baseDelayMs: number;    // e.g., 1000 (1 second)
  maxDelayMs: number;     // e.g., 3600000 (1 hour)
  maxAttempts: number;    // e.g., 10
  jitterStrategy: 'full' | 'equal' | 'decorrelated';
}

function calculateRetryDelay(attempt: number, config: RetryConfig): number {
  const exponentialDelay = config.baseDelayMs * Math.pow(2, attempt);
  const cappedDelay = Math.min(exponentialDelay, config.maxDelayMs);

  switch (config.jitterStrategy) {
    case 'full':
      // Random between 0 and capped delay
      return Math.random() * cappedDelay;

    case 'equal':
      // Half fixed + half random
      return (cappedDelay / 2) + (Math.random() * cappedDelay / 2);

    case 'decorrelated':
      // Depends on previous delay (more complex state)
      return Math.random() * (config.baseDelayMs + cappedDelay * 3);
  }
}

// Example schedule with full jitter, base=1s:
// Attempt 0: random(0, 1s)    → ~0.4s
// Attempt 1: random(0, 2s)    → ~1.2s
// Attempt 2: random(0, 4s)    → ~2.8s
// Attempt 3: random(0, 8s)    → ~5.1s
// Attempt 4: random(0, 16s)   → ~9.3s
// ... capped at maxDelayMs
```

### Python Implementation
```python
import random
import asyncio
from dataclasses import dataclass

@dataclass
class RetryConfig:
    base_delay_ms: int = 1000
    max_delay_ms: int = 3_600_000  # 1 hour
    max_attempts: int = 10

def calculate_retry_delay(attempt: int, config: RetryConfig) -> float:
    """Full jitter: random between 0 and exponential delay."""
    exponential = config.base_delay_ms * (2 ** attempt)
    capped = min(exponential, config.max_delay_ms)
    return random.uniform(0, capped) / 1000  # Convert to seconds

async def retry_with_backoff(coro_func, config: RetryConfig):
    """Retry an async function with exponential backoff + jitter."""
    last_exception = None
    for attempt in range(config.max_attempts):
        try:
            return await coro_func()
        except RetryableError as e:
            last_exception = e
            delay = calculate_retry_delay(attempt, config)
            await asyncio.sleep(delay)
    raise last_exception
```

## What to Retry vs. Not

### Retryable (Temporary Failures)
- Network timeouts
- Connection errors
- HTTP 408 (Request Timeout)
- HTTP 429 (Too Many Requests) — honor `Retry-After` header
- HTTP 500 (Internal Server Error)
- HTTP 502 (Bad Gateway)
- HTTP 503 (Service Unavailable)
- HTTP 504 (Gateway Timeout)

### NOT Retryable (Permanent Failures)
- HTTP 400 (Bad Request) — malformed payload
- HTTP 401 (Unauthorized) — credentials wrong
- HTTP 403 (Forbidden) — endpoint rejects request
- HTTP 404 (Not Found) — endpoint doesn't exist
- HTTP 410 (Gone) — endpoint permanently removed
- HTTP 422 (Unprocessable Entity)

### Special: HTTP 429
```python
async def handle_rate_limited(response):
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        delay = int(retry_after)  # Seconds or HTTP-date
    else:
        delay = calculate_retry_delay(attempt, config)
    await asyncio.sleep(delay)
```

## Dead Letter Queue (DLQ)

When all retries are exhausted, don't lose the event:

```python
async def process_with_dlq(event_id: str, payload: dict):
    config = RetryConfig(max_attempts=10)

    for attempt in range(config.max_attempts):
        try:
            await process_event(payload)
            await update_event_status(event_id, "completed")
            return
        except RetryableError as e:
            if attempt == config.max_attempts - 1:
                # All retries exhausted → DLQ
                await move_to_dlq(event_id, payload, str(e), attempt)
                return
            delay = calculate_retry_delay(attempt, config)
            await asyncio.sleep(delay)

async def move_to_dlq(event_id, payload, error, attempts):
    await db.execute("""
        INSERT INTO dead_letter_queue (event_id, payload, error, attempts, failed_at)
        VALUES ($1, $2, $3, $4, NOW())
    """, event_id, json.dumps(payload), error, attempts)

    # Alert the team
    await notify_team(f"Webhook {event_id} failed after {attempts} attempts: {error}")
```

### DLQ Management
```python
@app.post("/admin/dlq/replay/{event_id}")
async def replay_dlq_event(event_id: str):
    """Replay a failed event after fixing the handler."""
    event = await db.fetchrow(
        "SELECT * FROM dead_letter_queue WHERE event_id = $1", event_id
    )
    if not event:
        raise HTTPException(404, "Event not found in DLQ")

    # Re-enqueue for processing
    await message_queue.publish("webhook-events", json.loads(event["payload"]))

    # Remove from DLQ
    await db.execute("DELETE FROM dead_letter_queue WHERE event_id = $1", event_id)
    return {"status": "replayed"}
```

## Circuit Breaker Pattern

Stop hammering a failing endpoint:
```python
class CircuitBreaker:
    def __init__(self, failure_threshold=5, recovery_timeout=60):
        self.failures = 0
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state = "closed"  # closed = normal, open = blocking, half-open = testing
        self.last_failure_time = 0

    async def call(self, func, *args, **kwargs):
        if self.state == "open":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "half-open"
            else:
                raise CircuitOpenError("Circuit breaker is open")

        try:
            result = await func(*args, **kwargs)
            if self.state == "half-open":
                self.state = "closed"
                self.failures = 0
            return result
        except Exception as e:
            self.failures += 1
            self.last_failure_time = time.time()
            if self.failures >= self.failure_threshold:
                self.state = "open"
            raise
```

## Key Rules

1. **Exponential backoff + jitter** — never fixed delays
2. **Cap maximum delay** — typically 1 hour
3. **Set max attempts** — typically 5-10
4. **Retry temporary failures only** — 5xx, timeouts, 429
5. **Never retry 4xx** (except 429) — they won't fix themselves
6. **Dead letter queue** — for events that fail all retries
7. **Circuit breaker** — protect failing downstream services
8. **Honor Retry-After** — when provider sends it
9. **Alert on DLQ** — team needs to know about stuck events
10. **Track attempt count** — in your event record
