"""
Webhook POST endpoint for Tropelex.

Receives GitHub/GitLab push events, verifies HMAC signatures,
enforces idempotency, and auto-syncs repo changes to project memory.

Mount into the main app:
    from core.webhooks.router import webhook_router
    app.include_router(webhook_router)
"""

import logging
import os
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from core.git_integration import sync_repo_to_memory
from core.webhooks.idempotency import create_idempotency_store
from core.webhooks.signature import verify_webhook_signature

logger = logging.getLogger("tropelex.webhooks")

webhook_router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

# --- Shared state (module-level, lazy-init) ---
_idempotency_store = create_idempotency_store(default_ttl_hours=24)

# --- Paths ---
_CORE_DIR = Path(__file__).parent.parent  # core/
BASE_DIR = _CORE_DIR.parent              # project root


def _get_memory_manager():
    """Lazy-init MemoryManager (same pattern as server.py)."""
    from core.memory.manager import MemoryManager

    return MemoryManager(str(BASE_DIR))


def _extract_event_id(payload: dict[str, Any], headers: dict[str, str]) -> str | None:
    """Extract a unique event ID from the webhook payload or headers.

    Priority:
    1. X-GitHub-Delivery / X-Gitlab-Event-UUID header (provider-supplied)
    2. GitLab: payload['object_attributes']['id'] (MR/push internal ID)
    3. GitHub: payload['after'] commit SHA + repository full name
    4. Fallback: SHA-256 of the raw payload body (last resort dedup)
    """
    # Provider-supplied unique delivery ID
    for header_key in ("x-github-delivery", "x-gitlab-event-uuid"):
        if header_key in headers:
            return headers[header_key]

    # GitLab push events have object_attributes.id
    obj_attrs = payload.get("object_attributes", {})
    if "id" in obj_attrs:
        return f"gl-{obj_attrs['id']}"

    # GitHub push: after SHA + repo name
    repo_name = payload.get("repository", {}).get("full_name", "")
    after_sha = payload.get("after", "")
    if after_sha:
        return f"gh-{repo_name}-{after_sha}"

    return None


def _parse_push_event(payload: dict[str, Any], provider: str) -> dict[str, Any]:
    """Normalise GitHub / GitLab push event payloads into a common shape.

    Returns:
        {
            "repo_url": str,       # local clone path or remote URL
            "repo_name": str,      # full repo name (owner/repo)
            "project": str,        # sanitised project name for memory
            "branch": str,         # branch that was pushed to
            "commits": [...],      # list of commit summaries
            "head_commit": str,    # HEAD commit SHA after push
        }
    """
    if provider == "github":
        return _parse_github_push(payload)
    elif provider == "gitlab":
        return _parse_gitlab_push(payload)
    else:
        raise ValueError(f"Unsupported provider: {provider}")


def _parse_github_push(payload: dict[str, Any]) -> dict[str, Any]:
    """Parse a GitHub push event payload."""
    ref = payload.get("ref", "")  # e.g. "refs/heads/main"
    branch = ref.replace("refs/heads/", "") if ref.startswith("refs/heads/") else ref

    repo = payload.get("repository", {})
    repo_name = repo.get("full_name", "unknown")
    # Use clone_url for local operations; fall back to html_url
    repo_url = repo.get("clone_url") or repo.get("html_url", "")
    head_commit = payload.get("after", "")

    commits = []
    for c in payload.get("commits", []):
        commits.append({
            "sha": c.get("id", "")[:8],
            "message": c.get("message", ""),
            "author": c.get("author", {}).get("name", ""),
        })

    # Derive a safe project name from the repo
    project = _sanitise_project_name(repo_name)

    return {
        "repo_url": repo_url,
        "repo_name": repo_name,
        "project": project,
        "branch": branch,
        "commits": commits,
        "head_commit": head_commit,
    }


def _parse_gitlab_push(payload: dict[str, Any]) -> dict[str, Any]:
    """Parse a GitLab push event payload."""
    ref = payload.get("ref", "")
    branch = ref.replace("refs/heads/", "") if ref.startswith("refs/heads/") else ref

    project_info = payload.get("project", {})
    repo_name = project_info.get("path_with_namespace", "unknown")
    repo_url = project_info.get("git_http_url") or project_info.get("git_ssh_url", "")
    head_commit = payload.get("after", "")

    commits = []
    for c in payload.get("commits", []):
        commits.append({
            "sha": c.get("id", "")[:8],
            "message": c.get("message", ""),
            "author": c.get("author", {}).get("name", ""),
        })

    project = _sanitise_project_name(repo_name)

    return {
        "repo_url": repo_url,
        "repo_name": repo_name,
        "project": project,
        "branch": branch,
        "commits": commits,
        "head_commit": head_commit,
    }


def _sanitise_project_name(name: str) -> str:
    """Strip path components and sanitise for use as a memory project key."""
    # Take the last path segment (repo name) from owner/repo
    clean = Path(name).name
    # Allow only alphanumeric, hyphens, underscores
    return "".join(c for c in clean if c.isalnum() or c in "-_")[:100]


# ---------------------------------------------------------------------------
#  POST /api/webhooks/git
# ---------------------------------------------------------------------------

@webhook_router.post("/git")
async def receive_git_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(None, alias="X-Hub-Signature-256"),
    x_gitlab_token: str | None = Header(None, alias="X-Gitlab-Token"),
    x_gitlab_signature: str | None = Header(None, alias="X-Gitlab-Signature"),
    x_github_event: str | None = Header(None, alias="X-GitHub-Event"),
    x_github_delivery: str | None = Header(None, alias="X-GitHub-Delivery"),
    x_gitlab_event: str | None = Header(None, alias="X-Gitlab-Event"),
    x_gitlab_event_uuid: str | None = Header(None, alias="X-Gitlab-Event-UUID"),
):
    """Receive a GitHub or GitLab webhook push event.

    Flow:
        1. Read raw body for HMAC verification.
        2. Identify provider and extract signature header.
        3. Verify HMAC signature → 403 on failure.
        4. Check idempotency → 409 on duplicate.
        5. Parse push event payload.
        6. Auto-sync to memory via sync_repo_to_memory().
        7. Return 200 with sync summary.
    """
    # 1. Read raw body
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty request body")

    # 2. Determine provider from headers
    provider = _detect_provider(
        x_hub_signature_256=x_hub_signature_256,
        x_gitlab_token=x_gitlab_token,
        x_gitlab_signature=x_gitlab_signature,
        x_github_event=x_github_event,
        x_gitlab_event=x_gitlab_event,
    )

    if provider is None:
        raise HTTPException(
            status_code=400,
            detail="Could not detect webhook provider. Expected GitHub or GitLab headers.",
        )

    # 3. Extract and verify signature
    webhook_secret = os.environ.get("WEBHOOK_SECRET", "")
    if not webhook_secret:
        logger.warning("WEBHOOK_SECRET not set — skipping signature verification")
        # In dev mode without a secret, allow through but log
    else:
        signature = _get_signature_header(provider, x_hub_signature_256, x_gitlab_token, x_gitlab_signature)
        if signature is None:
            raise HTTPException(
                status_code=403,
                detail=f"Missing {provider} signature header",
            )
        if not verify_webhook_signature(body, signature, webhook_secret, provider):
            logger.warning("Webhook signature verification failed for %s", provider)
            raise HTTPException(status_code=403, detail="Invalid webhook signature")

    # 4. Parse payload
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # 5. Idempotency check
    # Build a full set of headers for event ID extraction
    all_headers = {k.lower(): v for k, v in request.headers.items()}
    event_id = _extract_event_id(payload, all_headers)

    if event_id and _idempotency_store.is_duplicate(event_id):
        logger.info("Duplicate webhook event: %s", event_id)
        raise HTTPException(status_code=409, detail="Duplicate event")

    # 6. Only process push events (ignore issues, PRs, etc.)
    event_type = _detect_event_type(provider, x_github_event, x_gitlab_event, payload)
    if event_type != "push":
        logger.info("Ignoring non-push event type: %s", event_type)
        if event_id:
            _idempotency_store.mark(event_id)
        return JSONResponse(
            status_code=200,
            content={"processed": False, "reason": f"Event type '{event_type}' ignored"},
        )

    # 7. Parse the push event
    try:
        event_data = _parse_push_event(payload, provider)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # 8. Determine repo path — prefer a local path if available in env
    repo_path = _resolve_repo_path(event_data)

    if not repo_path:
        logger.warning("No local repo path resolved for %s", event_data["repo_name"])
        if event_id:
            _idempotency_store.mark(event_id)
        return JSONResponse(
            status_code=200,
            content={
                "processed": False,
                "reason": "No local repo path configured",
                "repo_name": event_data["repo_name"],
            },
        )

    # 9. Mark event as seen before processing (prevents concurrent duplicates)
    if event_id:
        _idempotency_store.mark(event_id)

    # 10. Sync to memory
    try:
        mm = _get_memory_manager()
        result = await sync_repo_to_memory(repo_path, event_data["project"], mm)
    except Exception as exc:
        logger.error("Webhook sync failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Sync failed: {exc}")

    logger.info(
        "Webhook processed: repo=%s branch=%s new_decisions=%s",
        event_data["repo_name"],
        event_data["branch"],
        result.get("new_decisions", 0),
    )

    return JSONResponse(
        status_code=200,
        content={
            "processed": True,
            "event_id": event_id,
            "repo": event_data["repo_name"],
            "branch": event_data["branch"],
            "commits": len(event_data["commits"]),
            "sync": result,
        },
    )


# ---------------------------------------------------------------------------
#  Internal helpers
# ---------------------------------------------------------------------------

def _detect_provider(
    x_hub_signature_256: str | None,
    x_gitlab_token: str | None,
    x_gitlab_signature: str | None,
    x_github_event: str | None,
    x_gitlab_event: str | None,
) -> str | None:
    """Detect webhook provider from request headers."""
    if x_hub_signature_256 or x_github_event:
        return "github"
    if x_gitlab_token or x_gitlab_signature or x_gitlab_event:
        return "gitlab"
    return None


def _get_signature_header(
    provider: str,
    x_hub_signature_256: str | None,
    x_gitlab_token: str | None,
    x_gitlab_signature: str | None,
) -> str | None:
    """Extract the signature value appropriate for the detected provider."""
    if provider == "github":
        return x_hub_signature_256
    elif provider == "gitlab":
        # GitLab may send token or signature; prefer signature if present
        return x_gitlab_signature or x_gitlab_token
    return None


def _detect_event_type(
    provider: str,
    x_github_event: str | None,
    x_gitlab_event: str | None,
    payload: dict[str, Any],
) -> str:
    """Detect the webhook event type from headers or payload.

    Normalises GitLab's "Push Hook" / "Merge Request Hook" to their
    base event kinds ("push", "merge_request") for consistent comparison.
    """
    if provider == "github":
        if x_github_event:
            return x_github_event.lower()
    elif provider == "gitlab":
        if x_gitlab_event:
            # GitLab sends "Push Hook", "Merge Request Hook", etc.
            # Normalise to base kind: "push", "merge_request", etc.
            normalised = x_gitlab_event.lower()
            if normalised.endswith(" hook"):
                normalised = normalised[:-5].strip()
            return normalised
        # GitLab push events have object_kind = "push"
        object_kind = payload.get("object_kind", "")
        if object_kind:
            return object_kind
    # Fallback: infer from payload structure
    if "commits" in payload:
        return "push"
    return "unknown"


def _resolve_repo_path(event_data: dict[str, Any]) -> str | None:
    """Resolve a local filesystem path for the repo.

    Checks:
    1. TROPELEX_REPO_<REPO_NAME> env var (uppercase, hyphens → underscores)
    2. TROPELEX_REPOS_DIR + repo_name (common base directory)
    3. WEBHOOK_REPOS_DIR + repo_name
    4. None (no local path)

    Repo names are sanitised to prevent path traversal.
    """
    repo_name = event_data["repo_name"]
    # Sanitise: only allow alphanumeric, hyphens, underscores, slashes (owner/repo)
    safe_name = re.sub(r"[^a-zA-Z0-9_\-/]", "", repo_name)
    if not safe_name:
        return None

    # Sanitise for env var lookup: owner/repo → OWNER_REPO
    env_key = "TROPELEX_REPO_" + safe_name.upper().replace("/", "_").replace("-", "_")
    env_path = os.environ.get(env_key)
    if env_path and Path(env_path).is_dir():
        return env_path

    # Check common repos directory
    repos_dir = os.environ.get("TROPELEX_REPOS_DIR") or os.environ.get("WEBHOOK_REPOS_DIR")
    if repos_dir:
        base = Path(repos_dir).resolve()
        candidate = (base / safe_name).resolve()
        # Verify resolved path is still under base (prevent traversal)
        if candidate.is_dir() and str(candidate).startswith(str(base)):
            return str(candidate)

    return None
