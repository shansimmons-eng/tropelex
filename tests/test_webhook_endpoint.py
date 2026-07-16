"""
Integration tests for the webhook POST endpoint (core.webhooks.router).

Uses httpx.AsyncClient with FastAPI TestClient pattern.
Tests cover: signature verification, idempotency, push event parsing,
provider detection, and sync integration.
"""

import hashlib
import hmac
import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from core.webhooks.router import (
    _detect_event_type,
    _detect_provider,
    _extract_event_id,
    _parse_github_push,
    _parse_gitlab_push,
    _resolve_repo_path,
    _sanitise_project_name,
    _idempotency_store,
    webhook_router,
)


def _app():
    """Create a FastAPI app with the webhook router included."""
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(webhook_router)
    return app


def _hmac_sha256(payload: bytes, secret: str) -> str:
    """Helper: compute HMAC-SHA256 hex digest."""
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
#  Sample payloads
# ---------------------------------------------------------------------------

GITHUB_PUSH_PAYLOAD: dict[str, Any] = {
    "ref": "refs/heads/main",
    "after": "abc123def456",
    "repository": {
        "full_name": "octocat/Hello-World",
        "clone_url": "https://github.com/octocat/Hello-World.git",
        "html_url": "https://github.com/octocat/Hello-World",
    },
    "commits": [
        {
            "id": "abc123def456789",
            "message": "feat: add webhook endpoint",
            "author": {"name": "Alice"},
        },
        {
            "id": "def789abc123456",
            "message": "fix: validate signature",
            "author": {"name": "Bob"},
        },
    ],
}

GITLAB_PUSH_PAYLOAD: dict[str, Any] = {
    "object_kind": "push",
    "ref": "refs/heads/main",
    "after": "789abc123def456",
    "project": {
        "path_with_namespace": "mygroup/myproject",
        "git_http_url": "https://gitlab.com/mygroup/myproject.git",
        "git_ssh_url": "git@gitlab.com:mygroup/myproject.git",
    },
    "commits": [
        {
            "id": "789abc123def4567890",
            "message": "refactor: simplify router",
            "author": {"name": "Charlie"},
        },
    ],
    "object_attributes": {"id": 9901},
}


# ---------------------------------------------------------------------------
#  Unit tests: helper functions
# ---------------------------------------------------------------------------


class TestSanitiseProjectName:
    def test_owner_repo(self):
        assert _sanitise_project_name("octocat/Hello-World") == "Hello-World"

    def test_path_with_namespace(self):
        assert _sanitise_project_name("mygroup/myproject") == "myproject"

    def test_simple_name(self):
        assert _sanitise_project_name("simple") == "simple"

    def test_strips_special_chars(self):
        result = _sanitise_project_name("owner/repo name!@#$%")
        assert result.isalnum() or all(c in "-_" for c in result)

    def test_max_length(self):
        long_name = "a" * 200
        assert len(_sanitise_project_name(long_name)) <= 100


class TestDetectProvider:
    def test_github_by_signature(self):
        assert _detect_provider("sha256=abc", None, None, None, None) == "github"

    def test_github_by_event_header(self):
        assert _detect_provider(None, None, None, "push", None) == "github"

    def test_gitlab_by_token(self):
        assert _detect_provider(None, "token-xyz", None, None, None) == "gitlab"

    def test_gitlab_by_signature(self):
        assert _detect_provider(None, None, "sha256=abc", None, None) == "gitlab"

    def test_gitlab_by_event(self):
        assert _detect_provider(None, None, None, None, "Push Hook") == "gitlab"

    def test_unknown_returns_none(self):
        assert _detect_provider(None, None, None, None, None) is None


class TestExtractEventId:
    def test_github_delivery_header(self):
        headers = {"x-github-delivery": "abc-123"}
        assert _extract_event_id({}, headers) == "abc-123"

    def test_gitlab_event_uuid(self):
        headers = {"x-gitlab-event-uuid": "uuid-456"}
        assert _extract_event_id({}, headers) == "uuid-456"

    def test_gitlab_object_attributes_id(self):
        payload = {"object_attributes": {"id": 42}}
        assert _extract_event_id(payload, {}) == "gl-42"

    def test_github_after_sha(self):
        payload = {
            "after": "abc123",
            "repository": {"full_name": "owner/repo"},
        }
        assert _extract_event_id(payload, {}) == "gh-owner/repo-abc123"

    def test_no_event_id_returns_none(self):
        assert _extract_event_id({}, {}) is None


class TestDetectEventType:
    def test_github_push(self):
        assert _detect_event_type("github", "push", None, {}) == "push"

    def test_github_issues(self):
        assert _detect_event_type("github", "issues", None, {}) == "issues"

    def test_gitlab_push_header(self):
        assert _detect_event_type("gitlab", None, "Push Hook", {}) == "push"

    def test_gitlab_object_kind(self):
        payload = {"object_kind": "push"}
        assert _detect_event_type("gitlab", None, None, payload) == "push"

    def test_fallback_commits_in_payload(self):
        payload = {"commits": []}
        assert _detect_event_type("unknown", None, None, payload) == "push"


class TestParseGithubPush:
    def test_basic_push(self):
        result = _parse_github_push(GITHUB_PUSH_PAYLOAD)
        assert result["repo_name"] == "octocat/Hello-World"
        assert result["branch"] == "main"
        assert result["project"] == "Hello-World"
        assert len(result["commits"]) == 2
        assert result["head_commit"] == "abc123def456"
        assert result["commits"][0]["sha"] == "abc123de"

    def test_branch_extracts_from_ref(self):
        payload = {**GITHUB_PUSH_PAYLOAD, "ref": "refs/heads/feature/test"}
        result = _parse_github_push(payload)
        assert result["branch"] == "feature/test"

    def test_empty_commits(self):
        payload = {**GITHUB_PUSH_PAYLOAD, "commits": []}
        result = _parse_github_push(payload)
        assert result["commits"] == []


class TestParseGitlabPush:
    def test_basic_push(self):
        result = _parse_gitlab_push(GITLAB_PUSH_PAYLOAD)
        assert result["repo_name"] == "mygroup/myproject"
        assert result["branch"] == "main"
        assert result["project"] == "myproject"
        assert len(result["commits"]) == 1
        assert result["head_commit"] == "789abc123def456"

    def test_empty_commits(self):
        payload = {**GITLAB_PUSH_PAYLOAD, "commits": []}
        result = _parse_gitlab_push(payload)
        assert result["commits"] == []


class TestResolveRepoPath:
    def test_env_var_lookup(self, monkeypatch):
        monkeypatch.setenv("TROPELEX_REPO_OCTOCAT_HELLO_WORLD", "/tmp/repo")
        event_data = {"repo_name": "octocat/Hello-World"}
        with patch("pathlib.Path.is_dir", return_value=True):
            result = _resolve_repo_path(event_data)
        assert result == "/tmp/repo"

    def test_repos_dir_lookup(self, monkeypatch):
        monkeypatch.delenv("TROPELEX_REPO_OCTOCAT_HELLO_WORLD", raising=False)
        monkeypatch.setenv("TROPELEX_REPOS_DIR", "/tmp/repos")
        event_data = {"repo_name": "octocat/Hello-World"}
        with patch("pathlib.Path.is_dir", return_value=True):
            result = _resolve_repo_path(event_data)
        assert result == "/tmp/repos/octocat/Hello-World"

    def test_no_path_returns_none(self, monkeypatch):
        monkeypatch.delenv("TROPELEX_REPO_OCTOCAT_HELLO_WORLD", raising=False)
        monkeypatch.delenv("TROPELEX_REPOS_DIR", raising=False)
        monkeypatch.delenv("WEBHOOK_REPOS_DIR", raising=False)
        event_data = {"repo_name": "octocat/Hello-World"}
        assert _resolve_repo_path(event_data) is None


# ---------------------------------------------------------------------------
#  Integration tests: webhook endpoint
# ---------------------------------------------------------------------------


@pytest.fixture
def secret():
    """Webhook secret used for signing test payloads."""
    return "test-webhook-secret-123"


@pytest.fixture
def signed_github_headers(secret):
    """Build GitHub webhook headers with a valid HMAC signature."""
    payload_bytes = json.dumps(GITHUB_PUSH_PAYLOAD).encode()
    sig = "sha256=" + _hmac_sha256(payload_bytes, secret)
    return {
        "X-Hub-Signature-256": sig,
        "X-GitHub-Event": "push",
        "X-GitHub-Delivery": "test-delivery-001",
    }


@pytest.fixture
def signed_gitlab_headers(secret):
    """Build GitLab webhook headers with a valid HMAC signature."""
    payload_bytes = json.dumps(GITLAB_PUSH_PAYLOAD).encode()
    sig = _hmac_sha256(payload_bytes, secret)
    return {
        "X-Gitlab-Signature": sig,
        "X-Gitlab-Event": "Push Hook",
        "X-Gitlab-Event-UUID": "gl-uuid-001",
    }


class TestWebhookEndpoint:
    """Integration tests using the FastAPI test client via httpx."""

    @pytest.fixture(autouse=True)
    def _setup_env(self, monkeypatch, secret):
        """Set WEBHOOK_SECRET and mock sync_repo_to_memory for all endpoint tests."""
        monkeypatch.setenv("WEBHOOK_SECRET", secret)
        monkeypatch.setenv("TROPELEX_REPOS_DIR", "/tmp/test-repos")
        # Clear idempotency store so tests don't collide on event IDs
        _idempotency_store._store.clear()

    async def test_github_push_valid_signature(self, signed_github_headers):
        """Valid GitHub push with correct HMAC → 200 with sync result."""
        from httpx import ASGITransport, AsyncClient

        mock_sync = AsyncMock(return_value={
            "synced": True,
            "new_decisions": 1,
            "stack": ["Python"],
        })
        with patch("core.webhooks.router.sync_repo_to_memory", mock_sync), \
             patch("core.webhooks.router._resolve_repo_path", return_value="/tmp/test-repos/Hello-World"), \
             patch("core.webhooks.router._get_memory_manager"):
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/webhooks/git",
                    content=json.dumps(GITHUB_PUSH_PAYLOAD),
                    headers=signed_github_headers,
                )
        assert resp.status_code == 200
        body = resp.json()
        assert body["processed"] is True
        assert body["repo"] == "octocat/Hello-World"
        assert body["branch"] == "main"
        assert body["commits"] == 2
        assert body["sync"]["new_decisions"] == 1

    async def test_github_invalid_signature(self, secret):
        """Invalid HMAC signature → 403."""
        from httpx import ASGITransport, AsyncClient

        payload_bytes = json.dumps(GITHUB_PUSH_PAYLOAD).encode()
        bad_sig = "sha256=" + _hmac_sha256(payload_bytes, "wrong-secret")
        headers = {
            "X-Hub-Signature-256": bad_sig,
            "X-GitHub-Event": "push",
            "X-GitHub-Delivery": "test-bad-sig",
        }
        async with AsyncClient(
            transport=ASGITransport(app=_app()), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/webhooks/git",
                content=json.dumps(GITHUB_PUSH_PAYLOAD),
                headers=headers,
            )
        assert resp.status_code == 403
        assert "Invalid webhook signature" in resp.json()["detail"]

    async def test_missing_signature_header(self):
        """Missing signature header → 403."""
        from httpx import ASGITransport, AsyncClient

        headers = {
            "X-GitHub-Event": "push",
            "X-GitHub-Delivery": "test-no-sig",
        }
        async with AsyncClient(
            transport=ASGITransport(app=_app()), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/webhooks/git",
                content=json.dumps(GITHUB_PUSH_PAYLOAD),
                headers=headers,
            )
        assert resp.status_code == 403
        assert "Missing" in resp.json()["detail"]

    async def test_duplicate_event_returns_409(self, signed_github_headers):
        """Second delivery with the same event ID → 409."""
        from httpx import ASGITransport, AsyncClient

        mock_sync = AsyncMock(return_value={
            "synced": True,
            "new_decisions": 0,
            "stack": [],
        })
        with patch("core.webhooks.router.sync_repo_to_memory", mock_sync), \
             patch("core.webhooks.router._resolve_repo_path", return_value="/tmp/test-repos/Hello-World"), \
             patch("core.webhooks.router._get_memory_manager"):
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                # First delivery — should succeed
                resp1 = await client.post(
                    "/api/webhooks/git",
                    content=json.dumps(GITHUB_PUSH_PAYLOAD),
                    headers=signed_github_headers,
                )
                assert resp1.status_code == 200

                # Second delivery with same event ID — should be duplicate
                resp2 = await client.post(
                    "/api/webhooks/git",
                    content=json.dumps(GITHUB_PUSH_PAYLOAD),
                    headers=signed_github_headers,
                )
        assert resp2.status_code == 409
        assert "Duplicate event" in resp2.json()["detail"]

    async def test_gitlab_push_valid_signature(self, signed_gitlab_headers):
        """Valid GitLab push with correct HMAC → 200."""
        from httpx import ASGITransport, AsyncClient

        mock_sync = AsyncMock(return_value={
            "synced": True,
            "new_decisions": 1,
            "stack": ["Python"],
        })
        with patch("core.webhooks.router.sync_repo_to_memory", mock_sync), \
             patch("core.webhooks.router._resolve_repo_path", return_value="/tmp/test-repos/myproject"), \
             patch("core.webhooks.router._get_memory_manager"):
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/webhooks/git",
                    content=json.dumps(GITLAB_PUSH_PAYLOAD),
                    headers=signed_gitlab_headers,
                )
        assert resp.status_code == 200
        body = resp.json()
        assert body["processed"] is True
        assert body["repo"] == "mygroup/myproject"
        assert body["branch"] == "main"
        assert body["commits"] == 1

    async def test_non_push_event_ignored(self, secret):
        """Non-push events (e.g. issues) → 200 with processed=False."""
        from httpx import ASGITransport, AsyncClient

        issues_payload = {
            "action": "opened",
            "issue": {"title": "Bug report"},
        }
        payload_bytes = json.dumps(issues_payload).encode()
        sig = "sha256=" + _hmac_sha256(payload_bytes, secret)
        headers = {
            "X-Hub-Signature-256": sig,
            "X-GitHub-Event": "issues",
            "X-GitHub-Delivery": "test-issues-001",
        }
        async with AsyncClient(
            transport=ASGITransport(app=_app()), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/webhooks/git",
                content=json.dumps(issues_payload),
                headers=headers,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["processed"] is False
        assert "issues" in body["reason"]

    async def test_empty_body_returns_400(self, secret):
        """Empty request body → 400."""
        from httpx import ASGITransport, AsyncClient

        sig = "sha256=" + _hmac_sha256(b"", secret)
        headers = {
            "X-Hub-Signature-256": sig,
            "X-GitHub-Event": "push",
        }
        async with AsyncClient(
            transport=ASGITransport(app=_app()), base_url="http://test"
        ) as client:
            resp = await client.post("/api/webhooks/git", content=b"", headers=headers)
        assert resp.status_code == 400
        assert "Empty request body" in resp.json()["detail"]

    async def test_invalid_json_payload(self, secret):
        """Malformed JSON body → 400."""
        from httpx import ASGITransport, AsyncClient

        bad_json = b"{not valid json}"
        sig = "sha256=" + _hmac_sha256(bad_json, secret)
        headers = {
            "X-Hub-Signature-256": sig,
            "X-GitHub-Event": "push",
            "X-GitHub-Delivery": "test-bad-json",
        }
        async with AsyncClient(
            transport=ASGITransport(app=_app()), base_url="http://test"
        ) as client:
            resp = await client.post("/api/webhooks/git", content=bad_json, headers=headers)
        assert resp.status_code == 400
        assert "Invalid JSON" in resp.json()["detail"]

    async def test_no_local_repo_returns_200_not_processed(self, signed_github_headers):
        """When no local repo path is resolved → 200 with processed=False."""
        from httpx import ASGITransport, AsyncClient

        with patch("core.webhooks.router._resolve_repo_path", return_value=None):
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/webhooks/git",
                    content=json.dumps(GITHUB_PUSH_PAYLOAD),
                    headers=signed_github_headers,
                )
        assert resp.status_code == 200
        body = resp.json()
        assert body["processed"] is False
        assert "No local repo path" in body["reason"]

    async def test_no_provider_detected(self, secret):
        """Request with no provider headers → 400."""
        from httpx import ASGITransport, AsyncClient

        # Send payload with no GitHub/GitLab headers at all
        async with AsyncClient(
            transport=ASGITransport(app=_app()), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/webhooks/git",
                content=json.dumps({"data": "test"}),
            )
        assert resp.status_code == 400
        assert "Could not detect" in resp.json()["detail"]

    async def test_sync_failure_returns_500(self, signed_github_headers):
        """When sync_repo_to_memory raises → 500."""
        from httpx import ASGITransport, AsyncClient

        mock_sync = AsyncMock(side_effect=RuntimeError("disk full"))
        with patch("core.webhooks.router.sync_repo_to_memory", mock_sync), \
             patch("core.webhooks.router._resolve_repo_path", return_value="/tmp/test-repos/Hello-World"), \
             patch("core.webhooks.router._get_memory_manager"):
            async with AsyncClient(
                transport=ASGITransport(app=_app()), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/webhooks/git",
                    content=json.dumps(GITHUB_PUSH_PAYLOAD),
                    headers=signed_github_headers,
                )
        assert resp.status_code == 500
        assert "Sync failed" in resp.json()["detail"]
