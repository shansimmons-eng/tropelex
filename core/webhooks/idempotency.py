"""
Webhook idempotency — pure functions with thread-safe in-memory store.

Prevents duplicate webhook processing using event ID tracking with TTL expiry.
Follows code-quality.md: pure functions, dependency injection, <50 lines per function.
"""

import threading
import time


DEFAULT_TTL_HOURS = 24


def is_duplicate_event(event_id: str, store: dict) -> bool:
    """Check if an event has already been seen and is still within its TTL window.

    Pure function: same inputs always produce same output. The store is passed
    explicitly (dependency injection) so callers control the backing state.

    Args:
        event_id: Unique identifier for the webhook event.
        store: Dict mapping event_id -> expiry timestamp (epoch seconds).

    Returns:
        True if the event exists and has not expired.
    """
    expiry = store.get(event_id)
    if expiry is None:
        return False
    return time.time() < expiry


def mark_event(event_id: str, store: dict, ttl_hours: int = DEFAULT_TTL_HOURS) -> None:
    """Record an event with an expiry timestamp.

    Pure function: mutates the caller-owned store dict (explicit dependency)
    but has no hidden side effects.

    Args:
        event_id: Unique identifier for the webhook event.
        store: Dict mapping event_id -> expiry timestamp (epoch seconds).
        ttl_hours: Hours until the idempotency key expires.
    """
    store[event_id] = time.time() + (ttl_hours * 3600)


def cleanup_expired(store: dict) -> int:
    """Remove all expired entries from the store.

    Returns the number of entries removed.

    Args:
        store: Dict mapping event_id -> expiry timestamp (epoch seconds).

    Returns:
        Count of expired entries that were removed.
    """
    now = time.time()
    expired = [eid for eid, expiry in store.items() if expiry <= now]
    for eid in expired:
        del store[eid]
    return len(expired)


def create_idempotency_store(default_ttl_hours: int = DEFAULT_TTL_HOURS):
    """Factory: returns a thread-safe idempotency store with bound methods.

    The returned store object wraps a plain dict with a lock for thread safety
    and exposes the pure functions above as methods.

    Args:
        default_ttl_hours: Default TTL for new events.

    Returns:
        IdempotencyStore instance.
    """
    return IdempotencyStore(default_ttl_hours)


class IdempotencyStore:
    """Thread-safe in-memory idempotency store with TTL-based expiry.

    Usage:
        store = create_idempotency_store(ttl_hours=12)
        if store.is_duplicate("evt-123"):
            return {"skipped": True}
        store.mark("evt-123")
        # ... process event ...
    """

    def __init__(self, default_ttl_hours: int = DEFAULT_TTL_HOURS):
        self._store: dict[str, float] = {}
        self._lock = threading.Lock()
        self.default_ttl_hours = default_ttl_hours

    def is_duplicate(self, event_id: str) -> bool:
        """Check if an event is a duplicate (thread-safe)."""
        with self._lock:
            return is_duplicate_event(event_id, self._store)

    def mark(self, event_id: str, ttl_hours: int | None = None) -> None:
        """Mark an event as seen (thread-safe)."""
        hours = ttl_hours if ttl_hours is not None else self.default_ttl_hours
        with self._lock:
            mark_event(event_id, self._store, hours)

    def cleanup(self) -> int:
        """Remove expired entries (thread-safe)."""
        with self._lock:
            return cleanup_expired(self._store)

    def size(self) -> int:
        """Return the number of entries in the store."""
        with self._lock:
            return len(self._store)
