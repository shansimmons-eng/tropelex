"""
Webhook HMAC Signature Verification

Pure functions for verifying webhook signatures from GitHub, GitLab,
and other providers using HMAC-SHA256 with constant-time comparison.
"""

import hashlib
import hmac


def verify_webhook_signature(
    payload: bytes,
    signature: str,
    secret: str,
    provider: str = "github",
) -> bool:
    """
    Verify an HMAC-SHA256 webhook signature.

    Pure function — same inputs always produce the same result, no side effects.
    Returns False on any error (missing header, malformed signature, wrong provider).

    Args:
        payload: Raw request body bytes.
        signature: The signature header value from the request.
        secret: The shared webhook secret (from env vars, never hardcoded).
        provider: Provider name: "github" or "gitlab".

    Returns:
        True if signature is valid, False otherwise.
    """
    if payload is None or not signature or not secret:
        return False

    providers = {
        "github": _verify_github,
        "gitlab": _verify_gitlab,
    }

    verifier = providers.get(provider)
    if verifier is None:
        return False

    return verifier(payload, signature, secret)


def _compute_hmac(payload: bytes, secret: str) -> str:
    """Compute HMAC-SHA256 hex digest for payload. Pure function."""
    return hmac.new(
        secret.encode(), payload, hashlib.sha256
    ).hexdigest()


def _verify_github(payload: bytes, signature: str, secret: str) -> bool:
    """
    GitHub sends X-Hub-Signature-256 as "sha256=<hex>".
    Strip the prefix, compute expected, compare with constant time.
    """
    if not signature.startswith("sha256="):
        return False

    expected = _compute_hmac(payload, secret)
    received = signature[len("sha256="):]
    return hmac.compare_digest(expected, received)


def _verify_gitlab(payload: bytes, signature: str, secret: str) -> bool:
    """
    GitLab sends Webhook-Secret-Token as a plain token comparison,
    or X-Gitlab-Signature as an HMAC-SHA256 hex digest.

    For HMAC mode (this service), we compare against the hex digest.
    The signature header may include "sha256=" prefix — strip if present.
    """
    clean_signature = signature
    if signature.startswith("sha256="):
        clean_signature = signature[len("sha256="):]

    expected = _compute_hmac(payload, secret)
    return hmac.compare_digest(expected, clean_signature)
