"""
Tests for webhook HMAC signature verification.
"""

import hashlib
import hmac

import pytest

from core.webhooks.signature import verify_webhook_signature


def _hmac_sha256(payload: bytes, secret: str) -> str:
    """Helper: compute HMAC-SHA256 hex digest."""
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


# -- GitHub Tests --


class TestGitHubSignature:
    VALID_SECRET = "my-webhook-secret"
    PAYLOAD = b'{"action":"opened","number":1}'

    def test_valid_signature(self):
        sig = "sha256=" + _hmac_sha256(self.PAYLOAD, self.VALID_SECRET)
        assert verify_webhook_signature(
            self.PAYLOAD, sig, self.VALID_SECRET, "github"
        )

    def test_invalid_signature(self):
        sig = "sha256=" + _hmac_sha256(self.PAYLOAD, "wrong-secret")
        assert not verify_webhook_signature(
            self.PAYLOAD, sig, self.VALID_SECRET, "github"
        )

    def test_missing_prefix(self):
        raw_hex = _hmac_sha256(self.PAYLOAD, self.VALID_SECRET)
        assert not verify_webhook_signature(
            self.PAYLOAD, raw_hex, self.VALID_SECRET, "github"
        )

    def test_malformed_prefix(self):
        sig = "sha256=" + "not-hex!!!"
        assert not verify_webhook_signature(
            self.PAYLOAD, sig, self.VALID_SECRET, "github"
        )

    def test_empty_payload(self):
        sig = "sha256=" + _hmac_sha256(b"", self.VALID_SECRET)
        assert verify_webhook_signature(b"", sig, self.VALID_SECRET, "github")

    def test_tampered_payload(self):
        original_sig = "sha256=" + _hmac_sha256(self.PAYLOAD, self.VALID_SECRET)
        tampered = b'{"action":"closed","number":1}'
        assert not verify_webhook_signature(
            tampered, original_sig, self.VALID_SECRET, "github"
        )


# -- GitLab Tests --


class TestGitLabSignature:
    VALID_SECRET = "gitlab-token-xyz"
    PAYLOAD = b'{"object_kind":"push","ref":"refs/heads/main"}'

    def test_valid_signature(self):
        sig = _hmac_sha256(self.PAYLOAD, self.VALID_SECRET)
        assert verify_webhook_signature(
            self.PAYLOAD, sig, self.VALID_SECRET, "gitlab"
        )

    def test_valid_signature_with_prefix(self):
        sig = "sha256=" + _hmac_sha256(self.PAYLOAD, self.VALID_SECRET)
        assert verify_webhook_signature(
            self.PAYLOAD, sig, self.VALID_SECRET, "gitlab"
        )

    def test_invalid_signature(self):
        sig = _hmac_sha256(self.PAYLOAD, "wrong-secret")
        assert not verify_webhook_signature(
            self.PAYLOAD, sig, self.VALID_SECRET, "gitlab"
        )

    def test_empty_payload(self):
        sig = _hmac_sha256(b"", self.VALID_SECRET)
        assert verify_webhook_signature(b"", sig, self.VALID_SECRET, "gitlab")


# -- Edge Cases --


class TestEdgeCases:
    def test_empty_signature(self):
        assert not verify_webhook_signature(b"{}", "", "secret")

    def test_empty_secret(self):
        assert not verify_webhook_signature(b"{}", "sha256=abc", "")

    def test_empty_payload_and_secret(self):
        sig = "sha256=" + _hmac_sha256(b"", "secret")
        assert not verify_webhook_signature(b"", sig, "")

    def test_none_payload(self):
        assert not verify_webhook_signature(None, "sig", "secret")

    def test_none_signature(self):
        assert not verify_webhook_signature(b"{}", None, "secret")

    def test_none_secret(self):
        assert not verify_webhook_signature(b"{}", "sig", None)

    def test_unknown_provider(self):
        sig = "sha256=" + _hmac_sha256(b"{}", "secret")
        assert not verify_webhook_signature(b"{}", sig, "secret", "bitbucket")

    def test_default_provider_is_github(self):
        sig = "sha256=" + _hmac_sha256(b"{}", "secret")
        assert verify_webhook_signature(b"{}", sig, "secret")

    def test_large_payload(self):
        secret = "large-payload-secret"
        large = b"x" * 1_000_000
        sig = "sha256=" + _hmac_sha256(large, secret)
        assert verify_webhook_signature(large, sig, secret)

    def test_binary_payload(self):
        secret = "binary-secret"
        payload = bytes(range(256))
        sig = "sha256=" + _hmac_sha256(payload, secret)
        assert verify_webhook_signature(payload, sig, secret)

    def test_unicode_payload(self):
        secret = "unicode-secret"
        payload = '{"text":"\u00e9\u00e8\u00ea"}'.encode("utf-8")
        sig = "sha256=" + _hmac_sha256(payload, secret)
        assert verify_webhook_signature(payload, sig, secret)
