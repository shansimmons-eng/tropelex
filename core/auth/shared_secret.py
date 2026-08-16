"""
Shared-secret instance auth for Tropelex's local API server.

Tropelex runs as a single-user, localhost-bound instance — every client
(dashboard, MCP server, OpenCode plugin, Emacs/VSCode/Slack adapters) talks
to the same process on the same machine. A JWT-issuance flow (see
core/auth/middleware.py) adds no value for that topology; a single
long-lived shared secret, generated once and read from the environment by
every client, is the right primitive. JWT support stays available if
Tropelex ever grows a real multi-user story.

Usage:
    from core.auth.shared_secret import require_local_secret

    @router.post("/protected")
    async def protected(_: None = Depends(require_local_secret)):
        ...
"""

import hmac
import logging
import os
import secrets
from pathlib import Path

from fastapi import HTTPException, Request

logger = logging.getLogger("tropelex.auth")

SECRET_ENV_VAR = "TROPEL_EX_SECRET"


def get_or_create_secret(base_dir: Path) -> str:
    """Return the instance's shared secret, generating and persisting one
    to <base_dir>/.env on first run. Idempotent across restarts: once
    written, the .env loader in server.py picks it up on the next start
    via os.environ.setdefault before this ever runs again.
    """
    existing = os.environ.get(SECRET_ENV_VAR, "")
    if existing:
        return existing

    secret = secrets.token_urlsafe(32)
    os.environ[SECRET_ENV_VAR] = secret

    env_path = base_dir / ".env"
    try:
        with open(env_path, "a") as f:
            f.write(f"\n{SECRET_ENV_VAR}={secret}\n")
        logger.warning(
            "Generated new instance secret and wrote it to %s (%s...). "
            "All Tropelex clients (MCP server, OpenCode plugin, adapters) "
            "read %s from the environment automatically.",
            env_path, secret[:8], SECRET_ENV_VAR,
        )
    except OSError as exc:
        logger.error(
            "Could not persist %s to %s: %s. A new secret will be "
            "generated on every restart until this is fixed, which will "
            "invalidate all existing client sessions each time.",
            SECRET_ENV_VAR, env_path, exc,
        )
    return secret


def _extract_token(request: Request) -> str | None:
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    key_header = request.headers.get("x-tropelex-key")
    if key_header:
        return key_header.strip()
    return None


def token_is_valid(request: Request) -> bool:
    """True iff the request carries the correct instance secret.

    Never raises — callers (middleware or dependency) decide how to
    respond to False. Used by both require_local_secret and
    server.py's instance_auth_middleware, so there's one comparison path.
    """
    configured = os.environ.get(SECRET_ENV_VAR, "")
    if not configured:
        return False
    token = _extract_token(request)
    return bool(token) and hmac.compare_digest(token, configured)


def require_local_secret(request: Request) -> None:
    """FastAPI dependency enforcing the instance shared secret.

    Accepts the token via `Authorization: Bearer <token>` or
    `X-Tropelex-Key: <token>`. Raises 401 if missing or invalid.
    """
    if not token_is_valid(request):
        raise HTTPException(status_code=401, detail="Missing or invalid instance secret")
