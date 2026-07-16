"""Webhook HMAC verification for GitHub, GitLab, and other providers."""

from core.webhooks.signature import verify_webhook_signature

__all__ = ["verify_webhook_signature"]
