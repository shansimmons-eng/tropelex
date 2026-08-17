"""Tests for core.ghost.diff_source.recent_diffs (P4, Adversarial
Hardening plan) -- wires real git diffs into ghost detection, which
previously always got diff_data=[] and so could never detect anything.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from core.ghost.diff_source import recent_diffs


def _make_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=path, check=True)


def _commit(path: Path, filename: str, content: str, message: str) -> None:
    (path / filename).write_text(content)
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=path, check=True)


class TestRecentDiffs:
    def test_no_repo_path_returns_empty(self):
        assert recent_diffs({}) == []
        assert recent_diffs({"repo_path": None}) == []

    def test_repo_path_not_a_directory_returns_empty(self, tmp_path):
        missing = tmp_path / "does-not-exist"
        assert recent_diffs({"repo_path": str(missing)}) == []

    def test_directory_that_is_not_a_git_repo_returns_empty(self, tmp_path):
        plain = tmp_path / "plain"
        plain.mkdir()
        assert recent_diffs({"repo_path": str(plain)}) == []

    def test_real_repo_with_no_commits_returns_empty(self, tmp_path):
        repo = tmp_path / "repo"
        _make_repo(repo)
        assert recent_diffs({"repo_path": str(repo)}) == []

    def test_real_repo_returns_diff_entries(self, tmp_path):
        repo = tmp_path / "repo"
        _make_repo(repo)
        _commit(repo, "a.py", "print('hello')\n", "Add a.py")

        diffs = recent_diffs({"repo_path": str(repo)})

        assert len(diffs) == 1
        assert "file" in diffs[0] and "diff_text" in diffs[0]
        assert "a.py" in diffs[0]["diff_text"]
        assert "print" in diffs[0]["diff_text"]

    def test_max_diffs_caps_results(self, tmp_path):
        repo = tmp_path / "repo"
        _make_repo(repo)
        for i in range(5):
            _commit(repo, f"f{i}.py", f"x = {i}\n", f"Add f{i}")

        diffs = recent_diffs({"repo_path": str(repo)}, max_diffs=2)

        assert len(diffs) == 2

    def test_since_ts_excludes_commits_before_it(self, tmp_path):
        import time
        from datetime import datetime, timezone

        repo = tmp_path / "repo"
        _make_repo(repo)
        _commit(repo, "old.py", "x = 1\n", "Old commit")
        time.sleep(1.1)  # git --since has 1s resolution
        marker = datetime.now(timezone.utc).isoformat()
        time.sleep(1.1)
        _commit(repo, "new.py", "y = 2\n", "New commit")

        diffs = recent_diffs({"repo_path": str(repo)}, since_ts=marker)

        assert len(diffs) == 1
        assert "new.py" in diffs[0]["diff_text"]

    def test_no_repo_path_never_shells_out(self, monkeypatch):
        """A project with no repo_path must never even attempt a git
        subprocess call -- confirms the graceful skip is a true short
        circuit, not just an empty result from a failed call."""
        def _boom(*args, **kwargs):
            raise AssertionError("should not shell out with no repo_path")

        monkeypatch.setattr("subprocess.run", _boom)
        assert recent_diffs({}) == []
