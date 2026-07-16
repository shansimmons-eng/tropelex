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
    get_repo_summary,
    detect_tech_stack,
    detect_tech_stack_changes,
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
