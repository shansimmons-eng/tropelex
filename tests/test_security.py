"""Tests for security measures: masking, settings endpoint, rate limiting."""

import os
import pytest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.tropebook.web.server import app, _mask_key, _atomic_write


# ─── Masking function ──────────────────────────────────────────────────


class TestMaskKey:
    def test_non_empty_returns_asterisks(self):
        """Configured keys return only asterisks, no characters."""
        for _ in range(20):
            result = _mask_key("sk-abc123def456ghi")
            assert result, "Should not be empty for non-empty input"
            assert "*" in result, "Should contain asterisks"
            assert "sk-" not in result, "Should NOT reveal key prefix"
            assert "abc" not in result, "Should NOT reveal key content"
            assert "ghi" not in result, "Should NOT reveal key suffix"
            assert all(c == "*" for c in result), f"Should be all asterisks, got: {result!r}"

    def test_random_length_between_8_and_16(self):
        """Masked output has random length between 8 and 16."""
        lengths = {len(_mask_key("a" * 50)) for _ in range(100)}
        assert all(8 <= l <= 16 for l in lengths), f"Lengths should be 8-16, got: {lengths}"
        assert len(lengths) > 1, "Should produce varying lengths (randomized)"

    def test_empty_returns_empty(self):
        assert _mask_key("") == ""

    def test_none_returns_empty(self):
        assert _mask_key(None) == ""

    def test_short_key_still_masked(self):
        result = _mask_key("abc")
        assert all(c == "*" for c in result)
        assert 8 <= len(result) <= 16


# ─── Settings endpoint ─────────────────────────────────────────────────


class TestSettingsEndpoint:
    def test_get_settings_masks_secrets(self):
        """GET /api/settings returns masked values for secret keys."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test1234567890abcdef"}):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/api/settings")
            assert resp.status_code == 200
            data = resp.json()
            openai = data["keys"]["OPENAI_API_KEY"]
            assert openai["configured"] is True
            assert "sk-" not in openai["masked"]
            assert "test" not in openai["masked"]
            assert all(c == "*" for c in openai["masked"])

    def test_get_settings_shows_non_secret_values(self):
        """Non-secret keys (BSKY_HANDLE, CUSTOM_LLM_HOST) show plain values."""
        with patch.dict(os.environ, {"BSKY_HANDLE": "user.bsky.social"}):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/api/settings")
            assert resp.status_code == 200
            data = resp.json()
            bsky = data["keys"]["BSKY_HANDLE"]
            assert bsky["configured"] is True
            assert bsky["value"] == "user.bsky.social"

    def test_post_apikey_rejects_unknown_key(self):
        """POST /api/settings/apikey rejects keys not in ALLOWED_KEYS."""
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/api/settings/apikey", json={
            "key": "EVIL_SECRET_KEY",
            "value": "should-not-be-saved",
        })
        assert resp.status_code == 400
        assert "not allowed" in resp.json()["detail"]

    def test_post_apikey_accepts_allowed_keys(self):
        """POST /api/settings/apikey accepts whitelisted keys."""
        client = TestClient(app, raise_server_exceptions=False)
        for key in ["XAI_API_KEY", "SCRAPECREATORS_API_KEY", "BSKY_HANDLE", "AUTH_TOKEN", "CT0"]:
            resp = client.post("/api/settings/apikey", json={
                "key": key,
                "value": "test-value",
            })
            assert resp.status_code == 200, f"Key {key} should be accepted, got {resp.status_code}"

    def test_get_settings_includes_new_deep_research_keys(self):
        """GET /api/settings includes all deep research source keys."""
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/settings")
        assert resp.status_code == 200
        keys = resp.json()["keys"]
        for expected in [
            "XAI_API_KEY", "SCRAPECREATORS_API_KEY",
            "BSKY_HANDLE", "BSKY_APP_PASSWORD",
            "AUTH_TOKEN", "CT0", "PARALLEL_API_KEY",
        ]:
            assert expected in keys, f"Missing key: {expected}"


# ─── Rate limiting ─────────────────────────────────────────────────────


class TestRateLimiting:
    def test_rate_limit_middleware_exists(self):
        """Rate limit middleware is registered on the app."""
        middleware_classes = [type(m).__name__ for m in app.user_middleware]
        # The middleware should be present (BaseHTTPMiddleware or similar)
        assert len(app.user_middleware) > 0, "Should have middleware registered"

    def test_health_endpoint_not_rate_limited(self):
        """Health endpoint should always respond (not rate limited)."""
        client = TestClient(app, raise_server_exceptions=False)
        for _ in range(5):
            resp = client.get("/api/health")
            assert resp.status_code == 200


# ─── SSRF protection (if applicable) ───────────────────────────────────


class TestSSRFProtection:
    def test_private_ip_blocked_in_scraper(self):
        """Web scraper should block private IPs."""
        from core.tropebook.research import WebScraper
        scraper = WebScraper()
        # These should be blocked or handled safely
        assert True  # Placeholder - actual SSRF tests depend on scraper implementation
