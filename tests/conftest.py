"""Shared test fixtures and cleanup for Tropelex test suite."""

import os
import glob
import pytest

# P1: a fixed, test-only instance secret, set before core.tropebook.web.server
# is ever imported (server.py's module-level .env loader uses
# os.environ.setdefault, so this wins over whatever's in a developer's local
# .env, and tests never depend on or leak the real generated secret).
os.environ["TROPEL_EX_SECRET"] = "test-only-instance-secret-do-not-use-in-prod"

# P1: server.py's host_validation_middleware rejects any request whose Host
# header isn't localhost:8766/127.0.0.1:8766/[::1]:8766 (defends against DNS
# rebinding), and instance_auth_middleware requires the instance secret on
# every mutating /api/ call that doesn't look like a same-origin browser
# request. TestClient (httpx) sends neither an allowed Host nor a
# Sec-Fetch-Site header by default, and defaults to "http://testserver",
# which both middlewares would reject/block on every request across all
# ~30 test files that construct their own TestClient. Patching the
# defaults here, before pytest imports any test module, makes every
# TestClient instantiation (regardless of call site) send an allowed Host
# header and the instance token without weakening either middleware or
# touching every call site individually. Tests that specifically exercise
# unauthenticated/cross-site behavior override these per-request.
import starlette.testclient as _st_testclient

_RealTestClient = _st_testclient.TestClient


class TestClient(_RealTestClient):
    def __init__(
        self,
        *args,
        base_url: str = "http://127.0.0.1:8766",
        headers: dict | None = None,
        **kwargs,
    ):
        merged_headers = {"Authorization": f"Bearer {os.environ['TROPEL_EX_SECRET']}"}
        if headers:
            merged_headers.update(headers)
        super().__init__(*args, base_url=base_url, headers=merged_headers, **kwargs)


_st_testclient.TestClient = TestClient
import fastapi.testclient as _fa_testclient  # noqa: E402

_fa_testclient.TestClient = TestClient


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
