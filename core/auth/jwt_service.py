"""JWT token generation and validation using HS256.

Pure functions for token lifecycle management. All secrets are passed as
explicit dependencies — never read from environment or globals.
"""

from datetime import datetime, timedelta, timezone

import jwt
from jwt import DecodeError, ExpiredSignatureError, InvalidSignatureError


def generate_token(payload: dict, secret: str, expires_hours: int = 24) -> str:
    """Create a signed JWT with automatic expiration.

    Args:
        payload: Claims to encode (must include user_id and role).
        secret: Signing key (never hardcoded).
        expires_hours: Token lifetime from now.

    Returns:
        Encoded JWT string.

    Raises:
        ValueError: If payload is missing required claims.
    """
    _validate_required_claims(payload)

    now = datetime.now(timezone.utc)
    token_payload = {
        **payload,
        "iat": now,
        "exp": now + timedelta(hours=expires_hours),
    }

    return jwt.encode(token_payload, secret, algorithm="HS256")


def validate_token(token: str, secret: str) -> dict | None:
    """Decode and verify a JWT. Returns None on any failure.

    Failure modes handled:
    - Malformed token structure
    - Invalid or missing signature
    - Expired token
    - Invalid audience/issuer (not enforced here, but future-proof)

    Args:
        token: The JWT string to validate.
        secret: The signing key used during generation.

    Returns:
        Decoded payload dict on success, None on failure.
    """
    try:
        return jwt.decode(token, secret, algorithms=["HS256"])
    except (DecodeError, InvalidSignatureError, ExpiredSignatureError, Exception):
        return None


def _validate_required_claims(payload: dict) -> None:
    """Ensure payload contains mandatory fields."""
    missing = [claim for claim in ("user_id", "role") if claim not in payload]
    if missing:
        raise ValueError(f"Missing required claims: {', '.join(missing)}")
