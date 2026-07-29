"""Shared test fixtures and cleanup for Tropelex test suite."""

import os
import glob
import pytest


MEMORY_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "memory")


@pytest.fixture(autouse=True, scope="session")
def cleanup_test_projects():
    """Clean up test_* project files after all tests complete."""
    yield
    # After all tests, clean up any test_* project files
    pattern = os.path.join(MEMORY_DIR, "test_*.json")
    for f in glob.glob(pattern):
        try:
            os.remove(f)
        except OSError:
            pass


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """Reset the FastAPI app's in-memory rate limiter between tests.

    ``_rate_limits`` in core/tropebook/web/server.py is a module-level dict
    keyed by client IP. FastAPI's TestClient always reports its host as
    "testclient" (not 127.0.0.1, which the middleware exempts), so requests
    from every test file share one entry and accumulate within the same
    60s window. Without a reset, whichever test files run late enough in
    the session to push that entry past RATE_LIMIT_MAX start getting 429s
    on requests that have nothing to do with rate limiting.
    """
    from core.tropebook.web.server import _rate_limits

    _rate_limits.clear()
    yield
    _rate_limits.clear()
