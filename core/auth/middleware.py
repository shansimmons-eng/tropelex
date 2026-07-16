"""
FastAPI auth middleware and dependency injection for JWT-protected endpoints.

Usage in a router:
    from core.auth.middleware import require_auth, optional_auth

    @router.get("/protected")
    async def protected(user=Depends(require_auth)):
        return {"user": user["user_id"]}
"""

import os
from typing import Any

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from core.auth.jwt_service import validate_token

_bearer_scheme = HTTPBearer(auto_error=False)


def _get_secret() -> str:
    """Read JWT secret from environment. Raises if unset."""
    secret = os.environ.get("JWT_SECRET", "")
    if not secret:
        raise HTTPException(
            status_code=500,
            detail="JWT_SECRET not configured",
        )
    return secret


def extract_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any] | None:
    """Extract user claims from Bearer token, or None if absent/invalid.

    Never raises — returns None for missing, malformed, or expired tokens.
    Used by ``optional_auth``.
    """
    if credentials is None:
        return None
    secret = os.environ.get("JWT_SECRET", "")
    if not secret:
        return None
    return validate_token(credentials.credentials, secret)


def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """FastAPI dependency that enforces a valid JWT.

    Returns decoded claims dict. Raises 401 on any failure.

    Use as:
        @router.get("/protected")
        async def endpoint(user=Depends(require_auth)):
            ...
    """
    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    secret = _get_secret()
    claims = validate_token(credentials.credentials, secret)
    if claims is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return claims


def optional_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any] | None:
    """FastAPI dependency that extracts JWT if present but never rejects.

    Returns decoded claims dict or None.
    """
    return extract_user(credentials)
