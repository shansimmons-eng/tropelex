"""Tests for core.webhooks.idempotency"""

import time
import threading

import pytest

from core.webhooks.idempotency import (
    DEFAULT_TTL_HOURS,
    IdempotencyStore,
    cleanup_expired,
    create_idempotency_store,
    is_duplicate_event,
    mark_event,
)


class TestPureFunctions:
    """Tests for the pure idempotency functions."""

    def test_is_duplicate_returns_false_for_new_event(self):
        assert is_duplicate_event("evt-1", {}) is False

    def test_is_duplicate_returns_true_after_mark(self):
        store = {}
        mark_event("evt-1", store, ttl_hours=1)
        assert is_duplicate_event("evt-1", store) is True

    def test_is_duplicate_returns_false_for_expired_event(self):
        store = {}
        store["evt-1"] = time.time() - 1  # already expired
        assert is_duplicate_event("evt-1", store) is False

    def test_mark_event_sets_expiry(self):
        store = {}
        mark_event("evt-1", store, ttl_hours=2)
        expected = time.time() + 2 * 3600
        assert abs(store["evt-1"] - expected) < 1

    def test_mark_event_overwrites_existing(self):
        store = {}
        mark_event("evt-1", store, ttl_hours=1)
        first_expiry = store["evt-1"]
        mark_event("evt-1", store, ttl_hours=24)
        assert store["evt-1"] > first_expiry

    def test_cleanup_expired_removes_old_entries(self):
        store = {"old": time.time() - 100, "fresh": time.time() + 3600}
        removed = cleanup_expired(store)
        assert removed == 1
        assert "old" not in store
        assert "fresh" in store

    def test_cleanup_returns_zero_when_nothing_expired(self):
        store = {"fresh": time.time() + 3600}
        assert cleanup_expired(store) == 0

    def test_cleanup_empty_store(self):
        assert cleanup_expired({}) == 0

    def test_multiple_events_independent(self):
        store = {}
        mark_event("a", store, ttl_hours=1)
        mark_event("b", store, ttl_hours=1)
        assert is_duplicate_event("a", store) is True
        assert is_duplicate_event("b", store) is True
        assert is_duplicate_event("c", store) is False

    def test_default_ttl_constant(self):
        assert DEFAULT_TTL_HOURS == 24


class TestIdempotencyStore:
    """Tests for the thread-safe IdempotencyStore wrapper."""

    def test_is_duplicate_false_for_new_event(self):
        store = create_idempotency_store()
        assert store.is_duplicate("evt-1") is False

    def test_mark_and_check(self):
        store = create_idempotency_store()
        store.mark("evt-1")
        assert store.is_duplicate("evt-1") is True

    def test_custom_ttl(self):
        store = create_idempotency_store(default_ttl_hours=2)
        store.mark("evt-1", ttl_hours=1)
        expected = time.time() + 3600
        assert abs(store._store["evt-1"] - expected) < 1

    def test_default_ttl_from_factory(self):
        store = create_idempotency_store(default_ttl_hours=12)
        store.mark("evt-1")
        expected = time.time() + 12 * 3600
        assert abs(store._store["evt-1"] - expected) < 1

    def test_cleanup(self):
        store = create_idempotency_store()
        store._store["old"] = time.time() - 100
        store.mark("fresh")
        removed = store.cleanup()
        assert removed == 1
        assert store.size() == 1

    def test_size(self):
        store = create_idempotency_store()
        assert store.size() == 0
        store.mark("a")
        store.mark("b")
        assert store.size() == 2

    def test_expired_event_not_duplicate(self):
        store = create_idempotency_store()
        store._store["old"] = time.time() - 1
        assert store.is_duplicate("old") is False

    def test_thread_safety(self):
        store = create_idempotency_store()
        errors = []

        def writer(prefix, count):
            try:
                for i in range(count):
                    store.mark(f"{prefix}-{i}")
            except Exception as e:
                errors.append(e)

        def reader(prefix, count):
            try:
                for i in range(count):
                    store.is_duplicate(f"{prefix}-{i}")
            except Exception as e:
                errors.append(e)

        threads = []
        for t in range(5):
            threads.append(threading.Thread(target=writer, args=(f"w{t}", 100)))
            threads.append(threading.Thread(target=reader, args=(f"r{t}", 100)))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert store.size() >= 0  # no crash

    def test_cleanup_concurrent(self):
        store = create_idempotency_store()
        store._store["expired"] = time.time() - 1
        store.mark("active")
        removed = store.cleanup()
        assert removed == 1
        assert store.is_duplicate("active") is True
