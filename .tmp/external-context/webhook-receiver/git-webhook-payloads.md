---
source: Official GitHub/GitLab docs
library: git-webhooks
topic: Git webhook payloads for push events
fetched: 2026-07-16T00:00:00Z
official_docs:
  - https://docs.github.com/en/webhooks/webhook-events-and-payloads
  - https://docs.gitlab.com/user/project/integrations/webhook_events/
---

# Git Webhook Payloads (Push Events)

## GitHub Push Event

### Headers
| Header | Value |
|--------|-------|
| `X-GitHub-Event` | `push` |
| `X-GitHub-Delivery` | Unique delivery ID |
| `X-Hub-Signature-256` | `sha256={hex_signature}` |
| `X-GitHub-Hook-ID` | Hook identifier |

### Payload Structure
```json
{
  "ref": "refs/heads/main",
  "before": "95790bf891e76fee5e1747ab589903a6a1f80f22",
  "after": "da1560886d4f094c3e6c9ef40349f7d38b5d27d7",
  "repository": {
    "id": 123456,
    "name": "my-repo",
    "full_name": "owner/my-repo",
    "clone_url": "https://github.com/owner/my-repo.git",
    "ssh_url": "git@github.com:owner/my-repo.git",
    "default_branch": "main",
    "private": false
  },
  "pusher": {
    "name": "username",
    "email": "user@example.com"
  },
  "sender": {
    "login": "username",
    "id": 12345,
    "type": "User"
  },
  "commits": [
    {
      "id": "da1560886d4f094c3e6c9ef40349f7d38b5d27d7",
      "message": "feat: add auto-sync functionality",
      "timestamp": "2026-07-16T10:00:00+00:00",
      "url": "https://github.com/owner/my-repo/commit/da156088...",
      "author": {
        "name": "Developer",
        "email": "dev@example.com",
        "username": "devuser"
      },
      "added": ["src/new_file.py"],
      "modified": ["src/existing.py"],
      "removed": []
    }
  ],
  "head_commit": {
    "id": "da1560886d4f094c3e6c9ef40349f7d38b5d27d7",
    "message": "feat: add auto-sync functionality",
    "distinct": true
  },
  "created": false,
  "deleted": false,
  "forced": false,
  "compare": "https://github.com/owner/my-repo/compare/95790bf...da156088"
}
```

### Key Fields for Auto-Sync
- `ref` — branch ref that was pushed to (parse branch name: `refs/heads/main` → `main`)
- `after` — latest commit SHA after push
- `before` — commit SHA before push
- `head_commit.id` — HEAD commit of the push
- `commits[].distinct` — `true` if this commit is new (not on target branch before)
- `commits[].added` — new files
- `commits[].modified` — modified files
- `commits[].removed` — deleted files
- `repository.clone_url` — HTTPS clone URL
- `repository.ssh_url` — SSH clone URL
- `forced` — `true` if force push (DANGER — may need special handling)
- `created` — `true` if new branch created
- `deleted` — `true` if branch deleted

### Branch Extraction
```python
def extract_branch(ref: str) -> str:
    """Extract branch name from refs/heads/main."""
    if ref.startswith("refs/heads/"):
        return ref[len("refs/heads/"):]
    return ref

# "refs/heads/main" → "main"
# "refs/heads/feature/auto-sync" → "feature/auto-sync"
# "refs/tags/v1.0.0" → "v1.0.0" (tag push, different event)
```

### Force Push Detection
```python
if payload.get("forced"):
    # Force push detected — may need full re-sync
    # Don't just apply deltas — re-clone or reset
    await handle_force_push(payload)
```

## GitLab Push Event

### Headers
| Header | Value |
|--------|-------|
| `X-Gitlab-Event` | `Push Hook` |
| `X-Gitlab-Webhook-UUID` | Unique delivery ID |
| `Idempotency-Key` | Same as webhook-id (17.4+) |
| `webhook-id` | Standard Webhooks ID (19.0+) |
| `webhook-timestamp` | Unix timestamp (19.0+) |
| `webhook-signature` | `v1,{base64}` (19.0+ with signing token) |
| `X-Gitlab-Token` | Secret token (legacy) |

### Payload Structure
```json
{
  "object_kind": "push",
  "event_name": "push",
  "before": "95790bf891e76fee5e1747ab589903a6a1f80f22",
  "after": "da1560886d4f094c3e6c9ef40349f7d38b5d27d7",
  "ref": "refs/heads/master",
  "checkout_sha": "da1560886d4f094c3e6c9ef40349f7d38b5d27d7",
  "user_id": 4,
  "user_name": "John Smith",
  "user_username": "jsmith",
  "user_email": "john@example.com",
  "project_id": 15,
  "project": {
    "id": 15,
    "name": "Diaspora",
    "description": "",
    "web_url": "http://example.com/mike/diaspora",
    "git_ssh_url": "git@example.com:mike/diaspora.git",
    "git_http_url": "http://example.com/mike/diaspora.git",
    "namespace": "Mike",
    "path_with_namespace": "mike/diaspora",
    "default_branch": "master"
  },
  "commits": [
    {
      "id": "da1560886d4f094c3e6c9ef40349f7d38b5d27d7",
      "message": "add new feature",
      "timestamp": "2012-01-03T23:36:29+02:00",
      "url": "http://example.com/mike/diaspora/commit/da1560886d4f094c3e6c9ef40349f7d38b5d27d7",
      "author": {
        "name": "John Smith",
        "email": "john@example.com"
      },
      "added": ["file.txt"],
      "modified": [],
      "removed": []
    }
  ],
  "total_commits_count": 1
}
```

### Key Differences from GitHub
- `user_username` field (GitHub uses `pusher.name`)
- `project_id` field (GitHub uses `repository.id`)
- `checkout_sha` — the SHA that was checked out
- `total_commits_count` — actual count (payload caps at 20 commits)
- `commits` array capped at 20 — use `total_commits_count` for real count
- `created` — branch created without new commits → `commits` is empty
- No `distinct` field on commits (use `before`/`after` comparison)

### GitLab Limits
- Max 20 commits detailed in payload (check `total_commits_count`)
- Pushes with >3 branches by default are skipped (configurable)
- Max 20 commits per push in payload
- If branch created with no commits, `commits` is empty

## Handling for Auto-Sync

### Push Event Processing
```python
async def handle_push_event(provider: str, payload: dict):
    branch = extract_branch(payload["ref"])
    after_sha = payload["after"]
    before_sha = payload["before"]

    # Skip deleted branches
    if payload.get("deleted"):
        return await handle_branch_deleted(provider, branch)

    # Handle force push — needs full re-sync
    if payload.get("forced"):
        return await handle_force_push(provider, branch, after_sha)

    # Extract changed files from commits
    if provider == "github":
        changed_files = extract_github_changes(payload["commits"])
    elif provider == "gitlab":
        changed_files = extract_gitlab_changes(payload["commits"])

    # Trigger sync
    await sync_service.sync(
        provider=provider,
        branch=branch,
        from_sha=before_sha,
        to_sha=after_sha,
        changed_files=changed_files
    )

def extract_github_changes(commits: list) -> dict:
    """GitHub commits have 'distinct' field."""
    all_added = []
    all_modified = []
    all_removed = []

    for commit in commits:
        if commit.get("distinct", True):  # Only distinct commits
            all_added.extend(commit.get("added", []))
            all_modified.extend(commit.get("modified", []))
            all_removed.extend(commit.get("removed", []))

    return {
        "added": list(set(all_added)),
        "modified": list(set(all_modified)),
        "removed": list(set(all_removed))
    }

def extract_gitlab_changes(commits: list) -> dict:
    """GitLab commits don't have 'distinct' field."""
    all_added = []
    all_modified = []
    all_removed = []

    for commit in commits:
        all_added.extend(commit.get("added", []))
        all_modified.extend(commit.get("modified", []))
        all_removed.extend(commit.get("removed", []))

    return {
        "added": list(set(all_added)),
        "modified": list(set(all_modified)),
        "removed": list(set(all_removed))
    }
```

### Event Type Dispatch
```python
async def handle_webhook(request: Request):
    # Detect provider
    if "X-Hub-Signature-256" in request.headers:
        provider = "github"
    elif "X-Gitlab-Event" in request.headers:
        provider = "gitlab"
    else:
        raise HTTPException(400, "Unknown provider")

    # Verify signature
    body = await verify_signature(request, provider)

    # Dispatch by event type
    if provider == "github":
        event_type = request.headers.get("X-GitHub-Event")
    else:
        event_type = request.headers.get("X-Gitlab-Event")

    match (provider, event_type):
        case ("github", "push"):
            await handle_push_event("github", body)
        case ("github", "ping"):
            return {"msg": "pong"}
        case ("gitlab", "Push Hook"):
            await handle_push_event("gitlab", body)
        case _:
            logger.info(f"Ignoring event: {provider}/{event_type}")

    return {"status": "ok"}
```

## Quick Reference

| Field | GitHub | GitLab | Notes |
|-------|--------|--------|-------|
| Branch ref | `ref` | `ref` | Same format: `refs/heads/main` |
| After SHA | `after` | `after` | Latest commit |
| Before SHA | `before` | `before` | Previous HEAD |
| Commits | `commits[]` | `commits[]` | GitLab caps at 20 |
| Changed files | `commits[].added/modified/removed` | Same | Both use arrays |
| Force push | `forced` | — | GitHub only |
| New branch | `created` | — | GitHub only |
| Branch deleted | `deleted` | — | GitHub only |
| Clone URL | `repository.clone_url` | `project.git_http_url` | Different key paths |
| Pusher | `pusher.name` | `user_username` | Different field names |
| Repo name | `repository.name` | `project.name` | Different key paths |
| Event ID | `X-GitHub-Delivery` | `webhook-id` / `X-Gitlab-Webhook-UUID` | For idempotency |
