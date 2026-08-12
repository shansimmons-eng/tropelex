"""
Tests for enhanced Git integration.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.git_integration import (
    _classify_files,
    _detect_dependency_changes,
    _detect_structural_changes,
    _extract_rationale,
    _extract_revert_target,
    _is_revert,
    _summarize_commit_decision,
    extract_deep_decisions,
    extract_decisions_from_commits,
    get_project_repo_path,
    get_repo_fingerprint,
    get_repo_summary,
    detect_tech_stack,
    detect_tech_stack_changes,
    sync_repo_to_memory,
)


class TestClassifyFiles:
    def test_ui_files(self):
        assert "ui" in _classify_files(["src/App.tsx", "styles/main.css"])

    def test_backend_files(self):
        cats = _classify_files(["src/handler.py", "api/routes.go"])
        assert "backend" in cats

    def test_test_files(self):
        assert "testing" in _classify_files(["tests/test_app.py", "src/app.spec.ts"])

    def test_mixed_files(self):
        cats = _classify_files(["src/App.tsx", "api/handler.py", "tests/test_api.py"])
        assert "ui" in cats
        assert "backend" in cats
        assert "testing" in cats

    def test_empty_list(self):
        assert _classify_files([]) == []

    def test_config_files(self):
        cats = _classify_files(["config.yaml", "settings.toml"])
        assert "config" in cats

    def test_docker_files(self):
        cats = _classify_files(["Dockerfile", "docker-compose.yml"])
        assert "devops" in cats


class TestExtractRationale:
    def test_because_pattern(self):
        body = "Switched to async because the old sync approach was blocking."
        result = _extract_rationale(body)
        assert result is not None
        assert "because" in result.lower()

    def test_no_rationale(self):
        assert _extract_rationale("Just a short message") is None

    def test_empty_body(self):
        assert _extract_rationale("") is None

    def test_multiple_rationale_lines(self):
        body = "Motivation: performance was bad\nTo fix: switched to cache"
        result = _extract_rationale(body)
        assert result is not None


class TestIsRevert:
    def test_revert_prefix(self):
        assert _is_revert("Revert \"feat: add button\"") is True

    def test_normal_commit(self):
        assert _is_revert("feat: add button") is False

    def test_revert_in_subject(self):
        assert _is_revert("reverting changes to API") is True

    def test_undo(self):
        assert _is_revert("undo database migration") is True


class TestExtractRevertTarget:
    def test_revert_quoted(self):
        target = _extract_revert_target('Revert "feat: add button"')
        assert target == "feat: add button"

    def test_revert_hash(self):
        target = _extract_revert_target("Revert abc1234")
        assert target == "abc1234"

    def test_no_target(self):
        assert _extract_revert_target("normal commit") is None


class TestDetectStructuralChanges:
    def test_tests_touched(self):
        result = _detect_structural_changes(["tests/test_app.py", "tests/test_api.py"])
        assert result["tests_touched"] == 2

    def test_migrations(self):
        result = _detect_structural_changes(["migrations/001_init.sql"])
        assert result["migrations"] == 1

    def test_config_changes(self):
        result = _detect_structural_changes(["config.json", "settings.yaml"])
        assert result["config_changes"] == 2

    def test_no_signals(self):
        assert _detect_structural_changes([]) is None


class TestSummarizeCommitDecision:
    def test_basic_summary(self):
        entry = {"subject": "feat: add dark mode", "categories": ["ui"]}
        summary = _summarize_commit_decision(entry)
        assert "add dark mode" in summary
        assert "ui" in summary

    def test_with_rationale(self):
        entry = {
            "subject": "refactor: use async",
            "categories": ["backend"],
            "rationale": "Performance was bad with sync",
        }
        summary = _summarize_commit_decision(entry)
        assert "async" in summary
        assert "Performance" in summary

    def test_with_dep_changes(self):
        entry = {
            "subject": "chore: update deps",
            "dependency_changes": [{"file": "requirements.txt", "added": ["httpx"], "removed": ["requests"]}],
        }
        summary = _summarize_commit_decision(entry)
        assert "httpx" in summary
        assert "requests" in summary


class TestExtractDecisionsFromCommits:
    def test_conventional_commits(self):
        commits = [
            {"hash": "abc1234", "subject": "feat: add login page", "author": "dev", "date": "2026-01-15"},
            {"hash": "def5678", "subject": "fix: resolve null pointer", "author": "dev", "date": "2026-01-16"},
            {"hash": "ghi9012", "subject": "update readme", "author": "dev", "date": "2026-01-17"},
        ]
        decisions = extract_decisions_from_commits(commits)
        assert len(decisions) == 2
        assert decisions[0]["hash"] == "abc1234"

    def test_empty_commits(self):
        assert extract_decisions_from_commits([]) == []


class TestDetectTechStackChanges:
    def test_no_changes(self):
        with patch("core.git_integration.detect_tech_stack", return_value=["Python", "FastAPI"]):
            result = detect_tech_stack_changes("/some/path", ["Python", "FastAPI"])
            assert result["changed"] is False

    def test_with_mock(self):
        with patch("core.git_integration.detect_tech_stack", return_value=["Python", "React"]):
            result = detect_tech_stack_changes("/some/path", ["Python", "FastAPI"])
            assert result["changed"] is True
            assert "React" in result["added"]
            assert "FastAPI" in result["removed"]


def _make_repo(path: Path, commit_msg: str) -> None:
    """Init a git repo at `path` with one commit."""
    import subprocess

    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=path, check=True)
    (path / "f.txt").write_text(commit_msg)
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", commit_msg], cwd=path, check=True)


class TestGetRepoFingerprint:
    def test_fingerprint_falls_back_to_root_commit_without_remote(self, tmp_path):
        repo = tmp_path / "repo"
        _make_repo(repo, "init")
        fp = get_repo_fingerprint(str(repo))
        assert fp is not None
        assert len(fp) == 40  # a commit hash

    def test_same_repo_same_fingerprint(self, tmp_path):
        repo = tmp_path / "repo"
        _make_repo(repo, "init")
        assert get_repo_fingerprint(str(repo)) == get_repo_fingerprint(str(repo))

    def test_different_repos_different_fingerprints(self, tmp_path):
        repo_a = tmp_path / "a"
        repo_b = tmp_path / "b"
        _make_repo(repo_a, "init a")
        _make_repo(repo_b, "init b")
        assert get_repo_fingerprint(str(repo_a)) != get_repo_fingerprint(str(repo_b))

    def test_non_git_dir_returns_none(self, tmp_path):
        empty = tmp_path / "not-a-repo"
        empty.mkdir()
        assert get_repo_fingerprint(str(empty)) is None


class _FakeMemoryManager:
    """Minimal in-memory stand-in for MemoryManager, scoped to one test."""

    def __init__(self):
        self.store: dict[str, dict] = {}

    def get_project_memory(self, name: str) -> dict:
        return self.store.setdefault(name, {})

    def save_project_memory(self, name: str, mem: dict) -> None:
        self.store[name] = mem


class TestSyncRepoFingerprintGuard:
    """Regression coverage for the contamination-prevention safeguard: a
    project's git sync should refuse to silently mix in a different repo's
    commit history once it's been synced from one repo before."""

    @pytest.mark.asyncio
    async def test_first_sync_stores_fingerprint_and_succeeds(self, tmp_path):
        repo = tmp_path / "repo"
        _make_repo(repo, "init")
        mm = _FakeMemoryManager()

        result = await sync_repo_to_memory(str(repo), "proj", mm)

        assert result["synced"] is True
        assert mm.store["proj"]["git_repo_fingerprint"] == get_repo_fingerprint(str(repo))

    @pytest.mark.asyncio
    async def test_second_sync_same_repo_succeeds(self, tmp_path):
        repo = tmp_path / "repo"
        _make_repo(repo, "init")
        mm = _FakeMemoryManager()

        await sync_repo_to_memory(str(repo), "proj", mm)
        result = await sync_repo_to_memory(str(repo), "proj", mm)

        assert result["synced"] is True

    @pytest.mark.asyncio
    async def test_sync_from_different_repo_is_blocked(self, tmp_path):
        repo_a = tmp_path / "a"
        repo_b = tmp_path / "b"
        _make_repo(repo_a, "init a")
        _make_repo(repo_b, "init b")
        mm = _FakeMemoryManager()

        await sync_repo_to_memory(str(repo_a), "proj", mm)
        result = await sync_repo_to_memory(str(repo_b), "proj", mm)

        assert result["synced"] is False
        assert result["fingerprint_mismatch"] is True
        assert result["previous_repo"] == get_repo_fingerprint(str(repo_a))
        assert result["current_repo"] == get_repo_fingerprint(str(repo_b))

    @pytest.mark.asyncio
    async def test_force_overrides_mismatch(self, tmp_path):
        repo_a = tmp_path / "a"
        repo_b = tmp_path / "b"
        _make_repo(repo_a, "init a")
        _make_repo(repo_b, "init b")
        mm = _FakeMemoryManager()

        await sync_repo_to_memory(str(repo_a), "proj", mm)
        result = await sync_repo_to_memory(str(repo_b), "proj", mm, force=True)

        assert result["synced"] is True


class TestGetProjectRepoPath:
    """Doc Mining / pytest count / git summary use this to find a
    project's own repo instead of silently falling back to whichever repo
    Tropelex itself is installed in."""

    def test_no_repo_path_returns_none(self):
        assert get_project_repo_path({}) is None

    def test_repo_path_missing_from_disk_returns_none(self):
        assert get_project_repo_path({"repo_path": "/nonexistent/path/xyz"}) is None

    def test_valid_repo_path_returned(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        assert get_project_repo_path({"repo_path": str(repo)}) == str(repo)

    @pytest.mark.asyncio
    async def test_sync_persists_repo_path(self, tmp_path):
        repo = tmp_path / "repo"
        _make_repo(repo, "init")
        mm = _FakeMemoryManager()

        await sync_repo_to_memory(str(repo), "proj", mm)

        assert mm.store["proj"]["repo_path"] == str(repo)
        assert get_project_repo_path(mm.store["proj"]) == str(repo)

    @pytest.mark.asyncio
    async def test_resync_updates_repo_path_to_new_location(self, tmp_path):
        """Unlike the fingerprint identity check, repo_path itself should
        track wherever the checkout currently lives."""
        repo = tmp_path / "repo"
        _make_repo(repo, "init")
        mm = _FakeMemoryManager()

        await sync_repo_to_memory(str(repo), "proj", mm)
        moved = tmp_path / "repo_moved"
        repo.rename(moved)
        await sync_repo_to_memory(str(moved), "proj", mm, force=True)

        assert mm.store["proj"]["repo_path"] == str(moved)
